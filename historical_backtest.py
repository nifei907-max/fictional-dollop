#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史 1 分钟 K 线回测脚本（纯标准库，无 pandas 依赖）

用途：
- 读取 time/open/high/low/close/volume CSV
- 按当前系统核心逻辑做历史回测：EMA7/EMA30 趋势、EMA7 回踩、K线方向确认、
  RSI/ATR/连续K线过滤、偶数点止盈止损
- 输出胜率、总盈亏、盈亏比、最大回撤、交易明细等

示例：
    python historical_backtest.py historical_klines.csv
    python historical_backtest.py historical_klines.csv --slippage 0.5 --commission 1
    python historical_backtest.py historical_klines.csv --export-trades backtest_trades.csv

CSV 字段要求：
    time,open,high,low,close,volume
或：
    timestamp,open,high,low,close,volume
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class Candle:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Trade:
    side: str
    entry_time: str
    exit_time: str
    entry: float
    stop: float
    take: float
    exit: float
    pnl: float
    bars_held: int
    reason: str
    signal_reason: str


@dataclass
class BacktestConfig:
    ema_fast: int = 7
    ema_trend: int = 30
    rsi_period: int = 14
    atr_period: int = 14
    support_window: int = 15
    pullback_distance: float = 2.0
    atr_min: float = 1.5
    atr_max: float = 8.0
    atr_clamp_min: float = 1.5
    atr_clamp_max: float = 4.0
    stop_atr_mult: float = 0.8
    take_atr_mult: float = 1.5
    max_consecutive_candles: int = 5
    max_hold_bars: int = 20
    slippage: float = 0.0
    commission: float = 0.0
    conservative_same_bar: bool = True


def _read_candles_from_reader(reader: csv.DictReader) -> list[Candle]:
    candles: list[Candle] = []
    if reader.fieldnames is None:
        raise ValueError("CSV 没有表头")
    fields = {name.strip().lower(): name for name in reader.fieldnames}
    time_key = fields.get("time") or fields.get("timestamp")
    required = ["open", "high", "low", "close"]
    missing = [key for key in required if key not in fields]
    if time_key is None:
        missing.append("time/timestamp")
    if missing:
        raise ValueError(f"CSV 缺少字段: {missing}")

    for row in reader:
        if not row or not row.get(time_key, "").strip():
            continue
        try:
            candles.append(
                Candle(
                    time=row[time_key].strip(),
                    open=float(row[fields["open"]]),
                    high=float(row[fields["high"]]),
                    low=float(row[fields["low"]]),
                    close=float(row[fields["close"]]),
                    volume=float(row.get(fields.get("volume", ""), 0) or 0),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"K线数据解析失败: {row}") from exc
    return candles


def read_candles(path: str | Path) -> list[Candle]:
    if str(path) == "-":
        return _read_candles_from_reader(csv.DictReader(sys.stdin))
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return _read_candles_from_reader(csv.DictReader(f))


def ema_series(values: list[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("EMA period 必须大于 0")
    alpha = 2 / (period + 1)
    out: list[float] = []
    ema = values[0]
    for value in values:
        ema = value * alpha + ema * (1 - alpha)
        out.append(ema)
    return out


def rsi(values: list[float], period: int) -> float:
    if len(values) < period + 1:
        return 50.0
    gains = []
    losses = []
    recent = values[-period - 1 :]
    for prev, cur in zip(recent, recent[1:]):
        diff = cur - prev
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(candles: list[Candle], period: int) -> float:
    if len(candles) < 2:
        return 0.0
    trs = []
    start = max(1, len(candles) - period)
    for i in range(start, len(candles)):
        cur = candles[i]
        prev = candles[i - 1]
        tr = max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def consecutive_count(candles: list[Candle], direction: str) -> int:
    count = 0
    for candle in reversed(candles):
        if direction == "bull" and candle.close > candle.open:
            count += 1
        elif direction == "bear" and candle.close < candle.open:
            count += 1
        else:
            break
    return count


def round_even_price(price: float) -> int:
    return int(round(price / 2) * 2)


def even_points(points: float, minimum: int) -> int:
    value = max(minimum, int(round(points)))
    return max(2, int(round(value / 2) * 2))


def active_imbalance_proxy(candles: list[Candle], window: int = 10) -> float:
    """无 tick/盘口历史时，用最近收盘方向近似主动买卖差。"""
    if len(candles) < 2:
        return 0.0
    recent = candles[-window:]
    up = 0
    down = 0
    for prev, cur in zip(recent, recent[1:]):
        if cur.close > prev.close:
            up += 1
        elif cur.close < prev.close:
            down += 1
    total = up + down
    if total == 0:
        return 0.0
    return (up - down) / total


def find_signal(candles: list[Candle], cfg: BacktestConfig) -> Optional[dict]:
    if len(candles) < max(cfg.ema_trend, cfg.atr_period, cfg.rsi_period, cfg.support_window) + 2:
        return None

    closes = [c.close for c in candles]
    ema_fast = ema_series(closes, cfg.ema_fast)
    ema_trend = ema_series(closes, cfg.ema_trend)
    cur = candles[-1]
    prev = candles[-2]

    current_atr = atr(candles, cfg.atr_period)
    if current_atr < cfg.atr_min or current_atr > cfg.atr_max:
        return None

    current_rsi = rsi(closes, cfg.rsi_period)
    if current_rsi > 85 or current_rsi < 15:
        return None

    if consecutive_count(candles, "bull") >= cfg.max_consecutive_candles:
        return None
    if consecutive_count(candles, "bear") >= cfg.max_consecutive_candles:
        return None

    trend_up = cur.close > ema_trend[-1] and ema_fast[-1] > ema_trend[-1]
    trend_down = cur.close < ema_trend[-1] and ema_fast[-1] < ema_trend[-1]
    near_ema = abs(cur.close - ema_fast[-1]) <= cfg.pullback_distance
    momentum = cur.close - prev.close
    imbalance = active_imbalance_proxy(candles)

    clamped_atr = min(cfg.atr_clamp_max, max(cfg.atr_clamp_min, current_atr))
    stop_points = even_points(clamped_atr * cfg.stop_atr_mult, 2)
    take_points = even_points(clamped_atr * cfg.take_atr_mult, 4)
    entry = round_even_price(cur.close)

    if trend_up and near_ema and cur.close >= cur.open and momentum > 0 and imbalance > 0:
        return {
            "side": "LONG",
            "entry": entry,
            "stop": entry - stop_points,
            "take": entry + take_points,
            "reason": "EMA30上涨趋势 + 回踩EMA7 + 阳线动量确认",
        }

    if trend_down and near_ema and cur.close <= cur.open and momentum < 0 and imbalance < 0:
        return {
            "side": "SHORT",
            "entry": entry,
            "stop": entry + stop_points,
            "take": entry - take_points,
            "reason": "EMA30下跌趋势 + 反弹EMA7 + 阴线动量确认",
        }

    # 支撑/压力假突破反转（顺趋势过滤）
    prev_window = candles[-cfg.support_window - 1 : -1]
    resistance = max(c.high for c in prev_window)
    support = min(c.low for c in prev_window)
    if prev.close > resistance and cur.close < cur.open and trend_down:
        return {
            "side": "SHORT",
            "entry": entry,
            "stop": entry + stop_points,
            "take": entry - take_points,
            "reason": "压力假突破回落 + 下跌趋势确认",
        }
    if prev.close < support and cur.close > cur.open and trend_up:
        return {
            "side": "LONG",
            "entry": entry,
            "stop": entry - stop_points,
            "take": entry + take_points,
            "reason": "支撑假跌破收回 + 上涨趋势确认",
        }

    return None


def simulate_trade(candles: list[Candle], signal_index: int, signal: dict, cfg: BacktestConfig) -> Trade:
    side = signal["side"]
    entry = float(signal["entry"])
    stop = float(signal["stop"])
    take = float(signal["take"])
    if side == "LONG":
        effective_entry = entry + cfg.slippage
    else:
        effective_entry = entry - cfg.slippage

    last_index = min(len(candles) - 1, signal_index + cfg.max_hold_bars)
    exit_price = candles[last_index].close
    exit_reason = "超时平仓"
    exit_index = last_index

    for i in range(signal_index + 1, last_index + 1):
        bar = candles[i]
        if side == "LONG":
            hit_stop = bar.low <= stop
            hit_take = bar.high >= take
            if hit_stop and (cfg.conservative_same_bar or not hit_take):
                exit_price = stop - cfg.slippage
                exit_reason = "止损"
                exit_index = i
                break
            if hit_take:
                exit_price = take + cfg.slippage
                exit_reason = "止盈"
                exit_index = i
                break
            if hit_stop:
                exit_price = stop - cfg.slippage
                exit_reason = "止损"
                exit_index = i
                break
        else:
            hit_stop = bar.high >= stop
            hit_take = bar.low <= take
            if hit_stop and (cfg.conservative_same_bar or not hit_take):
                exit_price = stop + cfg.slippage
                exit_reason = "止损"
                exit_index = i
                break
            if hit_take:
                exit_price = take - cfg.slippage
                exit_reason = "止盈"
                exit_index = i
                break
            if hit_stop:
                exit_price = stop + cfg.slippage
                exit_reason = "止损"
                exit_index = i
                break

    direction = 1 if side == "LONG" else -1
    pnl = (exit_price - effective_entry) * direction - cfg.commission
    return Trade(
        side=side,
        entry_time=candles[signal_index].time,
        exit_time=candles[exit_index].time,
        entry=effective_entry,
        stop=stop,
        take=take,
        exit=exit_price,
        pnl=pnl,
        bars_held=exit_index - signal_index,
        reason=exit_reason,
        signal_reason=signal["reason"],
    )


def run_backtest(candles: list[Candle], cfg: BacktestConfig) -> list[Trade]:
    trades: list[Trade] = []
    i = max(cfg.ema_trend, cfg.atr_period, cfg.rsi_period, cfg.support_window) + 2
    while i < len(candles) - 1:
        history = candles[: i + 1]
        signal = find_signal(history, cfg)
        if signal is None:
            i += 1
            continue
        trade = simulate_trade(candles, i, signal, cfg)
        trades.append(trade)
        # 已有持仓时不重复开仓；下一次从平仓后一根继续。
        i += max(trade.bars_held, 1)
    return trades


def summarize(trades: list[Trade]) -> dict[str, str]:
    if not trades:
        return {
            "总交易次数": "0",
            "胜率": "0.00%",
            "总盈亏": "0.00",
            "最大回撤": "0.00",
        }

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_win / gross_loss if gross_loss else math.inf
    reason_counts = Counter(t.reason for t in trades)
    side_counts = Counter(t.side for t in trades)

    return {
        "总交易次数": str(len(trades)),
        "做多次数": str(side_counts.get("LONG", 0)),
        "做空次数": str(side_counts.get("SHORT", 0)),
        "盈利次数": str(len(wins)),
        "亏损次数": str(len(losses)),
        "胜率": f"{len(wins) / len(trades):.2%}",
        "总盈亏": f"{sum(pnls):.2f}",
        "平均盈亏": f"{sum(pnls) / len(pnls):.2f}",
        "最大盈利": f"{max(pnls):.2f}",
        "最大亏损": f"{min(pnls):.2f}",
        "盈亏比/ProfitFactor": "∞" if math.isinf(profit_factor) else f"{profit_factor:.2f}",
        "最大回撤": f"{max_drawdown:.2f}",
        "平均持仓K数": f"{sum(t.bars_held for t in trades) / len(trades):.2f}",
        "平仓原因": dict(reason_counts),
    }


def print_report(candles: list[Candle], trades: list[Trade], show_trades: int) -> None:
    print("=" * 72)
    print("历史K线回测结果")
    print("=" * 72)
    print(f"K线数量: {len(candles)}")
    if candles:
        print(f"时间范围: {candles[0].time} → {candles[-1].time}")
    print("-" * 72)
    for key, value in summarize(trades).items():
        print(f"{key}: {value}")

    if show_trades > 0 and trades:
        print("-" * 72)
        print(f"最近 {min(show_trades, len(trades))} 笔交易:")
        for trade in trades[-show_trades:]:
            print(
                f"{trade.entry_time} {trade.side:<5} entry={trade.entry:.1f} "
                f"stop={trade.stop:.1f} take={trade.take:.1f} -> "
                f"{trade.exit_time} exit={trade.exit:.1f} pnl={trade.pnl:.2f} "
                f"{trade.reason} | {trade.signal_reason}"
            )


def export_trades(path: str | Path, trades: Iterable[Trade]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "side",
                "entry_time",
                "exit_time",
                "entry",
                "stop",
                "take",
                "exit",
                "pnl",
                "bars_held",
                "reason",
                "signal_reason",
            ],
        )
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade.__dict__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="历史K线策略回测")
    parser.add_argument("csv_path", help="历史K线CSV路径；传 '-' 可从标准输入读取")
    parser.add_argument("--slippage", type=float, default=0.0, help="单边滑点，单位：点")
    parser.add_argument("--commission", type=float, default=0.0, help="每笔交易成本，单位：点")
    parser.add_argument("--max-hold-bars", type=int, default=20, help="最多持仓K线数")
    parser.add_argument("--pullback-distance", type=float, default=2.0, help="距离EMA7多少点内视为回踩")
    parser.add_argument("--show-trades", type=int, default=20, help="显示最近N笔交易")
    parser.add_argument("--export-trades", default="", help="导出交易明细CSV路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = BacktestConfig(
        slippage=args.slippage,
        commission=args.commission,
        max_hold_bars=args.max_hold_bars,
        pullback_distance=args.pullback_distance,
    )
    candles = read_candles(args.csv_path)
    trades = run_backtest(candles, cfg)
    print_report(candles, trades, args.show_trades)
    if args.export_trades:
        export_trades(args.export_trades, trades)
        print(f"交易明细已导出: {args.export_trades}")


if __name__ == "__main__":
    main()
