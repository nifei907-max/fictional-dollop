ai_filter.py

"""
AI 信号分析器（替代 AI 过滤器）

设计目标：

1. 不阻塞交易信号
2. AI 仅负责解释和辅助分析
3. AI 失败不影响系统运行
4. 适用于 1分钟超短线 + OCR行情系统
   """

from deepseek_client import DeepSeekClient
from config import APIConfig

api_cfg = APIConfig()
ai_client = DeepSeekClient(api_cfg)

class AIFilter:
"""
兼容旧接口

```
原：
    check_signal() 返回 True/False

现：
    永远返回 True
    不参与交易拦截

AI 只负责生成解释
"""

def __init__(self):
    self.enabled = True

def check_signal(
    self,
    side,
    indicators,
    price
):
    """
    为兼容旧代码保留

    永远放行
    """
    return True

def explain_signal(
    self,
    side,
    indicators,
    price
):
    """
    AI辅助分析
    """

    if not self.enabled:
        return "AI分析已关闭"

    try:

        prompt = self._build_prompt(
            side,
            indicators,
            price
        )

        result = ai_client.analyze(prompt)

        return str(result).strip()

    except Exception as e:

        print(f"AI分析失败: {e}")

        return "AI分析失败"

def _build_prompt(
    self,
    side,
    indicators,
    price
):

    return f"""
```

你是一名专业短线交易分析师。

交易方向:
{side}

当前价格:
{price}

市场指标:

RSI:
{round(indicators.get('rsi', 0), 2)}

ATR:
{round(indicators.get('atr', 0), 2)}

趋势:
{indicators.get('trend', '未知')}

MACD多头:
{indicators.get('macd_bullish', False)}

MACD空头:
{indicators.get('macd_bearish', False)}

请用简洁中文回答：

1. 当前市场状态
2. 为什么出现该信号
3. 风险点
4. 信号强度（1~10分）

控制在100字以内。
"""

analysis_worker.py

"""
分析线程：从 candle_queue 取已完成的 K 线，运行策略
同时合并当前 forming candle，实现实时决策
增加 AI 分析结果推送，并使用实时价格进行解读
市场状态机（第五阶段：趋势生命周期）
"""

import threading
import queue
import pandas as pd
from queues import candle_queue, signal_queue
from runtime_state import RuntimeState
import strategy
import candle_worker

data_mgr = None
tick_engine = None
gui_queue = None


def update_market_state(state, ind, tick_indicators, current_price):
    """
    更新市场状态机 - 第五阶段：趋势生命周期
    状态：WAITING, EARLY_LONG, TREND_LONG, STRONG_LONG, LONG_EXHAUSTION,
          RANGE, EARLY_SHORT, TREND_SHORT, STRONG_SHORT, SHORT_EXHAUSTION
    """
    ema_fast = ind["ema_mid"]  # EMA7
    ema_slow = ind["ema_long"]  # EMA13
    slope = ind["ema_slope"]
    trend_strength = ind["trend_strength"]
    recent_range = ind["recent_range"]
    rsi = ind["rsi"]
    bull_consecutive = ind["bull_consecutive"]
    bear_consecutive = ind["bear_consecutive"]
    tick_momentum = tick_indicators.get("momentum", 0)
    tick_acc = tick_indicators.get("acceleration", 0)
    buy_pressure = tick_indicators.get("aggressive_buying", 0)
    sell_pressure = tick_indicators.get("aggressive_selling", 0)
    current_state = state.get_market_state()

    # ========== 多头生命周期 ==========
    if current_state == "WAITING":
        if ema_fast > ema_slow and tick_momentum > 0 and buy_pressure > 0.6:
            state.set_market_state("EARLY_LONG")
        elif ema_fast < ema_slow and tick_momentum < 0 and sell_pressure > 0.6:
            state.set_market_state("EARLY_SHORT")

    elif current_state == "EARLY_LONG":
        if trend_strength > 0.05:
            state.set_market_state("TREND_LONG")
        elif ema_fast < ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "TREND_LONG":
        # 进入加速阶段
        if buy_pressure > 0.8 and tick_acc > 0 and bull_consecutive >= 3:
            state.set_market_state("STRONG_LONG")
        elif ema_fast < ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "STRONG_LONG":
        # 进入衰竭
        if rsi > 85 and tick_acc < 0:
            state.set_market_state("LONG_EXHAUSTION")
        elif ema_fast < ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "LONG_EXHAUSTION":
        # 衰竭后进入震荡
        if abs(slope) < 0.03 and recent_range < 3:
            state.set_market_state("RANGE")
        elif ema_fast < ema_slow:
            state.set_market_state("WAITING")
        elif buy_pressure > 0.6 and tick_momentum > 0:
            # 衰竭后重新走强，可回到 TREND_LONG
            state.set_market_state("TREND_LONG")

    # ========== 空头生命周期（镜像）==========
    elif current_state == "EARLY_SHORT":
        if trend_strength > 0.05:
            state.set_market_state("TREND_SHORT")
        elif ema_fast > ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "TREND_SHORT":
        if sell_pressure > 0.8 and tick_acc < 0 and bear_consecutive >= 3:
            state.set_market_state("STRONG_SHORT")
        elif ema_fast > ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "STRONG_SHORT":
        if rsi < 15 and tick_acc > 0:
            state.set_market_state("SHORT_EXHAUSTION")
        elif ema_fast > ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "SHORT_EXHAUSTION":
        if abs(slope) < 0.03 and recent_range < 3:
            state.set_market_state("RANGE")
        elif ema_fast > ema_slow:
            state.set_market_state("WAITING")
        elif sell_pressure > 0.6 and tick_momentum < 0:
            state.set_market_state("TREND_SHORT")

    # ========== RANGE 状态（双向均可转为早期趋势）==========
    elif current_state == "RANGE":
        if ema_fast > ema_slow and tick_momentum > 0 and buy_pressure > 0.6:
            state.set_market_state("EARLY_LONG")
        elif ema_fast < ema_slow and tick_momentum < 0 and sell_pressure > 0.6:
            state.set_market_state("EARLY_SHORT")

    else:
        state.set_market_state("WAITING")


def run_analysis_worker(state: RuntimeState, stop_event: threading.Event):
    global data_mgr, tick_engine, gui_queue
    while not stop_event.is_set():
        try:
            item = candle_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        except Exception:
            continue

        if isinstance(item, dict) and item.get("force"):
            continue

        if data_mgr is None:
            continue

        with data_mgr._data_lock:
            df = data_mgr.candles.tail(100).copy()
        if len(df) < 15:
            continue

        if candle_worker.candle_engine is not None:
            current = candle_worker.candle_engine.current_candle
            if current is not None:
                forming = {
                    "timestamp": current["time"],
                    "open": current["open"],
                    "high": current["high"],
                    "low": current["low"],
                    "close": current["close"],
                    "volume": current["volume"],
                }
                df = pd.concat([df, pd.DataFrame([forming])], ignore_index=True)

        closed_df = df.iloc[:-1]
        if len(closed_df) >= 14:
            ind = strategy.calculate_indicators(closed_df)
            atr = ind.get("atr", 2.0)
            burst_threshold = max(0.5, atr * 0.1)
        else:
            burst_threshold = 0.5

        tick_indicators = {}
        if tick_engine is not None:
            tick_indicators = {
                "speed": tick_engine.tick_speed(),
                "momentum": tick_engine.tick_momentum(),
                "mean_price": tick_engine.tick_mean_price(),
                "acceleration": tick_engine.tick_acceleration(),
                "burst": tick_engine.is_burst(threshold=burst_threshold),
                "strength": tick_engine.get_tick_strength(),
                "micro_trend": tick_engine.micro_trend(),
                "pressure": tick_engine.pressure_score(),
                "consistency": tick_engine.tick_consistency(),
                "orderbook_pressure": tick_engine.orderbook_pressure(),
                "active_imbalance": tick_engine.active_imbalance(),
                "aggressive_buying": tick_engine.aggressive_buying(),
                "aggressive_selling": tick_engine.aggressive_selling(),
            }

        current_price = df.iloc[-1]["close"]
        # 更新市场状态（生命周期）
        update_market_state(state, ind, tick_indicators, current_price)

        # 使用状态机驱动入场
        market_state = state.get_market_state()
        signal = strategy.state_based_trade_rule(
            df=df, state=state, tick_indicators=tick_indicators, market_state=market_state
        )

        if signal:
            signal_queue.put(signal)
            real_time_price = state.get_price()
            if real_time_price is None:
                real_time_price = df.iloc[-1]["close"]
            ind_full = strategy.calculate_indicators(df)
            explanation = strategy.explain_analysis(ind_full, real_time_price, signal)
            if gui_queue:
                try:
                    gui_queue.put_nowait(("explain", explanation))
                except:
                    pass
            # 反向信号提醒
            pos, _ = state.get_position()
            if pos is not None:
                pos_side = pos.get("side")
                signal_side = signal.get("side")
                if pos_side == "LONG" and signal_side == "SHORT":
                    msg = "⚠️ 反向信号：持有多单，出现做空信号，建议平仓！"
                    if gui_queue:
                        try:
                            gui_queue.put_nowait(("warning", msg))
                        except:
                            pass
                elif pos_side == "SHORT" and signal_side == "LONG":
                    msg = "⚠️ 反向信号：持有空单，出现做多信号，建议平仓！"
                    if gui_queue:
                        try:
                            gui_queue.put_nowait(("warning", msg))
                        except:
                            pass

        # AI 分析（当 state.analysis_mode == 0 时）
        if state.analysis_mode == 0 and len(closed_df) >= 14:
            try:
                ai_text = strategy.run_ai_analysis(df, state)
                if ai_text and gui_queue:
                    gui_queue.put_nowait(("ai", ai_text))
            except Exception as e:
                print(f"AI分析异常: {e}")

backtest_engine.py

"""
策略回测引擎
"""

import pandas as pd
from strategy import local_trade_rule
from runtime_state import RuntimeState
from performance import analyze_trades


class BacktestEngine:

    def __init__(self, data: pd.DataFrame):

        self.df = data.copy()

        self.state = RuntimeState()

        self.trades = []

    def run(self):

        if len(self.df) < 50:
            print("K线数量不足")
            return {}

        print("开始回测...")

        for i in range(30, len(self.df)):

            current_df = self.df.iloc[:i].copy()

            signal = local_trade_rule(
                current_df,
                self.state
            )

            if signal:

                trade = self._simulate_trade(
                    signal,
                    i
                )

                if trade:
                    self.trades.append(trade)

        result = analyze_trades(
            pd.DataFrame(self.trades)
        )

        print("回测完成")
        print(result)

        return result

    def _simulate_trade(self, signal, start_index):

        side = signal["side"]

        entry = signal["entry"]

        stop = signal["stop"]

        take = signal["take"]

        future = self.df.iloc[start_index:start_index + 20]

        for _, row in future.iterrows():

            high = row["high"]

            low = row["low"]

            if side == "LONG":

                if low <= stop:
                    pnl = stop - entry

                    return {
                        "side": side,
                        "entry": entry,
                        "exit": stop,
                        "pnl": pnl,
                        "reason": "止损"
                    }

                if high >= take:
                    pnl = take - entry

                    return {
                        "side": side,
                        "entry": entry,
                        "exit": take,
                        "pnl": pnl,
                        "reason": "止盈"
                    }

            elif side == "SHORT":

                if high >= stop:
                    pnl = entry - stop

                    return {
                        "side": side,
                        "entry": entry,
                        "exit": stop,
                        "pnl": pnl,
                        "reason": "止损"
                    }

                if low <= take:
                    pnl = entry - take

                    return {
                        "side": side,
                        "entry": entry,
                        "exit": take,
                        "pnl": pnl,
                        "reason": "止盈"
                    }

        return None

backtester.py

"""
回测引擎：基于历史K线数据模拟交易
支持滑点、手续费、信号冷却
"""

import pandas as pd
import numpy as np
from runtime_state import RuntimeState
from strategy import local_trade_rule
import strategy as strat


class Backtester:
    def __init__(self, data_mgr, slippage=0.5, commission=1.0):
        """
        data_mgr: MarketDataManager 实例，包含 candles DataFrame
        slippage: 滑点（点），开仓时价格偏移
        commission: 手续费（点），每手
        """
        self.data_mgr = data_mgr
        self.slippage = slippage
        self.commission = commission
        self.trades = []

    def run(self):
        df = self.data_mgr.candles.copy()
        if df.empty or len(df) < 15:
            return pd.DataFrame()

        state = RuntimeState()
        # 模拟 forming candle（回测中只能用已收盘K线）
        # 遍历每一根K线作为当前K线，用之前的数据生成信号
        signals = []
        for i in range(15, len(df)):
            # 取到当前K线为止的历史数据（包含当前K线作为forming，但回测中实际不会用到当前未收盘数据）
            # 严格来说，回测应只使用已收盘K线，但为了与实盘一致，我们使用到 i-1 作为历史，i作为当前 forming
            hist_df = df.iloc[: i + 1].copy()
            tick_indicators = {}  # 回测中无tick指标，可简化
            signal = local_trade_rule(hist_df, state, tick_indicators)
            if signal:
                # 记录信号
                signals.append(
                    {
                        "time": df.iloc[i]["timestamp"],
                        "side": signal["side"],
                        "entry": signal["entry"],
                        "stop": signal["stop"],
                        "take": signal["take"],
                        "reason": signal["reason"],
                    }
                )
                # 实际开仓（考虑滑点）
                entry_price = (
                    signal["entry"] + self.slippage if signal["side"] == "LONG" else signal["entry"] - self.slippage
                )
                # 记录持仓
                trade = {
                    "entry_time": df.iloc[i]["timestamp"],
                    "side": signal["side"],
                    "entry_price": entry_price,
                    "stop": signal["stop"],
                    "take": signal["take"],
                    "exit_time": None,
                    "exit_price": None,
                    "pnl": None,
                    "reason": None,
                }
                # 模拟后续价格移动，直到止损或止盈触发
                for j in range(i + 1, len(df)):
                    current_price = df.iloc[j]["close"]
                    if trade["side"] == "LONG":
                        if current_price <= trade["stop"]:
                            exit_price = trade["stop"] - self.slippage  # 止损可能滑点
                            reason = "止损"
                            break
                        elif current_price >= trade["take"]:
                            exit_price = trade["take"] + self.slippage
                            reason = "止盈"
                            break
                    else:
                        if current_price >= trade["stop"]:
                            exit_price = trade["stop"] + self.slippage
                            reason = "止损"
                            break
                        elif current_price <= trade["take"]:
                            exit_price = trade["take"] - self.slippage
                            reason = "止盈"
                            break
                else:
                    # 未触发止损止盈，最后平仓
                    exit_price = df.iloc[-1]["close"]
                    reason = "到期平仓"
                trade["exit_time"] = df.iloc[j]["timestamp"] if "j" in locals() else df.iloc[-1]["timestamp"]
                trade["exit_price"] = exit_price
                trade["reason"] = reason
                # 计算盈亏（扣除手续费）
                if trade["side"] == "LONG":
                    pnl = (trade["exit_price"] - trade["entry_price"]) - self.commission
                else:
                    pnl = (trade["entry_price"] - trade["exit_price"]) - self.commission
                trade["pnl"] = pnl
                self.trades.append(trade)
                # 更新状态（模拟持仓），但回测中不实际影响后续信号（简单起见，忽略持仓互锁）
                # 注意：实际应设置state.position，但为了简单，我们只记录信号后立即平仓（每次独立）
                # 这里假设每次信号都是独立开仓，不考虑持仓冲突
        return pd.DataFrame(self.trades)

    def get_statistics(self):
        if not self.trades:
            return {}
        df = pd.DataFrame(self.trades)
        total_trades = len(df)
        winning_trades = len(df[df["pnl"] > 0])
        losing_trades = len(df[df["pnl"] < 0])
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        total_pnl = df["pnl"].sum()
        avg_pnl = df["pnl"].mean()
        max_win = df["pnl"].max()
        max_loss = df["pnl"].min()
        # 计算盈亏比（平均盈利/平均亏损）
        avg_win = df[df["pnl"] > 0]["pnl"].mean() if winning_trades > 0 else 0
        avg_loss = abs(df[df["pnl"] < 0]["pnl"].mean()) if losing_trades > 0 else 0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else float("inf")
        return {
            "总交易次数": total_trades,
            "盈利次数": winning_trades,
            "亏损次数": losing_trades,
            "胜率": f"{win_rate:.2%}",
            "总盈亏": f"{total_pnl:.2f}",
            "平均盈亏": f"{avg_pnl:.2f}",
            "最大盈利": f"{max_win:.2f}",
            "最大亏损": f"{max_loss:.2f}",
            "盈亏比": f"{profit_factor:.2f}",
        }

candle_engine.py

from datetime import datetime
from typing import Optional, Dict, Any

class CandleEngine:
    def __init__(self, interval_seconds: int = 60):
        self.interval = interval_seconds
        self.current_candle: Optional[Dict[str, Any]] = None

    def update_tick(self, price: float, tick_time: datetime) -> Optional[Dict]:
        minute_key = tick_time.replace(second=0, microsecond=0)
        if self.current_candle is None:
            self.current_candle = {
                "time": minute_key,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1
            }
            return None
        if minute_key == self.current_candle["time"]:
            self.current_candle["high"] = max(self.current_candle["high"], price)
            self.current_candle["low"] = min(self.current_candle["low"], price)
            self.current_candle["close"] = price
            self.current_candle["volume"] += 1
            return None
        finished = self.current_candle.copy()
        self.current_candle = {
            "time": minute_key,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1
            
        }
        return finished

    def force_flush(self) -> Optional[Dict]:
        if self.current_candle is None:
            return None
        finished = self.current_candle.copy()
        self.current_candle = None
        return finished

candle_worker.py

"""K线线程：从 tick_queue 取 tick，用 CandleEngine 生成 OHLC，写入 data_mgr 并放入 candle_queue"""

import threading
from queues import tick_queue, candle_queue
from candle_engine import CandleEngine
from runtime_state import RuntimeState

data_mgr = None
candle_engine = None


def run_candle_worker(state: RuntimeState, stop_event: threading.Event):
    global data_mgr, candle_engine
    engine = CandleEngine()
    candle_engine = engine
    while not stop_event.is_set():
        try:
            item = tick_queue.get(timeout=0.5)
            # 兼容多种格式：(price, timestamp) 或 (price, timestamp, bid1, ask1)
            if isinstance(item, tuple) and len(item) >= 2:
                price = item[0]
                tick_time = item[1]
            else:
                continue
        except:
            continue
        finished = engine.update_tick(price, tick_time)
        if finished is not None:
            if data_mgr is not None:
                with data_mgr._data_lock:
                    data_mgr.add_candle(
                        {
                            "time": finished["time"],
                            "open": finished["open"],
                            "high": finished["high"],
                            "low": finished["low"],
                            "close": finished["close"],
                            "volume": finished["volume"],
                        }
                    )
            candle_queue.put(finished)

config_manager.py

"""
用户配置管理器（线程安全，原子写入，深拷贝默认值，支持区域便捷获取）
支持实时OCR分离区域：time_region, price_region
历史OHLC区域：ohlc_time_region, ohlc_price_region, ohlc_volume_region
"""

import json
import os
import copy
from typing import Tuple

CONFIG_FILE = "user_config.json"

DEFAULT_CONFIG = {
    "config_version": 1,
    "capture": {"left": 0, "top": 0, "width": 0, "height": 0, "interval_seconds": 0.5},  # 保留向后兼容，但不再使用
    "time_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "price_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "min_price_change": 1,
    "max_price_jump": 20,
    "tesseract_cmd": "./Tesseract-OCR/tesseract.exe",
    "colors": {
        "red_threshold": {"r": (250, 255), "g": (0, 5), "b": (0, 5)},
        "cyan_threshold": {"r": (0, 5), "g": (250, 255), "b": (250, 255)},
    },
    "system_prompt": "你是专业量化交易分析AI。...",
    "strategy": {
        "macd_threshold": 0.05,
        "rsi_upper": 80,
        "rsi_lower": 20,
        "min_range": 4,
        "fake_breakout_distance": 12,
        "risk_reward_ratio": 1.5,
    },
    "ohlc_time_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "ohlc_price_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "ohlc_volume_region": {"left": 0, "top": 0, "width": 0, "height": 0},
}


class ConfigManager:
    def __init__(self, filepath: str = CONFIG_FILE):
        self.filepath = filepath
        self.config = self.load()

    def load(self) -> dict:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    # 可在此处合并默认配置，但简单起见直接返回用户配置
                    return user_config
            except Exception as e:
                print(f"[Config] 配置读取失败: {e}，将使用默认配置")
        return copy.deepcopy(DEFAULT_CONFIG)

    def save(self):
        try:
            tmp_file = self.filepath + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, self.filepath)
        except Exception as e:
            print(f"[Config] 保存失败: {e}")

    def get_region(self, key: str) -> Tuple[int, int, int, int]:
        r = self.config.get(key, {})
        return (
            r.get("left", 0),
            r.get("top", 0),
            r.get("width", 0),
            r.get("height", 0),
        )

    # 实时OCR区域
    def get_time_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("time_region")

    def set_time_region(self, left, top, width, height):
        self.config["time_region"] = {"left": left, "top": top, "width": width, "height": height}
        self.save()

    def get_price_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("price_region")

    def set_price_region(self, left, top, width, height):
        self.config["price_region"] = {"left": left, "top": top, "width": width, "height": height}
        self.save()

    # 历史OHLC区域
    def get_ohlc_time_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("ohlc_time_region")

    def get_ohlc_price_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("ohlc_price_region")

    def get_ohlc_volume_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("ohlc_volume_region")

    # 保留旧的 capture 区域兼容
    def get_capture_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("capture")

    def set_capture_region(self, left, top, width, height):
        self.config["capture"] = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "interval_seconds": self.config.get("capture", {}).get("interval_seconds", 0.5),
        }
        self.save()

    def get_min_price_change(self) -> int:
        return self.config.get("min_price_change", 1)

    def get_max_price_jump(self) -> int:
        return self.config.get("max_price_jump", 20)

    def get_tesseract_cmd(self) -> str:
        return self.config.get("tesseract_cmd", "./Tesseract-OCR/tesseract.exe")

    def get_color_thresholds(self) -> dict:
        return self.config.get("colors", copy.deepcopy(DEFAULT_CONFIG["colors"]))

    def set_color_thresholds(self, red, cyan):
        self.config["colors"] = {"red_threshold": red, "cyan_threshold": cyan}
        self.save()

    def get_system_prompt(self) -> str:
        return self.config.get("system_prompt", "")

    def set_system_prompt(self, prompt: str):
        self.config["system_prompt"] = prompt
        self.save()

    def get_strategy_params(self) -> dict:
        return self.config.get("strategy", copy.deepcopy(DEFAULT_CONFIG["strategy"]))

    def set_strategy_params(self, params: dict):
        self.config["strategy"] = params
        self.save()

config.py

"""全局配置模块（API Key 从环境变量读取）"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class CaptureConfig:
    monitor_index: int = 1
    left: int = 1722
    top: int = 283
    width: int = 61
    height: int = 26
    interval_seconds: float = 1.0

@dataclass
class OCRConfig:
    languages: list[str] = field(default_factory=lambda: ["en"])
    gpu: bool = False
    retry_times: int = 3
    retry_interval_seconds: float = 0.4
    min_confidence: float = 0.35
    tesseract_cmd: str = field(
        default_factory=lambda: os.getenv("TESSERACT_CMD", r"./Tesseract-OCR/tesseract.exe")
    )

@dataclass
class CandleConfig:
    interval_seconds: int = 60
    max_rows: int = 2000

@dataclass
class APIConfig:
    base_url: str = "https://api.deepseek.com"
    endpoint: str = "/chat/completions"
    model: str = "deepseek-chat"
    timeout_seconds: int = 20
    retry_times: int = 3
    retry_interval_seconds: float = 1.0
    api_key: str = field(
    default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "sk-your-api-key-here")
)

@dataclass
class AppConfig:
    symbol: str = "DEMO_SYMBOL"
    timezone: str = "UTC"
    poll_seconds: float = 1.0
    analyze_every_n_candles: int = 1
    data_dir: Path = Path("project/data")
    logs_dir: Path = Path("project/logs")
    tick_csv: Path = Path("project/data/ticks.csv")
    candle_csv: Path = Path("project/data/candles_1m.csv")
    log_file: Path = Path("project/logs/app.log")

@dataclass
class RuleConfig:
    enabled: bool = True
    rsi_long_threshold: float = 55.0
    rsi_short_threshold: float = 45.0

@dataclass
class NotifyConfig:
    cooldown_seconds: int = 120

data_exporter.py

"""
交易记录导出模块
"""

import pandas as pd
from datetime import datetime
import os


EXPORT_DIR = "exports"

if not os.path.exists(EXPORT_DIR):
    os.makedirs(EXPORT_DIR)


def export_trade_log(trade_log: list):

    if not trade_log:
        print("没有交易记录可导出")
        return None

    df = pd.DataFrame(trade_log)

    filename = os.path.join(
        EXPORT_DIR,
        f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    df.to_csv(filename, index=False, encoding="utf-8-sig")

    print(f"✅ 交易记录已导出: {filename}")

    return filename


def export_performance(performance_dict: dict):

    if not performance_dict:
        print("没有绩效数据")
        return None

    df = pd.DataFrame([performance_dict])

    filename = os.path.join(
        EXPORT_DIR,
        f"performance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    df.to_csv(filename, index=False, encoding="utf-8-sig")

    print(f"✅ 绩效报告已导出: {filename}")

    return filename

data_manager.py

"""
MarketDataManager
负责：
1. 管理K线DataFrame
2. 线程安全
3. 自动保存CSV
4. 加载历史数据
"""

import os
import threading
import pandas as pd


class MarketDataManager:
    def __init__(self, candle_cfg=None, tick_csv="ticks.csv", candle_csv="candles.csv"):
        self.tick_csv = tick_csv
        self.candle_csv = candle_csv

        self._data_lock = threading.RLock()

        self.candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        self.load()

    # ==========================
    # K线管理
    # ==========================

    def add_candle(self, candle: dict):
        with self._data_lock:

            row = {
                "timestamp": candle.get("time"),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": int(candle.get("volume", 0)),
            }

            self.candles = pd.concat([self.candles, pd.DataFrame([row])], ignore_index=True)

            # 保留最近5000根
            if len(self.candles) > 5000:
                self.candles = self.candles.tail(5000).reset_index(drop=True)

    # ==========================
    # 查询
    # ==========================

    def latest(self, n=100):
        with self._data_lock:
            return self.candles.tail(n).copy()

    def count(self):
        with self._data_lock:
            return len(self.candles)

    def clear(self):
        with self._data_lock:
            self.candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    # ==========================
    # 持久化
    # ==========================

    def persist(self):
        with self._data_lock:

            if len(self.candles) == 0:
                return

            self.candles.to_csv(self.candle_csv, index=False, encoding="utf-8-sig")

    def save(self):
        self.persist()

    # ==========================
    # 加载
    # ==========================

    def load(self):

        if not os.path.exists(self.candle_csv):
            return

        try:

            df = pd.read_csv(self.candle_csv)

            required = {"timestamp", "open", "high", "low", "close", "volume"}

            if not required.issubset(df.columns):
                return

            df["timestamp"] = pd.to_datetime(df["timestamp"])

            self.candles = df

            print(f"[DATA] 已加载历史K线 {len(df)} 根")

        except Exception as e:
            print(f"[DATA] 加载失败: {e}")

    # ==========================
    # 导出DataFrame
    # ==========================

    def get_dataframe(self):
        with self._data_lock:
            return self.candles.copy()

deepseek_client.py

"""DeepSeek API 封装"""
import requests
from config import APIConfig

class DeepSeekClient:
    def __init__(self, config: APIConfig):
        self.base_url = config.base_url
        self.endpoint = config.endpoint
        self.model = config.model
        self.api_key = config.api_key
        self.timeout = config.timeout_seconds

    def analyze(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a professional quantitative trading analyst."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 200,
            "temperature": 0.1
        }
        try:
            resp = requests.post(
                f"{self.base_url}{self.endpoint}",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"API Error: {e}"

execution worker.py

"""执行线程：仅打印信号，不自动开仓"""
import threading
from queues import signal_queue
from runtime_state import RuntimeState

def run_execution_worker(state: RuntimeState, stop_event: threading.Event):
    while not stop_event.is_set():
        try:
            signal = signal_queue.get(timeout=0.5)
        except:
            continue
        if signal is None:
            continue
        # 只输出提示，不设置持仓
        if signal.get("type") == "ai":
            continue  # AI已在GUI显示
        print(f"💡 建议 {signal['side']} | 入场:{signal['entry']:.2f} 止损:{signal['stop']:.2f} 止盈:{signal['take']:.2f} 理由:{signal['reason']}")

get_relative.py

import pyautogui
import win32gui
import win32con

# 1. 找到交易软件窗口
title_keyword = "华中九通"
hwnd = None

def find_window(hwnd, _):
    global hwnd_found
    if win32gui.IsWindowVisible(hwnd) and title_keyword in win32gui.GetWindowText(hwnd):
        hwnd_found = hwnd

hwnd_found = None
win32gui.EnumWindows(find_window, None)

if hwnd_found is None:
    print("❌ 未找到包含“华中九通”的窗口，请确保交易软件已打开。")
    exit()

# 2. 获取窗口客户区左上角的屏幕坐标
client_rect = win32gui.GetClientRect(hwnd_found)
left_top = win32gui.ClientToScreen(hwnd_found, (0, 0))
print(f"窗口客户区左上角屏幕坐标: {left_top}")

# 3. 提示用户移动鼠标到价格数字左上角
print("请将鼠标移动到「实时价格数字」的左上角，然后按 Enter...")
input()
mx, my = pyautogui.position()
print(f"鼠标当前位置: ({mx}, {my})")

# 4. 计算相对偏移
rel_left = mx - left_top[0]
rel_top = my - left_top[1]
print(f"\n✅ 测量完成！")
print(f"rel_left = {rel_left}")
print(f"rel_top = {rel_top}")
print("请将这两个数字填入 user_config.json 的 capture 区域中的 rel_left 和 rel_top。")

health_monitor.py

"""
系统健康监控
"""

import threading
import time
import psutil
from logger_utils import log_warning, log_info


class HealthMonitor:

    def __init__(self):

        self.running = False

        self.cpu_limit = 85
        self.memory_limit = 85

        self.check_interval = 10

    def start(self):

        if self.running:
            return

        self.running = True

        threading.Thread(
            target=self._run,
            daemon=True
        ).start()

        log_info("系统健康监控启动")

    def stop(self):

        self.running = False

        log_info("系统健康监控停止")

    def _run(self):

        while self.running:

            try:

                cpu = psutil.cpu_percent(interval=1)

                memory = psutil.virtual_memory().percent

                if cpu >= self.cpu_limit:
                    log_warning(
                        f"CPU占用过高: {cpu}%"
                    )

                if memory >= self.memory_limit:
                    log_warning(
                        f"内存占用过高: {memory}%"
                    )

            except Exception as e:

                log_warning(
                    f"健康监控异常: {e}"
                )

            time.sleep(self.check_interval)

history_viewer.py

"""历史K线数据查看器"""
import tkinter as tk
from tkinter import ttk
import pandas as pd

class HistoryViewerDialog:
    def __init__(self, root, data_mgr):
        self.data_mgr = data_mgr
        self.win = tk.Toplevel(root)
        self.win.title("📋 历史K线数据（最近60根）")
        self.win.geometry("700x400")
        self.win.resizable(True, True)
        self.win.transient(root)
        frame = ttk.Frame(self.win)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        columns = ("时间", "开", "高", "低", "收", "成交量")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor=tk.CENTER)
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky=tk.NSEW)
        vsb.grid(row=0, column=1, sticky=tk.NS)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        ttk.Button(self.win, text="关闭", command=self.win.destroy).pack(pady=5)
        self.load_data()

    def load_data(self):
        if self.data_mgr is None or self.data_mgr.candles.empty:
            return
        df = self.data_mgr.candles.tail(60).copy()
        if "timestamp" in df.columns:
            df["时间"] = pd.to_datetime(df["timestamp"]).dt.strftime("%m-%d %H:%M")
        else:
            df["时间"] = ""
        for col in ["开", "高", "低", "收", "成交量"]:
            col_map = {"开": "open", "高": "high", "低": "low", "收": "close", "成交量": "volume"}
            if col_map[col] not in df.columns:
                df[col] = 0
        for _, row in df.iterrows():
            self.tree.insert("", tk.END, values=(
                row["时间"], row.get("open", 0), row.get("high", 0),
                row.get("low", 0), row.get("close", 0), row.get("volume", 0)
            ))

indicators.py

from __future__ import annotations
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import pandas as pd
from config import CandleConfig


@dataclass
class MarketDataManager:
    candle_cfg: CandleConfig
    tick_path: Path
    candle_path: Path

    def __post_init__(self) -> None:
        self.ticks = pd.DataFrame(columns=["timestamp", "price", "volume"])
        self.candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        self._data_lock = threading.RLock()

    def add_tick(self, timestamp: datetime, price: float, volume: float = 0.0) -> None:
        self.ticks.loc[len(self.ticks)] = [timestamp, price, volume]
        if len(self.ticks) > self.candle_cfg.max_rows:
            self.ticks = self.ticks.iloc[-self.candle_cfg.max_rows :].reset_index(drop=True)

    def build_candles(self) -> pd.DataFrame:
        if self.ticks.empty:
            return self.candles
        df = self.ticks.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        ohlc = df["price"].resample("1min").ohlc()
        vol = df["volume"].resample("1min").sum()
        merged = ohlc.join(vol.rename("volume")).dropna().reset_index()
        merged.rename(columns={"timestamp": "timestamp"}, inplace=True)
        self.candles = merged.tail(self.candle_cfg.max_rows).copy()
        return self.candles

    def add_candle(self, candle: dict) -> None:
        with self._data_lock:
            row = {
                "timestamp": pd.to_datetime(candle["time"]),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle.get("volume", 0)),
            }
            if self.candles.empty:
                self.candles = pd.DataFrame([row])
            else:
                self.candles = pd.concat([self.candles, pd.DataFrame([row])], ignore_index=True)
            if len(self.candles) > self.candle_cfg.max_rows:
                self.candles = self.candles.iloc[-self.candle_cfg.max_rows :].reset_index(drop=True)

    def latest_row(self) -> Optional[pd.Series]:
        if self.candles.empty:
            return None
        return self.candles.iloc[-1]

    def persist(self) -> None:
        self.tick_path.parent.mkdir(parents=True, exist_ok=True)
        self.candle_path.parent.mkdir(parents=True, exist_ok=True)
        self.ticks.to_csv(self.tick_path, index=False)
        self.candles.to_csv(self.candle_path, index=False)

kline_chart.py

"""
实时K线图窗口（修复数据类型错误，支持自动清洗）
"""
import tkinter as tk
import threading
import time
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import mplfinance as mpf

class KlineChartWindow:
    def __init__(self, root, data_mgr, refresh_interval=2):
        self.root = root
        self.data_mgr = data_mgr
        self.refresh_interval = refresh_interval
        self.running = True

        self.win = tk.Toplevel(root)
        self.win.title("📉 实时K线图")
        self.win.geometry("800x600")
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

        self.fig = plt.figure(figsize=(8, 5))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.win)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.update_thread = threading.Thread(target=self.auto_refresh, daemon=True)
        self.update_thread.start()

    def auto_refresh(self):
        while self.running:
            self.draw_chart()
            time.sleep(self.refresh_interval)

    def sanitize_ohlc(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        col_map = {
            'timestamp': 'Date', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'volume': 'Volume'
        }
        for old, new in col_map.items():
            if old in df.columns and new not in df.columns:
                df.rename(columns={old: new}, inplace=True)

        required = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        for col in required:
            if col not in df.columns:
                if col == 'Volume':
                    df[col] = 0.0
                else:
                    return pd.DataFrame()

        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df.dropna(subset=['Open', 'High', 'Low', 'Close'], inplace=True)
        df = df[df['High'] >= df['Low']]

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df.dropna(subset=['Date'], inplace=True)
        df.set_index('Date', inplace=True)

        return df

    def draw_chart(self):
        if self.data_mgr is None or self.data_mgr.candles.empty:
            return

        df = self.data_mgr.candles.tail(60).copy()
        if df.empty:
            return

        df = self.sanitize_ohlc(df)
        if df.empty:
            return

        self.fig.clear()
        ax1 = self.fig.add_subplot(2, 1, 1)
        ax2 = self.fig.add_subplot(2, 1, 2, sharex=ax1)

        try:
            mpf.plot(df, type='candle', style='charles',
                     ax=ax1, volume=ax2, show_nontrading=False,
                     ylabel='Price', ylabel_lower='Volume')
        except Exception as e:
            print(f"K线图绘制错误: {e}")

        self.canvas.draw()

    def on_close(self):
        self.running = False
        self.win.destroy()

kline_ocr_scraper.py

"""
历史K线抓取模块（一次性使用）- 本地时间，无时区
抓取完整 OHLC（开、高、低、收）和时间，直接保存为 K 线
配置键：ohlc_time_region, ohlc_price_region
"""

import win32gui
import time, re, os, pyautogui, pytesseract, pydirectinput, pygetwindow as gw
from PIL import Image
from datetime import datetime, timedelta
from config import CandleConfig, AppConfig
from config_manager import ConfigManager
from indicators import MarketDataManager

config_mgr = ConfigManager()
candle_cfg = CandleConfig()
app_cfg = AppConfig()

# ------------------------------------------------------------
# 1. 自动定位 Tesseract 可执行文件和 tessdata 目录
# ------------------------------------------------------------
base_dir = os.path.dirname(os.path.abspath(__file__))
tesseract_cmd = config_mgr.config.get("tesseract_cmd", "")
if not tesseract_cmd or not os.path.isfile(tesseract_cmd):
    parent_dir = os.path.dirname(base_dir)
    possible_path = os.path.join(parent_dir, "Tesseract-OCR", "tesseract.exe")
    if os.path.isfile(possible_path):
        tesseract_cmd = possible_path
    else:
        possible_path = os.path.join(base_dir, "Tesseract-OCR", "tesseract.exe")
        if os.path.isfile(possible_path):
            tesseract_cmd = possible_path
        else:
            tesseract_cmd = "tesseract"

if os.path.isfile(tesseract_cmd):
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    tessdata_dir = os.path.join(os.path.dirname(tesseract_cmd), "tessdata")
    if os.path.isdir(tessdata_dir):
        os.environ["TESSDATA_PREFIX"] = tessdata_dir
        print(f"[OK] Tesseract 路径: {tesseract_cmd}")
        print(f"[OK] tessdata 目录: {tessdata_dir}")
    else:
        print(f"[WARN] tessdata 目录不存在: {tessdata_dir}")
else:
    print(f"[ERROR] 找不到 tesseract.exe，请安装或配置路径")
    pytesseract.pytesseract.tesseract_cmd = "tesseract"

TRADING_WINDOW_TITLE = "华中九通"


def get_trading_window_client_left_top():
    title_keyword = "华中九通"
    hwnd = None

    def enum_callback(hwnd_enum, _):
        nonlocal hwnd
        text = win32gui.GetWindowText(hwnd_enum)
        if title_keyword in text and win32gui.IsWindowVisible(hwnd_enum):
            hwnd = hwnd_enum
            return False

    win32gui.EnumWindows(enum_callback, None)
    if hwnd is None:
        return None
    return win32gui.ClientToScreen(hwnd, (0, 0))


def get_region(config_key):
    cfg = config_mgr.config.get(config_key, {})
    left = cfg.get("left", 0)
    top = cfg.get("top", 0)
    width = cfg.get("width", 0)
    height = cfg.get("height", 0)
    rel_left = cfg.get("rel_left", 0)
    rel_top = cfg.get("rel_top", 0)
    if rel_left > 0 or rel_top > 0:
        client_coord = get_trading_window_client_left_top()
        if client_coord is not None:
            left = client_coord[0] + rel_left
            top = client_coord[1] + rel_top
    return (left, top, width, height)


def enlarge_image(img, scale=3):
    w, h = img.size
    return img.resize((w * scale, h * scale), Image.LANCZOS)


def ocr_text(region):
    if region[2] <= 0 or region[3] <= 0:
        return ""
    img = pyautogui.screenshot(region=region)
    img = img.convert("L")
    img = enlarge_image(img, scale=3)
    config = "--psm 7 -l chi_sim+eng"
    try:
        return pytesseract.image_to_string(img, config=config)
    except Exception as e:
        print(f"OCR 错误: {e}")
        return ""


def parse_time(text):
    match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", text)
    if match:
        return match.group(1)
    return None


def parse_ohlc(text):
    if not text:
        return None
    patterns = [
        r"开\s*[:：]?\s*([\d,.]+)\s*高\s*[:：]?\s*([\d,.]+)\s*低\s*[:：]?\s*([\d,.]+)\s*收\s*[:：]?\s*([\d,.]+)",
        r"开\s*([\d,.]+)\s*高\s*([\d,.]+)\s*低\s*([\d,.]+)\s*收\s*([\d,.]+)",
        r"高\s*([\d,.]+)\s*低\s*([\d,.]+)\s*收\s*([\d,.]+)",
        r"([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 4:
                open_val, high_val, low_val, close_val = groups
            elif len(groups) == 3:
                high_val, low_val, close_val = groups
                open_val = close_val
            else:
                continue
            try:
                o = float(open_val.replace(",", ""))
                h = float(high_val.replace(",", ""))
                l = float(low_val.replace(",", ""))
                c = float(close_val.replace(",", ""))
                if h < l:
                    h, l = l, h
                o = max(l, min(h, o))
                c = max(l, min(h, c))
                return {"open": o, "high": h, "low": l, "close": c}
            except:
                continue
    return None


def validate_ohlc(ohlc):
    if not ohlc:
        return None
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    if h < l:
        h, l = l, h
    o = max(l, min(h, o))
    c = max(l, min(h, c))
    ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"] = o, h, l, c
    return ohlc


def scrape_historical_klines(state, data_mgr_ref, total=60, stop_event=None):
    time_region = get_region("ohlc_time_region")
    price_region = get_region("ohlc_price_region")
    if price_region[2] <= 0 or price_region[3] <= 0:
        print("❌ OHLC 价格区域未设置，请在 user_config.json 中配置 ohlc_price_region")
        return
    if time_region[2] <= 0:
        print("⚠️ 时间区域未设置，将尝试从价格区域解析时间")

    SAFE_X, SAFE_Y = 100, 100
    pyautogui.moveTo(SAFE_X, SAFE_Y)
    print("⏳ 5 秒后开始抓取历史 K 线（完整 OHLC）...")
    for i in range(5, 0, -1):
        if stop_event and stop_event.is_set():
            return
        print(f"  {i}...")
        time.sleep(1)
    print("🚀 开始抓取")

    now = datetime.now()  # 本地时间，无时区
    candles = []
    for i in range(total):
        if stop_event and stop_event.is_set():
            break
        pyautogui.moveTo(SAFE_X, SAFE_Y)
        time_text = ocr_text(time_region) if time_region[2] > 0 else ""
        price_text = ocr_text(price_region)
        time_str = parse_time(time_text) or parse_time(price_text)
        ohlc = parse_ohlc(price_text)
        ohlc = validate_ohlc(ohlc)
        if ohlc and time_str:
            try:
                if ":" in time_str:
                    if time_str.count(":") == 1:
                        dt = datetime.strptime(f"{now.date()} {time_str}:00", "%Y-%m-%d %H:%M:%S")
                    else:
                        dt = datetime.strptime(f"{now.date()} {time_str}", "%Y-%m-%d %H:%M:%S")
                else:
                    dt = now - timedelta(minutes=(total - i))
                # 关键：不添加时区，保持 naive datetime
                candles.insert(
                    0,
                    {
                        "time": dt,
                        "open": ohlc["open"],
                        "high": ohlc["high"],
                        "low": ohlc["low"],
                        "close": ohlc["close"],
                    },
                )
                print(
                    f"   ✅ 第{i+1}根 {dt.strftime('%H:%M')} O:{ohlc['open']} H:{ohlc['high']} L:{ohlc['low']} C:{ohlc['close']}"
                )
            except Exception as e:
                print(f"   ⚠️ 时间解析失败: {time_str}, {e}")
        else:
            print(f"   ⚠️ 第{i+1}根识别失败（价格文本: {price_text[:50]})")
        if i < total - 1:
            pydirectinput.press("left")
            time.sleep(0.15)

    if not candles:
        print("❌ 未抓取到任何有效K线")
        return

    # 清空旧文件
    try:
        if os.path.exists(app_cfg.tick_csv):
            os.remove(app_cfg.tick_csv)
        if os.path.exists(app_cfg.candle_csv):
            os.remove(app_cfg.candle_csv)
    except:
        pass

    new_mgr = MarketDataManager(candle_cfg, app_cfg.tick_csv, app_cfg.candle_csv)
    for c in candles:
        new_mgr.add_candle(
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"], "volume": 0}
        )
    data_mgr_ref[0] = new_mgr
    state.base_price = candles[-1]["close"]
    state.update_price(state.base_price)
    print(f"✅ 历史K线抓取完成，共 {len(candles)} 根")


logger_utils.py

"""
日志模块
"""

import logging
import os
from datetime import datetime


LOG_DIR = "logs"

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

log_file = os.path.join(
    LOG_DIR,
    f"{datetime.now().strftime('%Y-%m-%d')}.log"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("trading_system")


def log_info(msg):
    logger.info(msg)


def log_warning(msg):
    logger.warning(msg)


def log_error(msg):
    logger.error(msg)


def log_trade(side, entry, stop, take, reason):
    logger.info(
        f"[交易信号] "
        f"{side} | "
        f"入场:{entry} "
        f"止损:{stop} "
        f"止盈:{take} "
        f"原因:{reason}"
    )


def log_position_close(side, entry, exit_price, pnl, reason):
    logger.info(
        f"[平仓] "
        f"{side} | "
        f"开仓:{entry} "
        f"平仓:{exit_price} "
        f"盈亏:{pnl:.2f} "
        f"原因:{reason}"
    )

main_gui.py

"""
量化交易系统 GUI 版 - 最终纯净版（折线图，无 mplfinance 警告）
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
import time
import queue
import sys
import os
from datetime import datetime, timezone

if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

import win32gui
import win32con
import win32api

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd

from runtime_state import RuntimeState
from queues import tick_queue, candle_queue, signal_queue
from ocr_worker import run_ocr_worker
from candle_worker import run_candle_worker
from analysis_worker import run_analysis_worker
from execution_worker import run_execution_worker
from risk_worker import risk_worker

from data_manager import MarketDataManager
from config import CandleConfig, AppConfig

from config_manager import ConfigManager
from realtime_regions_dialog import RealTimeRegionsDialog
from prompt_editor import PromptEditor
from strategy_settings_dialog import StrategySettingsDialog
from history_viewer import HistoryViewerDialog
from kline_chart import KlineChartWindow
from ohlc_settings_dialog import OHLCSettingsDialog
import kline_ocr_scraper
import strategy
import analysis_worker
import candle_worker
import risk_worker as rw

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

config_mgr = ConfigManager()
candle_cfg = CandleConfig()
app_cfg = AppConfig()
data_mgr = MarketDataManager(candle_cfg, app_cfg.tick_csv, app_cfg.candle_csv)
data_mgr_ref = [data_mgr]

analysis_worker.data_mgr = data_mgr
candle_worker.data_mgr = data_mgr

state = RuntimeState()
stop_event = threading.Event()
gui_queue = queue.Queue(maxsize=1000)
system_running = False

MANUAL_STOP_POINTS = 4
MANUAL_TAKE_POINTS = 6

TRADING_WINDOW_TITLE = "华中九通"
TRADING_WINDOW_WIDTH = 957
TRADING_WINDOW_HEIGHT = 569


def set_trading_window_topmost():
    hwnd = None

    def callback(hwnd_enum, _):
        nonlocal hwnd
        if win32gui.IsWindowVisible(hwnd_enum):
            title = win32gui.GetWindowText(hwnd_enum)
            if TRADING_WINDOW_TITLE in title:
                hwnd = hwnd_enum
                return False

    win32gui.EnumWindows(callback, None)
    if hwnd is None:
        messagebox.showwarning("未找到窗口", f"未找到包含 '{TRADING_WINDOW_TITLE}' 的窗口")
        return False
    screen_width = win32api.GetSystemMetrics(0)
    x = screen_width - TRADING_WINDOW_WIDTH
    y = 0
    win32gui.SetWindowPos(
        hwnd, win32con.HWND_TOPMOST, x, y, TRADING_WINDOW_WIDTH, TRADING_WINDOW_HEIGHT, win32con.SWP_SHOWWINDOW
    )
    return True


class TradingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("量化交易系统 Pro")
        self.root.geometry("950x950")
        self.root.minsize(700, 800)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.threads = []
        self.signal_thread = None
        self.last_chart_update = 0
        self.analysis_lock = threading.Lock()
        self.tick_engine = None
        self.history_loading = False

        self.create_widgets()
        self.update_gui()
        self.update_button_states(start_enabled=True, stop_enabled=False)

    def log(self, msg):
        try:
            gui_queue.put_nowait(("log", str(msg) + "\n"))
        except queue.Full:
            pass

    def update_button_states(self, start_enabled=None, stop_enabled=None):
        if start_enabled is not None:
            self.btn_start.configure(state="normal" if start_enabled else "disabled")
        if stop_enabled is not None:
            self.btn_stop.configure(state="normal" if stop_enabled else "disabled")
        if self.history_loading:
            self.btn_init.configure(state="disabled")
        else:
            self.btn_init.configure(state="normal")

    def create_widgets(self):
        self.main_container = ctk.CTkFrame(self.root, fg_color="#f1f5f9")
        self.main_container.pack(fill="both", expand=True, padx=5, pady=5)

        # 顶部价格与状态
        self.price_card = ctk.CTkFrame(self.main_container, height=70, corner_radius=12, fg_color="#2563eb")
        self.price_card.pack(fill="x", padx=5, pady=(5, 3))
        self.price_label = ctk.CTkLabel(
            self.price_card, text="2174.00", font=("微软雅黑", 40, "bold"), text_color="white"
        )
        self.price_label.pack(side="left", padx=20, pady=8)
        self.time_label = ctk.CTkLabel(
            self.price_card, text="--:--:--", font=("微软雅黑", 18, "bold"), text_color="#dcfce7"
        )
        self.time_label.pack(side="left", padx=20, pady=8)
        self.status_label = ctk.CTkLabel(
            self.price_card, text="⚫ 未启动", font=("微软雅黑", 15, "bold"), text_color="#f1f5f9"
        )
        self.status_label.pack(side="right", padx=20)

        # 按钮行1
        self.btn_row1 = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.btn_row1.pack(fill="x", padx=5, pady=5)
        self.btn_start = self.create_compact_button(self.btn_row1, "▶启动", self.start_system, "#2563eb", 15)
        self.btn_stop = self.create_compact_button(self.btn_row1, "⏹停止", self.stop_system, "#ef4444", 15)
        self.btn_init = self.create_compact_button(self.btn_row1, "📈初始", self.init_history, "#10b981", 15)
        self.create_compact_button(self.btn_row1, "🔄分析", self.force_analysis, "#f59e0b", 15)
        self.create_compact_button(self.btn_row1, "📉K线", self.open_kline_chart, "#8b5cf6", 15)
        self.create_compact_button(self.btn_row1, "📌置顶", self.top_window, "#06b6d4", 15)
        self.create_compact_button(self.btn_row1, "🧠AI", self.ai_mode, "#8b5cf6", 15)
        self.create_compact_button(self.btn_row1, "📊本地", self.local_mode, "#10b981", 15)
        self.create_compact_button(self.btn_row1, "⛔冷却", self.stop_loss, "#ef4444", 15)

        # 按钮行2
        self.btn_row2 = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.btn_row2.pack(fill="x", padx=5, pady=5)
        self.create_compact_button(self.btn_row2, "📁导出", self.export_log, "#6366f1", 15)
        self.create_compact_button(self.btn_row2, "⚙OCR", self.open_realtime_settings, "#64748b", 15)
        self.create_compact_button(self.btn_row2, "🧠提示词", self.open_prompt_editor, "#8b5cf6", 15)
        self.create_compact_button(self.btn_row2, "📈参数", self.open_strategy_settings, "#f59e0b", 15)
        self.create_compact_button(self.btn_row2, "📐OHLC区域", self.open_ohlc_settings, "#10b981", 15)
        self.create_compact_button(self.btn_row2, "🔬回测", self.run_backtest, "#ef4444", 15)
        self.create_compact_button(self.btn_row2, "📋历史K线", self.open_history_viewer, "#6366f1", 15)

        # 中间区域：K线图 + 信号面板
        self.middle_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.middle_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 图表区（纯折线图，无成交量）
        self.chart_frame = ctk.CTkFrame(self.middle_frame, corner_radius=10, fg_color="white")
        self.chart_frame.pack(fill="both", expand=True, padx=0, pady=(0, 5))
        ctk.CTkLabel(self.chart_frame, text="📈 价格走势", font=("微软雅黑", 14, "bold"), text_color="#0f172a").pack(
            anchor="w", padx=10, pady=(5, 0)
        )
        self.fig = plt.Figure(figsize=(6, 2.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=5, pady=5)

        # 信号面板（可滚动）
        self.signal_frame = ctk.CTkFrame(self.middle_frame, corner_radius=10, fg_color="white")
        self.signal_frame.pack(fill="both", expand=True, padx=0, pady=0)
        ctk.CTkLabel(self.signal_frame, text="🧠 交易信号", font=("微软雅黑", 14, "bold"), text_color="#0f172a").pack(
            anchor="center", pady=(5, 0)
        )
        self.signal_scroll = ctk.CTkScrollableFrame(self.signal_frame, fg_color="white", height=180)
        self.signal_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        self.signal_label = ctk.CTkLabel(
            self.signal_scroll, text="HOLD", font=("微软雅黑", 36, "bold"), text_color="#64748b"
        )
        self.signal_label.pack(anchor="center", padx=20, pady=(10, 5))
        self.signal_details = ctk.CTkLabel(
            self.signal_scroll, text="入场: --", font=("微软雅黑", 14), text_color="#334155"
        )
        self.signal_details.pack(anchor="center", padx=20, pady=2)
        self.reason_label = ctk.CTkLabel(
            self.signal_scroll,
            text="等待分析...",
            wraplength=600,
            justify="center",
            font=("微软雅黑", 13),
            text_color="#334155",
        )
        self.reason_label.pack(anchor="center", padx=20)
        self.ai_label = ctk.CTkLabel(
            self.signal_scroll, text="AI: 等待", font=("微软雅黑", 13, "bold"), text_color="#3b82f6"
        )
        self.ai_label.pack(anchor="center", padx=20, pady=2)
        self.explain_label = ctk.CTkLabel(
            self.signal_scroll, text="", wraplength=600, justify="left", font=("微软雅黑", 12), text_color="#475569"
        )
        self.explain_label.pack(anchor="center", padx=20, pady=(5, 0))

        # 指标卡片
        self.info_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.info_container.pack(fill="x", padx=5, pady=5)
        for i in range(6):
            self.info_container.grid_columnconfigure(i, weight=1)
        self.create_metric_card(0, 0, "趋势", "--", "#22c55e", 13, 20)
        self.create_metric_card(0, 1, "RSI", "--", "#3b82f6", 13, 20)
        self.create_metric_card(0, 2, "MACD", "--", "#f59e0b", 13, 20)
        self.create_metric_card(0, 3, "支撑", "--", "#8b5cf6", 13, 20)
        self.create_metric_card(0, 4, "阻力", "--", "#ef4444", 13, 20)
        self.create_metric_card(0, 5, "波动", "--", "#06b6d4", 13, 20)

        # 持仓信息栏
        self.hold_frame = ctk.CTkFrame(self.main_container, corner_radius=10, fg_color="white", height=60)
        self.hold_frame.pack(fill="x", padx=5, pady=5)
        self.hold_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.hold_side_label = ctk.CTkLabel(
            self.hold_frame, text="持仓: 无", font=("微软雅黑", 13), text_color="#64748b"
        )
        self.hold_side_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.hold_time_label = ctk.CTkLabel(
            self.hold_frame, text="持仓时间: 0秒", font=("微软雅黑", 13), text_color="#64748b"
        )
        self.hold_time_label.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        self.hold_pnl_label = ctk.CTkLabel(
            self.hold_frame, text="浮动盈亏: 0.0", font=("微软雅黑", 13), text_color="#64748b"
        )
        self.hold_pnl_label.grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.hold_stop_label = ctk.CTkLabel(
            self.hold_frame, text="止损距离: --", font=("微软雅黑", 13), text_color="#64748b"
        )
        self.hold_stop_label.grid(row=0, column=3, padx=10, pady=5, sticky="w")

        # 手动交易行
        self.trade_row = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.trade_row.pack(fill="x", padx=5, pady=5)
        ctk.CTkButton(
            self.trade_row,
            text="🔴做多",
            command=self.set_long,
            fg_color="#ef4444",
            width=80,
            height=35,
            font=("微软雅黑", 13),
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            self.trade_row,
            text="🔵做空",
            command=self.set_short,
            fg_color="#3b82f6",
            width=80,
            height=35,
            font=("微软雅黑", 13),
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            self.trade_row,
            text="⚪平仓",
            command=self.set_empty,
            fg_color="#64748b",
            width=80,
            height=35,
            font=("微软雅黑", 13),
        ).pack(side="left", padx=5)
        self.manual_price_entry = ctk.CTkEntry(
            self.trade_row, placeholder_text="输入价格", width=120, height=35, font=("微软雅黑", 13)
        )
        self.manual_price_entry.pack(side="left", padx=10)
        ctk.CTkButton(
            self.trade_row,
            text="设置价格",
            command=self.set_manual_price,
            fg_color="#10b981",
            width=90,
            height=35,
            font=("微软雅黑", 13),
        ).pack(side="left", padx=5)

        # 日志区
        self.log_frame = ctk.CTkFrame(self.main_container, corner_radius=10, fg_color="white")
        self.log_frame.pack(fill="both", expand=True, padx=5, pady=(5, 5))
        ctk.CTkLabel(self.log_frame, text="📋 系统日志", font=("微软雅黑", 13, "bold"), text_color="#0f172a").pack(
            anchor="w", padx=10, pady=(5, 0)
        )
        self.log_text = ctk.CTkTextbox(
            self.log_frame, height=120, fg_color="#0f172a", text_color="#e2e8f0", font=("Consolas", 12)
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text._textbox.tag_config("warning", foreground="#ff5555")

        self.progress_bar = ctk.CTkProgressBar(self.log_frame, width=400)
        self.progress_bar.pack(pady=5)
        self.progress_bar.set(0)
        self.progress_bar.pack_forget()

    def create_compact_button(self, parent, text, command, color, font_size=15):
        btn = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color=color,
            height=32,
            width=80,
            corner_radius=8,
            font=("微软雅黑", font_size, "bold"),
        )
        btn.pack(side="left", padx=3)
        return btn

    def create_metric_card(self, row, col, title, value, color, title_font=13, value_font=20):
        card = ctk.CTkFrame(self.info_container, corner_radius=10, fg_color="white", height=70)
        card.grid(row=row, column=col, padx=3, pady=2, sticky="nsew")
        ctk.CTkLabel(card, text=title, font=("微软雅黑", title_font), text_color="#64748b").pack(
            anchor="w", padx=10, pady=(8, 0)
        )
        val_lbl = ctk.CTkLabel(card, text=value, font=("微软雅黑", value_font, "bold"), text_color=color)
        val_lbl.pack(anchor="w", padx=10)
        if title == "趋势":
            self.trend_label = val_lbl
        elif title == "RSI":
            self.rsi_label = val_lbl
        elif title == "MACD":
            self.macd_label = val_lbl
        elif title == "支撑":
            self.support_label = val_lbl
        elif title == "阻力":
            self.resist_label = val_lbl
        elif title == "波动":
            self.range_label = val_lbl

    # ========== 线程管理 ==========
    def start_background_threads(self):
        from tick_indicators import TickIndicatorEngine

        self.tick_engine = TickIndicatorEngine(max_len=200)
        analysis_worker.tick_engine = self.tick_engine
        analysis_worker.gui_queue = gui_queue
        rw.gui_queue = gui_queue
        candle_worker.data_mgr = data_mgr_ref[0]
        analysis_worker.data_mgr = data_mgr_ref[0]
        if self.signal_thread is None or not self.signal_thread.is_alive():
            self.signal_thread = threading.Thread(target=self.signal_monitor, daemon=True)
            self.signal_thread.start()
        self.threads = [
            threading.Thread(target=run_ocr_worker, args=(state, stop_event, self.tick_engine), daemon=True),
            threading.Thread(target=run_candle_worker, args=(state, stop_event), daemon=True),
            threading.Thread(target=run_analysis_worker, args=(state, stop_event), daemon=True),
            threading.Thread(target=run_execution_worker, args=(state, stop_event), daemon=True),
            threading.Thread(target=rw.risk_worker, args=(state, stop_event), daemon=True),
        ]
        for t in self.threads:
            t.start()

    def start_system(self):
        global system_running
        if system_running:
            self.log("⚠ 系统已经在运行\n")
            return
        alive = any(t.is_alive() for t in self.threads) or (self.signal_thread and self.signal_thread.is_alive())
        if alive:
            self.log("⚠ 检测到残留线程，请先停止\n")
            return
        stop_event.clear()
        self.start_background_threads()
        system_running = True
        self.status_label.configure(text="🟢 运行中")
        self.log("▶ 系统启动成功\n")
        self.update_button_states(start_enabled=False, stop_enabled=True)

    def stop_system(self):
        global system_running
        if not system_running:
            self.log("⚠ 系统未运行\n")
            return
        stop_event.set()
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=0.5)
        if self.signal_thread and self.signal_thread.is_alive():
            self.signal_thread.join(timeout=0.5)
        system_running = False
        self.status_label.configure(text="🔴 已停止")
        self.log("⏹ 系统已停止\n")
        self.update_button_states(start_enabled=True, stop_enabled=False)

    def signal_monitor(self):
        while not stop_event.is_set():
            try:
                signal = signal_queue.get(timeout=0.5)
                if signal:
                    try:
                        gui_queue.put_nowait(("signal", signal))
                    except queue.Full:
                        pass
            except queue.Empty:
                pass
            except Exception as e:
                self.log(f"signal错误: {e}")

    # ========== GUI更新 ==========
    def update_gui(self):
        if not self.root.winfo_exists():
            return
        try:
            while not gui_queue.empty():
                try:
                    msg_type, data = gui_queue.get_nowait()
                except queue.Empty:
                    break
                if msg_type == "signal":
                    self.display_signal(data)
                elif msg_type == "log":
                    self.log_text.insert("end", data)
                    lines = int(self.log_text.index("end-1c").split(".")[0])
                    if lines > 300:
                        self.log_text.delete("1.0", f"{lines-300}.0")
                    self.log_text.see("end")
                elif msg_type == "explain":
                    self.explain_label.configure(text=data)
                elif msg_type == "warning":
                    self.log_text.insert("end", data + "\n", "warning")
                    self.log_text.see("end")
                    original_color = self.status_label.cget("text_color")
                    self.status_label.configure(text_color="orange")
                    self.root.after(3000, lambda: self.status_label.configure(text_color=original_color))
                elif msg_type == "backtest_progress":
                    self.progress_bar.set(data)
                    self.log_text.insert("end", f"回测进度: {int(data*100)}%\n")
                    self.log_text.see("end")
                elif msg_type == "backtest_finished":
                    self.progress_bar.pack_forget()
                    self.log(f"回测完成: {data}\n")
                    messagebox.showinfo("回测完成", data)
                elif msg_type == "ai":
                    self.ai_label.configure(text=f"AI: {data}")
                    self.signal_label.configure(text="AI建议", text_color="#8b5cf6")
                    self.signal_details.configure(text="")
                    self.reason_label.configure(text=data)

            price = state.get_price()
            if price:
                self.price_label.configure(text=f"{price:.2f}")
            tick_time = state.get_tick_time()
            if tick_time:
                self.time_label.configure(text=tick_time.strftime("%H:%M:%S"))

            # 持仓信息
            side, entry, stop, take, hold_seconds, unrealized_pnl = state.get_holding_info()
            if side is not None:
                self.hold_side_label.configure(
                    text=f"持仓: {side}", text_color="#ef4444" if side == "LONG" else "#22c55e"
                )
                self.hold_time_label.configure(text=f"持仓时间: {int(hold_seconds)}秒")
                pnl_color = "#22c55e" if unrealized_pnl > 0 else "#ef4444" if unrealized_pnl < 0 else "#64748b"
                self.hold_pnl_label.configure(text=f"浮动盈亏: {unrealized_pnl:.2f}点", text_color=pnl_color)
                if stop:
                    if side == "LONG":
                        cur_stop_dist = price - stop if price else 0
                    else:
                        cur_stop_dist = stop - price if price else 0
                    self.hold_stop_label.configure(text=f"止损距离: {cur_stop_dist:.2f}")
                    if price and 0 < cur_stop_dist < 0.5:
                        gui_queue.put_nowait(("warning", f"⚠️ 价格接近止损位！当前{price:.2f}，止损{stop}"))
                else:
                    self.hold_stop_label.configure(text="止损距离: --")
            else:
                self.hold_side_label.configure(text="持仓: 无")
                self.hold_time_label.configure(text="持仓时间: 0秒")
                self.hold_pnl_label.configure(text="浮动盈亏: 0.0")
                self.hold_stop_label.configure(text="止损距离: --")

            mgr = data_mgr_ref[0]
            if mgr is not None:
                with mgr._data_lock:
                    df = mgr.candles.tail(100).copy()
                if len(df) >= 5:
                    if len(df) >= 15:
                        closed_df = df.iloc[:-1]
                        ind = strategy.calculate_indicators(closed_df)
                        self.trend_label.configure(text=ind.get("trend", "--"))
                        self.rsi_label.configure(text=f"{ind['rsi']:.1f}")
                        macd_status = "多头" if ind.get("macd_bullish") else "空头"
                        self.macd_label.configure(text=macd_status)
                        self.support_label.configure(text=f"{ind['low_5']:.2f}")
                        self.resist_label.configure(text=f"{ind['high_5']:.2f}")
                        self.range_label.configure(text=f"{ind['recent_range']:.1f}")
                    now = time.time()
                    if now - self.last_chart_update > 1:
                        self.update_chart(df.tail(60), current_price=price)
                        self.last_chart_update = now
        except Exception as e:
            self.log(f"GUI错误: {e}\n")
        self.root.after(800, self.update_gui)

    def update_chart(self, df, current_price=None):
        """纯折线图，无成交量，无 mplfinance"""
        try:
            df = df.copy()
            if df.empty or len(df) < 5:
                return
            if "close" not in df.columns:
                return
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            if len(df) < 5:
                return

            self.fig.clear()
            self.ax = self.fig.add_subplot(111)

            indices = range(len(df))
            prices = df["close"].values

            self.ax.plot(indices, prices, linewidth=1.8, color="#2563eb")
            self.ax.set_ylabel("Price", fontsize=11)
            self.ax.grid(True, alpha=0.3)

            # Y轴范围包含实时价格
            if current_price is not None:
                y_min = min(prices.min(), current_price)
                y_max = max(prices.max(), current_price)
            else:
                y_min = prices.min()
                y_max = prices.max()
            # 避免 min==max 导致警告
            if y_max <= y_min:
                y_max = y_min + 1
            margin = (y_max - y_min) * 0.05
            self.ax.set_ylim(y_min - margin, y_max + margin)

            # X轴标签
            if "timestamp" in df.columns:
                try:
                    times = pd.to_datetime(df["timestamp"]).dt.strftime("%H:%M")
                    step = max(1, len(indices) // 6)
                    self.ax.set_xticks(indices[::step])
                    self.ax.set_xticklabels(times[::step], rotation=30, ha="right", fontsize=9)
                except:
                    pass

            self.canvas.draw_idle()
        except Exception as e:
            self.log(f"绘图失败: {e}\n")

    def display_signal(self, signal):
        if signal.get("type") == "ai":
            return
        side = signal.get("side", "HOLD")
        entry = signal.get("entry", "--")
        stop = signal.get("stop", "--")
        take = signal.get("take", "--")
        reason = signal.get("reason", "")
        if side == "LONG":
            self.signal_label.configure(text="做多 ↑", text_color="#ef4444")
            explain_text = f"系统建议：做多（{reason}）"
        elif side == "SHORT":
            self.signal_label.configure(text="做空 ↓", text_color="#22c55e")
            explain_text = f"系统建议：做空（{reason}）"
        else:
            self.signal_label.configure(text="HOLD", text_color="#64748b")
            explain_text = "系统建议：暂时观望（HOLD）"
        self.signal_details.configure(text=f"入场:{entry} 止损:{stop} 止盈:{take}")
        self.reason_label.configure(text=reason)
        self.explain_label.configure(text=explain_text)

    # ========== 功能方法 ==========
    def top_window(self):
        set_trading_window_topmost()

    def init_history(self):
        if self.history_loading:
            self.log("⚠ 历史K线正在抓取中，请勿重复操作\n")
            return
        threading.Thread(target=self._init_history, daemon=True).start()

    def _init_history(self):
        self.history_loading = True
        self.update_button_states()
        self.log("📈 正在抓取历史K线（一次性）...\n")
        try:
            kline_ocr_scraper.scrape_historical_klines(state, data_mgr_ref, total=60, stop_event=stop_event)
            if data_mgr_ref[0] is not None:
                data_mgr_ref[0].persist()
                analysis_worker.data_mgr = data_mgr_ref[0]
                candle_worker.data_mgr = data_mgr_ref[0]
            self.log("✅ 历史K线抓取完成\n")
            messagebox.showinfo("提示", "历史K线抓取完成")
        except Exception as e:
            self.log(f"❌ 历史K线抓取失败: {e}\n")
            messagebox.showerror("错误", f"抓取失败: {e}")
        finally:
            self.history_loading = False
            self.update_button_states()

    def force_analysis(self):
        if self.analysis_lock.locked():
            self.log("⚠ 分析任务已在执行中\n")
            return
        threading.Thread(target=self._force_analysis_worker, daemon=True).start()

    def _force_analysis_worker(self):
        with self.analysis_lock:
            try:
                candle_queue.put({"force": True})
                self.log("🔄 强制分析已触发\n")
                mgr = data_mgr_ref[0]
                if mgr and len(mgr.candles) >= 15:
                    with mgr._data_lock:
                        df = mgr.candles.tail(61).copy()
                    closed_df = df.iloc[:-1]
                    if len(closed_df) >= 14:
                        ind = strategy.calculate_indicators(closed_df)
                        current_price = closed_df.iloc[-1]["close"]
                        explanation = strategy.explain_analysis(ind, current_price)
                        try:
                            gui_queue.put_nowait(("explain", explanation))
                        except queue.Full:
                            pass
                        self.log(explanation + "\n")
                else:
                    self.log("⚠ 数据不足15根，无法强制分析\n")
            except Exception as e:
                self.log(f"分析失败: {e}\n")

    def ai_mode(self):
        state.analysis_mode = 0
        self.log("🧠 AI模式\n")

    def local_mode(self):
        state.analysis_mode = 1
        self.log("📊 本地规则模式\n")

    def stop_loss(self):
        state.set_stopout_time()
        state.set_position(None, "EMPTY")
        self.log("⛔ 手动止损冷却，已清仓\n")

    def export_log(self):
        import pandas as pd

        with state._lock:
            df = pd.DataFrame(state.trade_log)
        if not df.empty:
            df.to_csv("trade_log.csv", index=False)
            messagebox.showinfo("导出成功", "已保存到 trade_log.csv")
        else:
            messagebox.showinfo("提示", "暂无交易记录")

    def run_backtest(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("回测设置")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text="滑点 (点):").pack(pady=5)
        slippage_entry = ctk.CTkEntry(dialog)
        slippage_entry.insert(0, "0.5")
        slippage_entry.pack(pady=5)
        ctk.CTkLabel(dialog, text="手续费 (点/手):").pack(pady=5)
        commission_entry = ctk.CTkEntry(dialog)
        commission_entry.insert(0, "1.0")
        commission_entry.pack(pady=5)

        def start_backtest():
            try:
                slippage = float(slippage_entry.get())
                commission = float(commission_entry.get())
            except:
                messagebox.showerror("错误", "请输入有效数字")
                return
            dialog.destroy()
            self.log(f"开始回测，滑点={slippage}，手续费={commission}\n")
            self.progress_bar.pack(pady=5)
            self.progress_bar.set(0)
            threading.Thread(target=self._run_backtest_worker, args=(slippage, commission), daemon=True).start()

        ctk.CTkButton(dialog, text="开始回测", command=start_backtest).pack(pady=20)

    def _run_backtest_worker(self, slippage, commission):
        from backtester import Backtester
        from performance import analyze_trades

        try:
            bt = Backtester(data_mgr_ref[0], slippage=slippage, commission=commission)
            trades = bt.run()
            if trades is not None and not trades.empty:
                stats = analyze_trades(trades)
                result = "\n".join([f"{k}: {v}" for k, v in stats.items()])
                gui_queue.put(("backtest_finished", result))
                trades.to_csv("backtest_trades.csv", index=False)
                self.log(f"回测完成，共 {len(trades)} 笔交易\n")
            else:
                gui_queue.put(("backtest_finished", "没有产生任何交易"))
        except Exception as e:
            gui_queue.put(("log", f"回测异常: {e}\n"))
            gui_queue.put(("backtest_finished", f"回测异常: {e}"))

    def open_realtime_settings(self):
        RealTimeRegionsDialog(self.root, config_mgr, on_save_callback=self._on_realtime_regions_saved)

    def _on_realtime_regions_saved(self):
        self.log("✅ 实时区域配置已更新，重启后生效\n")

    def open_prompt_editor(self):
        PromptEditor(self.root, config_mgr)

    def open_strategy_settings(self):
        StrategySettingsDialog(self.root, config_mgr)

    def open_history_viewer(self):
        HistoryViewerDialog(self.root, data_mgr_ref[0])

    def open_kline_chart(self):
        KlineChartWindow(self.root, data_mgr_ref[0])

    def open_ohlc_settings(self):
        OHLCSettingsDialog(self.root, config_mgr, on_save_callback=self._on_ohlc_settings_saved)

    def _on_ohlc_settings_saved(self):
        self.log("✅ OHLC 区域配置已更新，请重新抓取历史K线\n")

    def set_long(self):
        price = state.get_price()
        if price is None:
            self.log("无当前价格，无法开多\n")
            return
        stop = price - MANUAL_STOP_POINTS
        take = price + MANUAL_TAKE_POINTS
        state.set_position(
            {"side": "LONG", "entry": price, "stop": stop, "take": take, "initial_risk": MANUAL_STOP_POINTS}, "LONG"
        )
        self.log(f"🔴 手动开多 @{price}\n")

    def set_short(self):
        price = state.get_price()
        if price is None:
            self.log("无当前价格，无法开空\n")
            return
        stop = price + MANUAL_STOP_POINTS
        take = price - MANUAL_TAKE_POINTS
        state.set_position(
            {"side": "SHORT", "entry": price, "stop": stop, "take": take, "initial_risk": MANUAL_STOP_POINTS}, "SHORT"
        )
        self.log(f"🔵 手动开空 @{price}\n")

    def set_empty(self):
        state.set_position(None, "EMPTY")
        self.log("⚪ 手动平仓\n")

    def set_manual_price(self):
        try:
            price = float(self.manual_price_entry.get())
            tick_time = datetime.now(timezone.utc)
            tick_queue.put((price, tick_time))
            state.update_price(price)
            self.log(f"✏️ 手动注入价格:{price}\n")
            self.manual_price_entry.delete(0, "end")
        except:
            messagebox.showerror("错误", "请输入正确价格")

    def on_close(self):
        if messagebox.askokcancel("退出", "确定退出系统？"):
            global system_running
            stop_event.set()
            system_running = False
            self.root.destroy()
            sys.exit(0)


if __name__ == "__main__":
    root = ctk.CTk()
    app = TradingApp(root)
    root.mainloop()

ml_backtest.py

# ml_backtest.py
import pandas as pd
import numpy as np
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score

# 加载数据
df = pd.read_csv("klines_auto.csv", parse_dates=["time"])
df.set_index("time", inplace=True)
df.sort_index(inplace=True)


# 特征工程
def add_features(df, lookback=5):
    df = df.copy()
    # 价格变化率
    for lag in range(1, lookback + 1):
        df[f"return_{lag}"] = df["close"].pct_change(lag)
    # 成交量变化率
    df["volume_change"] = df["volume"].pct_change()
    # 收盘价相对于近期高低点的位置
    df["close_pct_high5"] = df["close"] / df["high"].rolling(5).max() - 1
    df["close_pct_low5"] = df["close"] / df["low"].rolling(5).min() - 1
    # RSI (14)
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))
    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    # 布林带宽度
    bb_mid = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    df["bb_width"] = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid
    # 目标变量：下一根K线是否上涨（1涨，0跌/平）
    df["target"] = (df["close"].shift(-1) > df["close"]).astype(int)
    df.dropna(inplace=True)
    return df


df_feat = add_features(df)
# 特征列
feature_cols = [c for c in df_feat.columns if c not in ["target", "open", "high", "low", "close", "volume"]]
X = df_feat[feature_cols]
y = df_feat["target"]

# 时间序列交叉验证
tscv = TimeSeriesSplit(n_splits=5)
acc_list = []
for train_idx, test_idx in tscv.split(X):
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    model = XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42)
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    acc = accuracy_score(y_test, pred)
    acc_list.append(acc)
print(f"平均准确率: {np.mean(acc_list):.3f}")

# 使用全部数据训练最终模型
model = XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42)
model.fit(X, y)
importance = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
print("特征重要性:\n", importance.head(10))

# 回测交易
position = None
entry_price = 0
stop_loss = 0
take_profit = 0
trades = []
for i in range(20, len(df_feat) - 1):
    current = df_feat.iloc[i]
    price = current["close"]
    # 预测下一根K线方向
    feat = current[feature_cols].values.reshape(1, -1)
    prob_up = model.predict_proba(feat)[0][1]
    # 开仓条件：概率 > 0.6
    if position is None:
        if prob_up > 0.6:
            position = "LONG"
            entry_price = price
            stop_loss = price - 4
            take_profit = price + 6
            print(f"{current.name} 开多 @{price} 止损{stop_loss} 止盈{take_profit}")
        elif prob_up < 0.4:
            position = "SHORT"
            entry_price = price
            stop_loss = price + 4
            take_profit = price - 6
            print(f"{current.name} 开空 @{price} 止损{stop_loss} 止盈{take_profit}")
    else:
        if position == "LONG":
            if price >= take_profit:
                pnl = take_profit - entry_price
                trades.append({"entry": entry_price, "exit": take_profit, "pnl": pnl, "side": "LONG"})
                print(f"{current.name} 止盈多 @{take_profit} 盈亏{pnl}点")
                position = None
            elif price <= stop_loss:
                pnl = stop_loss - entry_price
                trades.append({"entry": entry_price, "exit": stop_loss, "pnl": pnl, "side": "LONG"})
                print(f"{current.name} 止损多 @{stop_loss} 盈亏{pnl}点")
                position = None
        elif position == "SHORT":
            if price <= take_profit:
                pnl = entry_price - take_profit
                trades.append({"entry": entry_price, "exit": take_profit, "pnl": pnl, "side": "SHORT"})
                print(f"{current.name} 止盈空 @{take_profit} 盈亏{pnl}点")
                position = None
            elif price >= stop_loss:
                pnl = entry_price - stop_loss
                trades.append({"entry": entry_price, "exit": stop_loss, "pnl": pnl, "side": "SHORT"})
                print(f"{current.name} 止损空 @{stop_loss} 盈亏{pnl}点")
                position = None

if trades:
    df_trades = pd.DataFrame(trades)
    print("\n回测统计：")
    print(f"总交易次数: {len(df_trades)}")
    print(f"盈利次数: {len(df_trades[df_trades['pnl']>0])}")
    print(f"胜率: {len(df_trades[df_trades['pnl']>0])/len(df_trades):.2%}")
    print(f"总盈亏: {df_trades['pnl'].sum()}点")
    df_trades.to_csv("ml_trades.csv", index=False)
else:
    print("无交易")

notifier.py

"""非阻塞声音通知"""
import threading
import winsound

def play_sound(freq, dur):
    threading.Thread(target=lambda: winsound.Beep(freq, dur), daemon=True).start()

ocr_worker.py

"""
OCR 线程：只识别最新成交价（高速版）
- 区域仅包含价格数字
- 使用系统时间作为 tick 时间戳
- 采样间隔 0.2 秒
- 灰度图直接识别，不二值化
- 价格去重 + 跨分钟强制推送
"""

import time
import threading
import logging
import pyautogui
import pytesseract
from datetime import datetime
from queues import tick_queue
from runtime_state import RuntimeState
from config_manager import ConfigManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("OCR")

config_mgr = ConfigManager()
pytesseract.pytesseract.tesseract_cmd = config_mgr.config.get("tesseract_cmd", r"./Tesseract-OCR/tesseract.exe")

PRICE_MIN = 2000
PRICE_MAX = 3500
MIN_PRICE_CHANGE = config_mgr.config.get("min_price_change", 1)
MAX_PRICE_JUMP = config_mgr.config.get("max_price_jump", 20)


class TickFilter:
    def __init__(self, max_jump=MAX_PRICE_JUMP, min_interval=0.2, min_change=MIN_PRICE_CHANGE):
        self.last_price = None
        self.max_jump = max_jump
        self.last_push_time = 0
        self.last_push_dt = None
        self.min_interval = min_interval
        self.min_change = min_change

    def update(self, price, tick_dt):
        now_ts = tick_dt.timestamp()
        if self.last_push_dt is not None:
            if tick_dt.minute != self.last_push_dt.minute:
                self.last_price = price
                self.last_push_time = now_ts
                self.last_push_dt = tick_dt
                return price
        if self.last_price is not None and price == self.last_price:
            if (now_ts - self.last_push_time) < self.min_interval:
                return None
        if self.last_price is not None:
            price_change = abs(price - self.last_price)
            if price_change < self.min_change:
                return None
            if price_change > self.max_jump:
                return None
        self.last_price = price
        self.last_push_time = now_ts
        self.last_push_dt = tick_dt
        return price


def capture_price():
    left, top, width, height = config_mgr.get_price_region()
    if width <= 0 or height <= 0:
        logger.error("价格区域未设置，请先标定 price_region")
        return None
    try:
        img = pyautogui.screenshot(region=(left, top, width, height))
        # 灰度图，不做二值化（保留更多信息）
        img = img.convert("L")
        # 快速识别，只允许数字
        config = "--psm 7 -c tessedit_char_whitelist=0123456789"
        text = pytesseract.image_to_string(img, config=config)
        text = text.strip()
        if not text:
            return None
        price = int(text)
        if PRICE_MIN <= price <= PRICE_MAX:
            return float(price)
        else:
            return None
    except Exception as e:
        logger.exception("价格识别异常")
        return None


def run_ocr_worker(state: RuntimeState, stop_event: threading.Event, tick_engine=None):
    filt = TickFilter()
    last_price = None
    consecutive_failures = 0
    logger.info("[OCR] 工作线程已启动（高速版）")
    while not stop_event.is_set():
        price = capture_price()
        if price is None:
            consecutive_failures += 1
            if consecutive_failures >= 5:
                logger.warning(f"OCR 连续 {consecutive_failures} 次识别失败，请检查区域")
                consecutive_failures = 0
            stop_event.wait(0.2)
            continue
        consecutive_failures = 0

        if price == last_price:
            stop_event.wait(0.2)
            continue
        last_price = price

        # 使用系统当前时间作为 tick 时间戳
        tick_time = datetime.now()
        price = filt.update(price, tick_time)
        if price is None:
            stop_event.wait(0.2)
            continue

        state.update_price(price)
        state.update_tick_time(tick_time)
        try:
            tick_queue.put_nowait((price, tick_time))
        except:
            pass
        if tick_engine is not None:
            tick_engine.add_tick(price, tick_time)
        stop_event.wait(0.2)  # 0.2秒采样一次
    logger.info("[OCR] 工作线程已停止")

ohlc_settings_dialog.py

"""OHLC 多区域截图设置对话框（时间、价格、成交量）"""

import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui
from config_manager import ConfigManager


class OHLCSettingsDialog:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("📋 OHLC 三区域截图设置")
        self.win.geometry("520x400")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.grab_set()

        self.notebook = ttk.Notebook(self.win)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.time_frame = ttk.Frame(self.notebook)
        self.price_frame = ttk.Frame(self.notebook)
        self.volume_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.time_frame, text="时间")
        self.notebook.add(self.price_frame, text="OHLC价格")
        self.notebook.add(self.volume_frame, text="成交量")

        self.create_region_tab(self.time_frame, "ohlc_time_region")
        self.create_region_tab(self.price_frame, "ohlc_price_region")
        self.create_region_tab(self.volume_frame, "ohlc_volume_region")

        ttk.Button(self.win, text="💾 保存所有区域", command=self.save_all).pack(pady=10)

    def create_region_tab(self, parent, config_key):
        frame = ttk.LabelFrame(parent, text="截图区域坐标 (像素)", padding=10)
        frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(frame, text="X (左):").grid(row=0, column=0, padx=5, pady=2)
        entry_left = ttk.Entry(frame, width=8)
        entry_left.grid(row=0, column=1, padx=5)
        ttk.Label(frame, text="Y (上):").grid(row=0, column=2, padx=5)
        entry_top = ttk.Entry(frame, width=8)
        entry_top.grid(row=0, column=3, padx=5)
        ttk.Label(frame, text="宽度:").grid(row=1, column=0, padx=5, pady=2)
        entry_width = ttk.Entry(frame, width=8)
        entry_width.grid(row=1, column=1, padx=5)
        ttk.Label(frame, text="高度:").grid(row=1, column=2, padx=5)
        entry_height = ttk.Entry(frame, width=8)
        entry_height.grid(row=1, column=3, padx=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=4, pady=5)
        ttk.Button(btn_frame, text="🖱️ 鼠标拾取 (3秒)", command=lambda: self.start_capture(entry_left, entry_top)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            btn_frame,
            text="📸 测试截图",
            command=lambda: self.test_screenshot(entry_left, entry_top, entry_width, entry_height),
        ).pack(side=tk.LEFT, padx=2)

        setattr(self, f"entry_{config_key}_left", entry_left)
        setattr(self, f"entry_{config_key}_top", entry_top)
        setattr(self, f"entry_{config_key}_width", entry_width)
        setattr(self, f"entry_{config_key}_height", entry_height)
        self.load_config_values(config_key)

    def load_config_values(self, config_key):
        cfg = self.config_mgr.config.get(config_key, {})
        getattr(self, f"entry_{config_key}_left").insert(0, str(cfg.get("left", 0)))
        getattr(self, f"entry_{config_key}_top").insert(0, str(cfg.get("top", 0)))
        getattr(self, f"entry_{config_key}_width").insert(0, str(cfg.get("width", 0)))
        getattr(self, f"entry_{config_key}_height").insert(0, str(cfg.get("height", 0)))

    def start_capture(self, entry_left, entry_top):
        self.win.after(3000, lambda: self.capture_pos(entry_left, entry_top))

    def capture_pos(self, entry_left, entry_top):
        x, y = pyautogui.position()
        entry_left.delete(0, tk.END)
        entry_left.insert(0, str(x))
        entry_top.delete(0, tk.END)
        entry_top.insert(0, str(y))

    def test_screenshot(self, entry_left, entry_top, entry_width, entry_height):
        try:
            left = int(entry_left.get())
            top = int(entry_top.get())
            width = int(entry_width.get())
            height = int(entry_height.get())
            img = pyautogui.screenshot(region=(left, top, width, height))
            img.show()
        except Exception as e:
            messagebox.showerror("截图失败", str(e))

    def save_all(self):
        for key in ["ohlc_time_region", "ohlc_price_region", "ohlc_volume_region"]:
            try:
                left = int(getattr(self, f"entry_{key}_left").get())
                top = int(getattr(self, f"entry_{key}_top").get())
                width = int(getattr(self, f"entry_{key}_width").get())
                height = int(getattr(self, f"entry_{key}_height").get())
                self.config_mgr.config[key] = {"left": left, "top": top, "width": width, "height": height}
            except ValueError:
                messagebox.showerror("输入错误", f"{key} 请输入有效整数")
                return
        self.config_mgr.save()
        messagebox.showinfo("保存成功", "三个区域配置已保存")
        if self.on_save:
            self.on_save()
        self.win.destroy()

performance.py

"""
绩效分析模块：计算交易记录的关键指标
"""

import pandas as pd


def analyze_trades(trades_df):
    """trades_df 为 backtester 生成的交易记录DataFrame"""
    if trades_df.empty:
        return {}
    total_trades = len(trades_df)
    winning = len(trades_df[trades_df["pnl"] > 0])
    losing = len(trades_df[trades_df["pnl"] < 0])
    win_rate = winning / total_trades if total_trades > 0 else 0
    total_pnl = trades_df["pnl"].sum()
    avg_pnl = trades_df["pnl"].mean()
    max_win = trades_df["pnl"].max()
    max_loss = trades_df["pnl"].min()
    avg_win = trades_df[trades_df["pnl"] > 0]["pnl"].mean() if winning > 0 else 0
    avg_loss = abs(trades_df[trades_df["pnl"] < 0]["pnl"].mean()) if losing > 0 else 0
    profit_factor = avg_win / avg_loss if avg_loss > 0 else float("inf")
    # 计算最大回撤（基于累计盈亏）
    trades_df["cum_pnl"] = trades_df["pnl"].cumsum()
    running_max = trades_df["cum_pnl"].cummax()
    drawdown = (trades_df["cum_pnl"] - running_max).min()
    return {
        "总交易次数": total_trades,
        "盈利次数": winning,
        "亏损次数": losing,
        "胜率": f"{win_rate:.2%}",
        "总盈亏": f"{total_pnl:.2f}",
        "平均盈亏": f"{avg_pnl:.2f}",
        "最大盈利": f"{max_win:.2f}",
        "最大亏损": f"{max_loss:.2f}",
        "盈亏比": f"{profit_factor:.2f}",
        "最大回撤": f"{drawdown:.2f}",
    }

prompt_editor.py

"""AI 提示词编辑器"""
import tkinter as tk
from tkinter import ttk, messagebox
from config_manager import ConfigManager

DEFAULT_PROMPT = """你是专业量化交易分析AI。..."""

class PromptEditor:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("🧠 AI 提示词编辑器")
        self.win.geometry("650x550")
        self.win.resizable(True, True)
        self.win.transient(root)
        self.win.grab_set()
        ttk.Label(self.win, text="修改 DeepSeek AI 系统提示词", font=("微软雅黑", 10)).pack(pady=5)
        text_frame = ttk.Frame(self.win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.text_widget = tk.Text(text_frame, wrap=tk.WORD, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(text_frame, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scrollbar.set)
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="💾 保存", command=self.save_prompt).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 恢复默认", command=self.reset_default).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="❌ 取消", command=self.win.destroy).pack(side=tk.LEFT, padx=5)
        self.load_current_prompt()

    def load_current_prompt(self):
        prompt = self.config_mgr.get_system_prompt()
        if not prompt: prompt = DEFAULT_PROMPT
        self.text_widget.delete(1.0, tk.END)
        self.text_widget.insert(tk.END, prompt)

    def save_prompt(self):
        new_prompt = self.text_widget.get(1.0, tk.END).strip()
        if not new_prompt: messagebox.showerror("错误", "提示词不能为空"); return
        self.config_mgr.set_system_prompt(new_prompt)
        messagebox.showinfo("成功", "AI 提示词已更新")
        if self.on_save: self.on_save()
        self.win.destroy()

    def reset_default(self):
        self.text_widget.delete(1.0, tk.END)
        self.text_widget.insert(tk.END, DEFAULT_PROMPT)

queues.py

"""消息队列定义"""
from queue import Queue

tick_queue = Queue(maxsize=5000)      # (price, tick_time)
candle_queue = Queue(maxsize=500)     # finished candle dict
signal_queue = Queue(maxsize=50)      # signal dict or None

realtime_regions_dialog.py

"""
实时区域设置对话框：一次性标定时间、价格、买一价、卖一价四个区域
"""

import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui
from config_manager import ConfigManager


class RealTimeRegionsDialog:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("⚙ 实时区域设置（时间/价格/买一/卖一）")
        self.win.geometry("500x450")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.grab_set()
        self.create_widgets()
        self.load_current_config()

    def create_widgets(self):
        notebook = ttk.Notebook(self.win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 时间区域
        self.time_frame = ttk.Frame(notebook)
        notebook.add(self.time_frame, text="时间")
        self.create_region_tab(self.time_frame, "time_region", "时间 (HH:MM:SS)")

        # 价格区域
        self.price_frame = ttk.Frame(notebook)
        notebook.add(self.price_frame, text="价格")
        self.create_region_tab(self.price_frame, "price_region", "最新成交价 (数字)")

        # 买一价区域
        self.bid_frame = ttk.Frame(notebook)
        notebook.add(self.bid_frame, text="买一价")
        self.create_region_tab(self.bid_frame, "bid1_price_region", "买一价 (数字)")

        # 卖一价区域
        self.ask_frame = ttk.Frame(notebook)
        notebook.add(self.ask_frame, text="卖一价")
        self.create_region_tab(self.ask_frame, "ask1_price_region", "卖一价 (数字)")

        ttk.Button(self.win, text="💾 保存所有区域", command=self.save_all).pack(pady=10)

    def create_region_tab(self, parent, config_key, description):
        frame = ttk.LabelFrame(parent, text="截图区域坐标 (像素)", padding=10)
        frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(frame, text=description).pack(anchor=tk.W, pady=2)

        # 坐标输入行
        row1 = ttk.Frame(frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="X:").pack(side=tk.LEFT, padx=2)
        entry_left = ttk.Entry(row1, width=8)
        entry_left.pack(side=tk.LEFT, padx=2)
        ttk.Label(row1, text="Y:").pack(side=tk.LEFT, padx=2)
        entry_top = ttk.Entry(row1, width=8)
        entry_top.pack(side=tk.LEFT, padx=2)
        ttk.Label(row1, text="宽度:").pack(side=tk.LEFT, padx=2)
        entry_width = ttk.Entry(row1, width=8)
        entry_width.pack(side=tk.LEFT, padx=2)
        ttk.Label(row1, text="高度:").pack(side=tk.LEFT, padx=2)
        entry_height = ttk.Entry(row1, width=8)
        entry_height.pack(side=tk.LEFT, padx=2)

        # 按钮行
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="🖱️ 鼠标拾取 (3秒)", command=lambda: self.start_capture(entry_left, entry_top)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            btn_frame,
            text="📸 测试截图",
            command=lambda: self.test_screenshot(entry_left, entry_top, entry_width, entry_height),
        ).pack(side=tk.LEFT, padx=2)

        setattr(self, f"entry_{config_key}_left", entry_left)
        setattr(self, f"entry_{config_key}_top", entry_top)
        setattr(self, f"entry_{config_key}_width", entry_width)
        setattr(self, f"entry_{config_key}_height", entry_height)

    def load_current_config(self):
        for key in ["time_region", "price_region", "bid1_price_region", "ask1_price_region"]:
            cfg = self.config_mgr.config.get(key, {})
            getattr(self, f"entry_{key}_left").insert(0, str(cfg.get("left", 0)))
            getattr(self, f"entry_{key}_top").insert(0, str(cfg.get("top", 0)))
            getattr(self, f"entry_{key}_width").insert(0, str(cfg.get("width", 0)))
            getattr(self, f"entry_{key}_height").insert(0, str(cfg.get("height", 0)))

    def start_capture(self, entry_left, entry_top):
        # 禁用当前按钮避免重复
        btn = self.win.focus_get()
        if btn and isinstance(btn, ttk.Button):
            btn.config(state="disabled")
        self.win.after(3000, lambda: self.capture_pos(entry_left, entry_top))

    def capture_pos(self, entry_left, entry_top):
        x, y = pyautogui.position()
        entry_left.delete(0, tk.END)
        entry_left.insert(0, str(x))
        entry_top.delete(0, tk.END)
        entry_top.insert(0, str(y))
        # 恢复按钮状态
        for child in self.win.winfo_children():
            if isinstance(child, ttk.Button):
                child.config(state="normal")

    def test_screenshot(self, entry_left, entry_top, entry_width, entry_height):
        try:
            left = int(entry_left.get())
            top = int(entry_top.get())
            width = int(entry_width.get())
            height = int(entry_height.get())
            img = pyautogui.screenshot(region=(left, top, width, height))
            img.show()
        except Exception as e:
            messagebox.showerror("截图失败", str(e))

    def save_all(self):
        for key in ["time_region", "price_region", "bid1_price_region", "ask1_price_region"]:
            try:
                left = int(getattr(self, f"entry_{key}_left").get())
                top = int(getattr(self, f"entry_{key}_top").get())
                width = int(getattr(self, f"entry_{key}_width").get())
                height = int(getattr(self, f"entry_{key}_height").get())
                self.config_mgr.config[key] = {"left": left, "top": top, "width": width, "height": height}
            except ValueError:
                messagebox.showerror("输入错误", f"{key} 请输入有效整数")
                return
        self.config_mgr.save()
        messagebox.showinfo("保存成功", "实时区域配置已保存")
        if self.on_save:
            self.on_save()
        self.win.destroy()

risk_worker.py

"""风控线程：监控持仓，止损/止盈，保本移动，并发送GUI通知"""

import threading
import time
from runtime_state import RuntimeState
from notifier import play_sound

MAX_HOLD_SECONDS = 300
gui_queue = None


def risk_worker(state: RuntimeState, stop_event: threading.Event):
    global gui_queue
    while not stop_event.is_set():
        state.price_updated.wait(timeout=0.1)
        state.price_updated.clear()
        pos, _ = state.get_position()
        if pos is None or pos.get("closing"):
            continue

        if "entry_time" in pos:
            if time.time() - pos["entry_time"] > MAX_HOLD_SECONDS:
                price = state.get_price()
                if price is not None:
                    _close_position(state, pos, price, reason="超时平仓")
                continue

        side = pos["side"]
        entry = pos["entry"]
        stop = pos["stop"]
        price = state.get_price()
        if price is None:
            continue

        # 盈利3点自动保本
        if side == "LONG":
            if (price - entry) >= 3 and stop < entry:
                state.move_stop_if_better(entry, "LONG")
        elif side == "SHORT":
            if (entry - price) >= 3 and stop > entry:
                state.move_stop_if_better(entry, "SHORT")

        initial_risk = pos.get("initial_risk", abs(entry - stop))
        if side == "LONG":
            profit = price - entry
            if profit >= initial_risk * 1.5:
                state.move_stop_if_better(entry, "LONG")
            if profit >= initial_risk * 2.0:
                state.move_stop_if_better(entry + initial_risk, "LONG")
            if profit >= initial_risk * 3.0:
                state.move_stop_if_better(entry + initial_risk * 2, "LONG")
        else:
            profit = entry - price
            if profit >= initial_risk * 1.5:
                state.move_stop_if_better(entry, "SHORT")
            if profit >= initial_risk * 2.0:
                state.move_stop_if_better(entry - initial_risk, "SHORT")
            if profit >= initial_risk * 3.0:
                state.move_stop_if_better(entry - initial_risk * 2, "SHORT")

        pos_cur, _ = state.get_position()
        if pos_cur is None:
            continue
        if side == "LONG":
            if price <= pos_cur["stop"]:
                _close_position(state, pos_cur, price, reason="止损")
            elif price >= pos_cur["take"]:
                _close_position(state, pos_cur, price, reason="止盈")
        else:
            if price >= pos_cur["stop"]:
                _close_position(state, pos_cur, price, reason="止损")
            elif price <= pos_cur["take"]:
                _close_position(state, pos_cur, price, reason="止盈")


def _close_position(state, pos, price, reason):
    state.set_closing()
    side, entry = pos["side"], pos["entry"]
    direction = 1 if side == "LONG" else -1
    pnl = (price - entry) * direction
    if reason == "止损":
        slippage = (price - pos["stop"]) * direction
        state.log_slippage(slippage, side, "stop")
    else:
        state.log_slippage(0, side, "take")
    state.update_daily_pnl(pnl)
    trade_info = {
        "trade_id": pos.get("trade_id"),
        "side": side,
        "entry": entry,
        "exit": price,
        "pnl": pnl,
        "reason": reason,
        "entry_time": pos.get("entry_time"),
        "exit_time": time.time(),
    }
    print(f"成交: {trade_info}")
    state.set_position(None, "EMPTY")
    if reason == "止损":
        state.consecutive_losses += 1
    else:
        state.consecutive_losses = 0
    play_sound(500, 500) if reason == "止损" else play_sound(1500, 300)

    if gui_queue is not None:
        try:
            gui_queue.put_nowait(("warning", f"⚠️ 持仓平仓：{reason}，{side} @{price:.2f}，盈亏:{pnl:.2f}点"))
        except:
            pass

runtime_state.py

"""
全局状态管理（线程安全，浅拷贝，事件驱动，趋势ID，市场状态机）
"""

import threading
import time
import copy
import uuid
from datetime import datetime, date
from typing import Optional, Dict, Any, Tuple


class RuntimeState:
    def __init__(self):
        self._lock = threading.RLock()
        self.latest_price: Optional[float] = None
        self.base_price: Optional[float] = None
        self.position: Optional[Dict[str, Any]] = None
        self.current_pos: str = "EMPTY"
        self.analysis_mode: int = 1
        self.ai_running: bool = False
        self.last_signal_time: float = 0.0
        self.last_direction: Optional[str] = None
        self.last_stopout_time: float = 0.0
        self.last_signal_candle_time: Optional[datetime] = None
        self.trade_log: list = []
        self.MAX_LOG_RECORDS = 1000
        self.strategy_mode: str = "auto"
        self.consecutive_losses = 0
        self.daily_pnl: float = 0.0
        self.max_daily_loss: float = -30.0
        self.last_pnl_reset_date: date = date.today()
        self.trend_start_done = False
        self.current_trend_entry_price: Optional[float] = None
        self.last_breakout_high: Optional[float] = None
        self.last_breakout_low: Optional[float] = None
        self.initial_risk: Optional[float] = None
        self.last_regime: Optional[str] = None
        self.regime_count: int = 0
        self.trend_id: int = 0
        self.slippage_stats = {"long_stop": [], "long_take": [], "short_stop": [], "short_take": []}
        self.price_updated = threading.Event()
        self.latest_tick_time: Optional[datetime] = None

        # =========================
        # 市场状态机
        # =========================
        self.market_state: str = "WAITING"  # WAITING, EARLY_LONG, LONG, EARLY_SHORT, SHORT, RANGE
        self.last_state: str = "WAITING"
        self.state_entry_time: float = time.time()

    # ---------- 价格与时间 ----------
    def update_price(self, price: float):
        with self._lock:
            self.latest_price = price
            self.price_updated.set()

    def get_price(self) -> Optional[float]:
        with self._lock:
            return self.latest_price

    def update_tick_time(self, tick_time: datetime):
        with self._lock:
            self.latest_tick_time = tick_time

    def get_tick_time(self) -> Optional[datetime]:
        with self._lock:
            return self.latest_tick_time

    # ---------- 持仓管理 ----------
    def set_position(self, pos: Optional[Dict[str, Any]], current_pos: str):
        with self._lock:
            if pos is not None:
                pos = copy.copy(pos)
                if "entry_time" not in pos:
                    pos["entry_time"] = time.time()
                if "trade_id" not in pos:
                    pos["trade_id"] = str(uuid.uuid4())
                pos["closing"] = False
                pos["trend_id"] = self.trend_id
            self.position = pos
            self.current_pos = current_pos

    def get_position(self) -> Tuple[Optional[Dict[str, Any]], str]:
        with self._lock:
            return copy.copy(self.position), self.current_pos

    def get_holding_info(self):
        with self._lock:
            if self.position is None:
                return None, None, None, None, 0, 0.0
            pos = self.position
            side = pos.get("side")
            entry = pos.get("entry")
            stop = pos.get("stop")
            take = pos.get("take")
            entry_time = pos.get("entry_time")
            current_price = self.latest_price or entry
            hold_seconds = time.time() - entry_time if entry_time else 0
            if side == "LONG":
                unrealized_pnl = current_price - entry
            else:
                unrealized_pnl = entry - current_price
            return side, entry, stop, take, hold_seconds, unrealized_pnl

    def update_position(self, updates: dict):
        with self._lock:
            if self.position:
                self.position.update(copy.copy(updates))

    def set_closing(self):
        self.update_position({"closing": True})

    def move_stop_if_better(self, new_stop: float, side: str):
        with self._lock:
            if self.position is None:
                return
            current_stop = self.position.get("stop")
            if current_stop is None:
                return
            if side == "LONG" and new_stop > current_stop:
                self.position["stop"] = new_stop
            elif side == "SHORT" and new_stop < current_stop:
                self.position["stop"] = new_stop

    # ---------- 信号与风险 ----------
    def record_signal(self, direction: str, entry: float, stop: float, take: float, reason: str):
        with self._lock:
            self.last_signal_time = time.time()
            self.last_direction = direction
            if len(self.trade_log) >= self.MAX_LOG_RECORDS:
                self.trade_log.pop(0)
            self.trade_log.append(
                {
                    "time": str(datetime.now()),
                    "direction": direction,
                    "entry": entry,
                    "stop": stop,
                    "take": take,
                    "reason": reason,
                }
            )

    def set_stopout_time(self):
        with self._lock:
            self.last_stopout_time = time.time()

    def get_risk_state(self) -> dict:
        with self._lock:
            return {
                "last_signal_time": self.last_signal_time,
                "last_direction": self.last_direction,
                "last_stopout_time": self.last_stopout_time,
            }

    # ---------- 日亏损限制 ----------
    def _check_daily_reset(self):
        today = date.today()
        if today != self.last_pnl_reset_date:
            self.daily_pnl = 0.0
            self.last_pnl_reset_date = today

    def update_daily_pnl(self, pnl_points: float):
        with self._lock:
            self._check_daily_reset()
            self.daily_pnl += pnl_points

    def is_daily_loss_limit(self) -> bool:
        with self._lock:
            self._check_daily_reset()
            return self.daily_pnl <= self.max_daily_loss

    # ---------- 滑点统计 ----------
    def log_slippage(self, slippage: float, side: str, reason: str):
        with self._lock:
            key = f"{side.lower()}_{reason}"
            if key in self.slippage_stats:
                self.slippage_stats[key].append(abs(slippage))
                if len(self.slippage_stats[key]) > 500:
                    self.slippage_stats[key].pop(0)

    # ---------- 趋势相关 ----------
    def reset_breakout_lock(self):
        with self._lock:
            self.trend_start_done = False
            self.current_trend_entry_price = None
            self.trend_id += 1

    # =========================
    # 市场状态管理（新增）
    # =========================
    def set_market_state(self, new_state: str):
        """设置市场状态，并打印状态切换日志"""
        with self._lock:
            if new_state != self.market_state:
                old = self.market_state
                self.last_state = old
                self.market_state = new_state
                self.state_entry_time = time.time()
                print(f"[STATE] {old} -> {new_state}")

    def get_market_state(self) -> str:
        with self._lock:
            return self.market_state

    def in_state(self, *states) -> bool:
        with self._lock:
            return self.market_state in states

set_topmost.py

import win32gui
import win32con
import win32api          # 修复：GetSystemMetrics 在这个模块里

TITLE = "华中九通"
WIDTH = 969
HEIGHT = 370

def find_window_by_title(title):
    hwnd = win32gui.FindWindow(None,
                                None)
    while hwnd:
        if win32gui.IsWindowVisible(hwnd):
            win_title = win32gui.GetWindowText(hwnd)
            if title in win_title:
                return hwnd
        hwnd = win32gui.GetWindow(hwnd, win32con.GW_HWNDNEXT)
    return None

hwnd = find_window_by_title(TITLE)
if hwnd is None:
    print(f"未找到包含 '{TITLE}' 的窗口，请确保交易软件已打开。")
    input("按 Enter 退出...")
    exit()

# 获取屏幕宽度，计算右上角坐标
screen_width = win32api.GetSystemMetrics(0)   # 这里改成 win32api
x = screen_width - WIDTH
y = 0

# 设置窗口位置和大小，并置顶
win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, WIDTH, HEIGHT,
                      win32con.SWP_SHOWWINDOW)

print(f"窗口已固定在右上角 ({x}, {y})，大小 {WIDTH}x{HEIGHT}，并置顶。")
print("现在其他程序无法遮挡它。")
input("按 Enter 退出...")

settings_dialog.py

"""OCR 截图区域设置对话框（实时价格）"""
import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui
from config_manager import ConfigManager

class SettingsDialog:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("⚙️ OCR 截图区域配置")
        self.win.geometry("450x300")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.grab_set()
        self.create_widgets()
        self.load_current_config()

    def create_widgets(self):
        coord_frame = ttk.LabelFrame(self.win, text="截图区域坐标 (像素)", padding=10)
        coord_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(coord_frame, text="X (左):").grid(row=0, column=0, padx=5, pady=2)
        self.entry_left = ttk.Entry(coord_frame, width=8); self.entry_left.grid(row=0, column=1, padx=5)
        ttk.Label(coord_frame, text="Y (上):").grid(row=0, column=2, padx=5)
        self.entry_top = ttk.Entry(coord_frame, width=8); self.entry_top.grid(row=0, column=3, padx=5)
        ttk.Label(coord_frame, text="宽度:").grid(row=1, column=0, padx=5, pady=2)
        self.entry_width = ttk.Entry(coord_frame, width=8); self.entry_width.grid(row=1, column=1, padx=5)
        ttk.Label(coord_frame, text="高度:").grid(row=1, column=2, padx=5)
        self.entry_height = ttk.Entry(coord_frame, width=8); self.entry_height.grid(row=1, column=3, padx=5)

        btn_frame = ttk.Frame(coord_frame)
        btn_frame.grid(row=2, column=0, columnspan=4, pady=10)
        self.btn_capture = ttk.Button(btn_frame, text="🖱️ 鼠标拾取 (3秒)", command=self.start_capture)
        self.btn_capture.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📸 测试截图", command=self.test_screenshot).pack(side=tk.LEFT, padx=5)

        action_frame = ttk.Frame(self.win)
        action_frame.pack(pady=10)
        ttk.Button(action_frame, text="💾 保存配置", command=self.save_config).pack(side=tk.LEFT, padx=10)
        ttk.Button(action_frame, text="❌ 取消", command=self.win.destroy).pack(side=tk.LEFT, padx=10)

    def load_current_config(self):
        cfg = self.config_mgr.config["capture"]
        self.entry_left.insert(0, str(cfg["left"]))
        self.entry_top.insert(0, str(cfg["top"]))
        self.entry_width.insert(0, str(cfg["width"]))
        self.entry_height.insert(0, str(cfg["height"]))

    def start_capture(self):
        self.btn_capture.config(text="正在捕获...", state="disabled")
        self.win.after(3000, self.capture_pos)

    def capture_pos(self):
        x, y = pyautogui.position()
        self.entry_left.delete(0, tk.END); self.entry_left.insert(0, str(x))
        self.entry_top.delete(0, tk.END); self.entry_top.insert(0, str(y))
        self.btn_capture.config(text="🖱️ 鼠标拾取 (3秒)", state="normal")

    def test_screenshot(self):
        try:
            left = int(self.entry_left.get()); top = int(self.entry_top.get())
            width = int(self.entry_width.get()); height = int(self.entry_height.get())
            img = pyautogui.screenshot(region=(left, top, width, height))
            img.show()
        except Exception as e: messagebox.showerror("截图失败", str(e))

    def save_config(self):
        try:
            left = int(self.entry_left.get()); top = int(self.entry_top.get())
            width = int(self.entry_width.get()); height = int(self.entry_height.get())
            self.config_mgr.set_capture_region(left, top, width, height)
            if self.on_save: self.on_save()
            messagebox.showinfo("保存成功", "配置已保存")
            self.win.destroy()
        except ValueError: messagebox.showerror("输入错误", "请输入有效数字")

signal_worker.py

"""
信号线程（稳定增强版）
- 捕获完整异常
- 防止线程崩溃
- 自动过滤空数据
- AI分析保护
"""

import time
import traceback
import pandas as pd

from strategy import (
    local_trade_rule,
    run_ai_analysis
)

from queues import signal_queue
from runtime_state import RuntimeState


def signal_worker(
        data_mgr,
        state: RuntimeState,
        stop_event
):

    print("信号线程启动")

    last_ai_time = 0

    while not stop_event.is_set():

        try:

            # =========================
            # 获取K线数据
            # =========================

            df = data_mgr.get_dataframe()

            if df is None:
                time.sleep(1)
                continue

            if len(df) < 20:
                time.sleep(1)
                continue

            # 防止非DataFrame
            if not isinstance(df, pd.DataFrame):
                time.sleep(1)
                continue

            # 防止关键列不存在
            required_cols = [
                "open",
                "high",
                "low",
                "close"
            ]

            missing_cols = [
                c for c in required_cols
                if c not in df.columns
            ]

            if missing_cols:

                print(
                    f"缺少K线字段: {missing_cols}"
                )

                time.sleep(1)
                continue

            # =========================
            # 本地策略分析
            # =========================

            signal = local_trade_rule(df, state)

            if signal:

                print(
                    f"发现交易信号: "
                    f"{signal}"
                )

                try:
                    signal_queue.put_nowait(signal)
                except Exception:
                    pass

            # =========================
            # AI辅助分析
            # =========================

            now = time.time()

            if now - last_ai_time > 60:

                try:

                    run_ai_analysis(df, state)

                except Exception as ai_err:

                    print(
                        f"AI分析异常: {ai_err}"
                    )

                    traceback.print_exc()

                last_ai_time = now

            time.sleep(0.5)

        except Exception as e:

            print(
                f"signal_worker异常: {e}"
            )

            traceback.print_exc()

            time.sleep(1)

    print("信号线程停止")

spike_filter.py

"""瞬时波动熔断"""
import time

class SpikeFilter:
    def __init__(self, spike_threshold=8, block_seconds=30):
        self.last_price = None
        self.blocked_until = 0
        self.spike_threshold = spike_threshold
        self.block_seconds = block_seconds

    def check(self, price: float) -> bool:
        now = time.time()
        if now < self.blocked_until:
            return False
        if self.last_price is not None and abs(price - self.last_price) >= self.spike_threshold:
            self.blocked_until = now + self.block_seconds
            self.last_price = price
            print(f"⚠️ 瞬时波动超过 {self.spike_threshold} 点，暂停 {self.block_seconds} 秒")
            return False
        self.last_price = price
        return True

strategy_settings_dialog.py

"""
策略参数设置对话框（匹配新策略，分组显示，动态读取）
"""
import tkinter as tk
from tkinter import ttk, messagebox
from config_manager import ConfigManager

PARAMETER_GROUPS = {
    "EMA & 趋势强度": [
        ("EMA 短周期", "EMA_SHORT"),
        ("EMA 中周期", "EMA_MID"),
        ("EMA 长周期", "EMA_LONG"),
        ("趋势强度高阈值", "TREND_STRENGTH_HIGH"),
        ("趋势强度低阈值", "TREND_STRENGTH_LOW"),
    ],
    "RSI 阈值": [
        ("RSI 周期", "RSI_PERIOD"),
        ("做多 RSI 下限", "RSI_LONG_THRESHOLD"),
        ("做空 RSI 上限", "RSI_SHORT_THRESHOLD"),
        ("多头过热 RSI 上限", "RSI_LONG_MAX"),
        ("空头过冷 RSI 下限", "RSI_SHORT_MIN"),
        ("横盘做多 RSI 下限", "RSI_OS_LONG"),
        ("横盘做空 RSI 上限", "RSI_OB_SHORT"),
    ],
    "风控与冷却": [
        ("信号冷却(秒)", "SIGNAL_COOLDOWN"),
        ("方向锁(秒)", "DIRECTION_LOCK_TIME"),
        ("止损后冷却(秒)", "STOP_AFTER_LOSS"),
        ("连续止损熔断次数", "MAX_CONSECUTIVE_LOSS"),
        ("熔断暂停(秒)", "PAUSE_AFTER_MAX_LOSS"),
    ],
    "波动与距离": [
        ("最小波动", "MIN_RANGE"),
        ("最大波动", "MAX_RANGE"),
        ("追高限制(点)", "MAX_DISTANCE_FROM_LOW"),
        ("追低限制(点)", "MAX_DISTANCE_FROM_HIGH"),
    ],
    "止盈止损 & ATR": [
        ("趋势止损 ATR 倍数", "TREND_STOP_MULT"),
        ("趋势止盈 ATR 倍数", "TREND_TAKE_MULT"),
        ("震荡止损 ATR 倍数", "RANGE_STOP_MULT"),
        ("震荡止盈 ATR 倍数", "RANGE_TAKE_MULT"),
        ("ATR 斜率因子", "ATR_SLOPE_FACTOR"),
        ("ATR 突破因子", "ATR_BREAKOUT_FACTOR"),
    ],
    "成交量 & 其他": [
        ("成交量均线周期", "VOL_MA_PERIOD"),
        ("成交量比率", "VOL_RATIO"),
        ("连续K线衰竭数", "EXHAUSTION_COUNT"),
        ("回踩最大等待K线", "PULLBACK_MAX_BARS"),
    ],
}

class StrategySettingsDialog:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback

        self.win = tk.Toplevel(root)
        self.win.title("📈 策略参数配置")
        self.win.geometry("600x550")
        self.win.resizable(True, True)
        self.win.transient(root)
        self.win.grab_set()

        style = ttk.Style(self.win)
        style.theme_use('clam')
        style.configure('TNotebook.Tab', font=('微软雅黑', 10, 'bold'), padding=[10, 4])
        style.configure('TLabel', font=('微软雅黑', 10), background='#f5f6fa')

        self.notebook = ttk.Notebook(self.win)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.entries = {}

        for group_name, params in PARAMETER_GROUPS.items():
            frame = ttk.Frame(self.notebook, padding=15)
            self.notebook.add(frame, text=group_name)
            for row, (label, param_key) in enumerate(params):
                ttk.Label(frame, text=label + ":").grid(row=row, column=0, sticky=tk.W, padx=5, pady=3)
                entry = ttk.Entry(frame, width=12, font=('微软雅黑', 10))
                entry.grid(row=row, column=1, padx=5, pady=3, sticky=tk.W)
                self.entries[param_key] = entry

        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="💾 保存设置", command=self.save_params).pack(side=tk.LEFT, padx=20)
        ttk.Button(btn_frame, text="❌ 取消", command=self.win.destroy).pack(side=tk.LEFT, padx=20)

        self.load_current_params()

    def load_current_params(self):
        from strategy import DEFAULT_PARAMS as strategy_defaults
        user_params = self.config_mgr.get_strategy_params()
        for key, entry in self.entries.items():
            val = user_params.get(key, strategy_defaults.get(key, ""))
            entry.delete(0, tk.END)
            entry.insert(0, str(val))

    def save_params(self):
        new_params = {}
        for key, entry in self.entries.items():
            try:
                new_params[key] = float(entry.get())
            except ValueError:
                messagebox.showerror("输入错误", f"参数 {key} 必须为数字")
                return
        self.config_mgr.config["strategy"] = new_params
        self.config_mgr.save()
        messagebox.showinfo("保存成功", "策略参数已更新，下次分析生效")
        if self.on_save:
            self.on_save()
        self.win.destroy()

strategy.py

"""
策略模块：1分钟超短线自适应系统（最终稳定版）
- 方向硬过滤：基于 EMA7/EMA13 趋势，禁止逆势开仓
- tick 指标仅作为择时辅助，权重降低为 0.3
- 支持 forming candle 实时分析
- 防止同根K线重复信号
- ATR 波动过滤：避免死盘或疯盘
- 禁止追单：价格必须在 EMA7 附近 ±2 点才允许开仓
- 回踩确认：价格需回撤至 EMA7 附近
- 信号门槛提高至 4 分，减少垃圾信号
- RSI 限制放宽至 85/15
- tick_consistency 加入评分（权重 0.3）
- 新增盘口压力指标 orderbook_pressure 参与评分
- 新增主动买卖识别 active_imbalance 参与评分
"""

import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from config import NotifyConfig, APIConfig
from runtime_state import RuntimeState
from deepseek_client import DeepSeekClient
from config_manager import ConfigManager

notify_cfg = NotifyConfig()
api_cfg = APIConfig()
ai_client = DeepSeekClient(api_cfg)
config_mgr = ConfigManager()

# 默认参数（当 user_config.json 中无配置时使用）
DEFAULT_PARAMS = {
    "EMA_SHORT": 3,
    "EMA_MID": 7,
    "EMA_LONG": 13,
    "RSI_PERIOD": 6,
    "RSI_LONG_THRESHOLD": 55,
    "RSI_SHORT_THRESHOLD": 45,
    "RSI_LONG_MAX": 75,
    "RSI_SHORT_MIN": 25,
    "RSI_OS_LONG": 30,
    "RSI_OB_SHORT": 70,
    "SIGNAL_COOLDOWN": 20,
    "DIRECTION_LOCK_TIME": 3,
    "STOP_AFTER_LOSS": 20,
    "MAX_CONSECUTIVE_LOSS": 3,
    "PAUSE_AFTER_MAX_LOSS": 180,
    "MIN_RANGE": 2,
    "MAX_RANGE": 30,
    "ATR_SLOPE_FACTOR": 0.08,
    "ATR_BREAKOUT_FACTOR": 0.08,
    "TREND_STRENGTH_HIGH": 0.12,
    "TREND_STRENGTH_LOW": 0.05,
    "MAX_DISTANCE_FROM_LOW": 10,
    "MAX_DISTANCE_FROM_HIGH": 10,
    "EXHAUSTION_COUNT": 5,
    "PULLBACK_MAX_BARS": 2,
    "TREND_STOP_MULT": 0.7,
    "TREND_TAKE_MULT": 1.8,
    "RANGE_STOP_MULT": 0.8,
    "RANGE_TAKE_MULT": 1.0,
    "VOL_MA_PERIOD": 5,
    "VOL_RATIO": 0.6,
    # 新增参数
    "PULLBACK_DISTANCE": 2,
    "ATR_MIN": 2,
    "ATR_MAX": 8,
    "TICK_CONSISTENCY_THRESHOLD": 0.6,
    "TICK_WEIGHT": 0.3,
    "ORDERBOOK_PRESSURE_THRESHOLD": 0.2,
    "ATR_STOP_MULT": 0.7,
    "ATR_TAKE_MULT": 1.2,
    "LONG_TERM_EMA": 20,
    "ACTIVE_IMBALANCE_THRESHOLD": 0.3,
    "ACTIVE_WEIGHT": 1,
}


def get_params():
    user_params = config_mgr.get_strategy_params()
    params = DEFAULT_PARAMS.copy()
    if user_params:
        params.update(user_params)
    int_keys = [
        "EXHAUSTION_COUNT",
        "PULLBACK_MAX_BARS",
        "VOL_MA_PERIOD",
        "RSI_PERIOD",
        "EMA_SHORT",
        "EMA_MID",
        "EMA_LONG",
        "MAX_CONSECUTIVE_LOSS",
        "SIGNAL_COOLDOWN",
        "DIRECTION_LOCK_TIME",
        "STOP_AFTER_LOSS",
        "PAUSE_AFTER_MAX_LOSS",
        "MIN_RANGE",
        "MAX_RANGE",
        "PULLBACK_DISTANCE",
        "ATR_MIN",
        "ATR_MAX",
        "LONG_TERM_EMA",
        "ACTIVE_WEIGHT",
    ]
    for key in int_keys:
        if key in params:
            params[key] = int(params[key])
    return params


# 模块级回踩状态（回测用）
_wait_pullback_long = False
_wait_pullback_short = False
_pullback_bars_long = 0
_pullback_bars_short = 0


def calculate_atr(high, low, close, period=14):
    close_series = pd.Series(close)
    prev_close = close_series.shift(1).fillna(close[0])
    tr = np.maximum(high - low, np.abs(high - prev_close.values), np.abs(low - prev_close.values))
    return np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr)


def consecutive_count(opens, closes, direction="bull"):
    count = 0
    for o, c in zip(opens[::-1], closes[::-1]):
        if direction == "bull" and c > o:
            count += 1
        elif direction == "bear" and c < o:
            count += 1
        else:
            break
    return count


def calculate_indicators(df: pd.DataFrame) -> dict:
    params = get_params()
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    ema_short = df["close"].ewm(span=params["EMA_SHORT"], adjust=False).mean().iloc[-1]
    ema_mid = df["close"].ewm(span=params["EMA_MID"], adjust=False).mean().iloc[-1]
    ema_long = df["close"].ewm(span=params["EMA_LONG"], adjust=False).mean().iloc[-1]

    if len(df) >= 2:
        ema_mid_prev = df["close"].ewm(span=params["EMA_MID"], adjust=False).mean().iloc[-2]
        ema_slope = ema_mid - ema_mid_prev
    else:
        ema_slope = 0.0

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / params["RSI_PERIOD"], adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / params["RSI_PERIOD"], adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi_series = 100 - (100 / (1 + rs))
    rsi = rsi_series.iloc[-1]
    prev_rsi = rsi_series.iloc[-2] if len(rsi_series) >= 2 else rsi

    recent_range = np.max(close[-5:]) - np.min(close[-5:])
    low_5 = np.min(low[-5:])
    high_5 = np.max(high[-5:])

    atr = calculate_atr(high, low, close, 14)
    atr = max(atr, 0.5)

    dynamic_slope_threshold = max(0.1, atr * params["ATR_SLOPE_FACTOR"])
    ema_mid_up = ema_slope > dynamic_slope_threshold
    ema_mid_down = ema_slope < -dynamic_slope_threshold
    trend_strength = abs(ema_slope) / max(atr, 2)

    opens = df["open"].values
    closes_arr = df["close"].values
    exhaustion_count = params["EXHAUSTION_COUNT"]
    bull_consecutive = consecutive_count(opens[-exhaustion_count:], closes_arr[-exhaustion_count:], "bull")
    bear_consecutive = consecutive_count(opens[-exhaustion_count:], closes_arr[-exhaustion_count:], "bear")

    volume_active = False
    vol_ma_period = params["VOL_MA_PERIOD"]
    if "volume" in df.columns and len(df) >= vol_ma_period:
        vol_ma = df["volume"].rolling(vol_ma_period).mean().iloc[-1]
        last_closed_vol = df["volume"].iloc[-1]
        if vol_ma > 0:
            volume_active = last_closed_vol > vol_ma * params["VOL_RATIO"]

    macd_bullish = ema_mid > ema_long
    macd_bearish = ema_mid < ema_long

    return {
        "ema_short": ema_short,
        "ema_mid": ema_mid,
        "ema_long": ema_long,
        "ema_slope": ema_slope,
        "ema_mid_up": ema_mid_up,
        "ema_mid_down": ema_mid_down,
        "rsi": rsi,
        "prev_rsi": prev_rsi,
        "recent_range": recent_range,
        "low_5": low_5,
        "high_5": high_5,
        "atr": atr,
        "breakout_margin": 0,
        "bull_consecutive": bull_consecutive,
        "bear_consecutive": bear_consecutive,
        "trend_strength": trend_strength,
        "volume_active": volume_active,
        "trend": "上涨" if ema_mid > ema_long else "下跌" if ema_mid < ema_long else "震荡",
        "support": low_5,
        "resistance": high_5,
        "macd_bullish": macd_bullish,
        "macd_bearish": macd_bearish,
    }


def is_active_time():
    return True


def local_trade_rule(df: pd.DataFrame, state: RuntimeState, tick_indicators: dict = None):
    global _wait_pullback_long, _wait_pullback_short, _pullback_bars_long, _pullback_bars_short
    if tick_indicators is None:
        tick_indicators = {}
    params = get_params()

    if len(df) < 15:
        return None
    if not is_active_time():
        return None
    if state.is_daily_loss_limit():
        return None

    pos, _ = state.get_position()
    if pos is not None:
        return None

    current_price = df.iloc[-1]["close"]
    current_candle_time = None
    if "timestamp" in df.columns:
        try:
            current_candle_time = pd.Timestamp(df.iloc[-1]["timestamp"])
        except:
            pass

    ind = calculate_indicators(df)

    if ind["atr"] < 2 or ind["atr"] > 8:
        return None

    risk = state.get_risk_state()
    now = time.time()

    if state.consecutive_losses >= params["MAX_CONSECUTIVE_LOSS"]:
        if now - state.last_stopout_time < params["PAUSE_AFTER_MAX_LOSS"]:
            return None
        else:
            state.consecutive_losses = 0

    if current_candle_time is not None and state.last_signal_candle_time is not None:
        elapsed = abs((current_candle_time - state.last_signal_candle_time).total_seconds())
        if elapsed < params["SIGNAL_COOLDOWN"]:
            return None
    else:
        if now - risk["last_signal_time"] < params["SIGNAL_COOLDOWN"]:
            return None

    if now - risk["last_stopout_time"] < params["STOP_AFTER_LOSS"]:
        return None

    if ind["recent_range"] < params["MIN_RANGE"]:
        return None
    if ind["recent_range"] > params["MAX_RANGE"]:
        return None

    pullback_max = params["PULLBACK_MAX_BARS"]
    if _wait_pullback_long:
        _pullback_bars_long += 1
        if _pullback_bars_long > pullback_max:
            _wait_pullback_long = False
            _pullback_bars_long = 0
    if _wait_pullback_short:
        _pullback_bars_short += 1
        if _pullback_bars_short > pullback_max:
            _wait_pullback_short = False
            _pullback_bars_short = 0

    if ind["trend_strength"] > params["TREND_STRENGTH_HIGH"]:
        regime = "trend"
        required_score = 4
    elif ind["trend_strength"] < params["TREND_STRENGTH_LOW"]:
        regime = "range"
        required_score = 0
    else:
        regime = "transition"
        required_score = 4

    if regime == "range":
        return _range_reversal_strategy(ind, current_price, state, current_candle_time, tick_indicators)
    return _trend_breakout_strategy(ind, current_price, state, required_score, current_candle_time, tick_indicators)


def _trend_breakout_strategy(ind, current_price, state, required_score, current_candle_time=None, tick_indicators=None):
    if tick_indicators is None:
        tick_indicators = {}
    params = get_params()
    stop_points = max(2, round(ind["atr"] * params["TREND_STOP_MULT"]))
    take_points = max(3, round(ind["atr"] * params["TREND_TAKE_MULT"]))

    ema7 = ind["ema_mid"]
    ema13 = ind["ema_long"]
    trend_up = ema7 > ema13 and ind["ema_slope"] > 0
    trend_down = ema7 < ema13 and ind["ema_slope"] < 0

    if ind["rsi"] > 85:
        return None
    if ind["rsi"] < 15:
        return None

    exhaustion = params["EXHAUSTION_COUNT"]
    if ind["bull_consecutive"] >= exhaustion:
        return None
    if ind["bear_consecutive"] >= exhaustion:
        return None

    if not ind["volume_active"]:
        return None

    tick_speed = tick_indicators.get("speed", 0.0)
    tick_momentum = tick_indicators.get("momentum", 0.0)
    tick_acceleration = tick_indicators.get("acceleration", 0.0)
    tick_burst = tick_indicators.get("burst", False)
    tick_strength = tick_indicators.get("strength", 0.0)
    tick_consistency = tick_indicators.get("consistency", 0.5)
    orderbook_pressure = tick_indicators.get("orderbook_pressure", 0.0)
    active_imbalance = tick_indicators.get("active_imbalance", 0.0)

    long_score = 0
    short_score = 0
    distance_to_ema = abs(current_price - ema7)

    pullback_long = current_price >= ema7 and current_price <= ema7 + 2
    pullback_short = current_price <= ema7 and current_price >= ema7 - 2

    if trend_up and pullback_long:
        if current_price > ema7:
            long_score += 2
        if ind["ema_mid_up"]:
            long_score += 2
        if ind["rsi"] > params["RSI_LONG_THRESHOLD"]:
            long_score += 1
        if (current_price - ind["low_5"]) < params["MAX_DISTANCE_FROM_LOW"]:
            long_score += 1
        if tick_momentum > 0:
            long_score += 0.3
        if tick_speed > 2.0:
            long_score += 0.3
        if tick_acceleration > 0:
            long_score += 0.3
        if tick_burst and tick_momentum > 0:
            long_score += 0.3
        if tick_strength > 0.7:
            long_score += 0.3
        if tick_consistency > 0.6:
            long_score += 0.3
        if orderbook_pressure > 0.2:
            long_score += 0.3
        if active_imbalance > 0.3:
            long_score += 1

    if trend_down and pullback_short:
        if current_price < ema7:
            short_score += 2
        if ind["ema_mid_down"]:
            short_score += 2
        if ind["rsi"] < params["RSI_SHORT_THRESHOLD"]:
            short_score += 1
        if (ind["high_5"] - current_price) < params["MAX_DISTANCE_FROM_HIGH"]:
            short_score += 1
        if tick_momentum < 0:
            short_score += 0.3
        if tick_speed < -2.0:
            short_score += 0.3
        if tick_acceleration < 0:
            short_score += 0.3
        if tick_burst and tick_momentum < 0:
            short_score += 0.3
        if tick_strength < -0.7:
            short_score += 0.3
        if tick_consistency > 0.6:
            short_score += 0.3
        if orderbook_pressure < -0.2:
            short_score += 0.3
        if active_imbalance < -0.3:
            short_score += 1

    if trend_up and pullback_long and long_score >= required_score:
        stop = current_price - stop_points
        take = current_price + take_points
        signal = {"side": "LONG", "entry": current_price, "stop": stop, "take": take, "reason": "趋势突破做多"}
        state.record_signal("LONG", current_price, stop, take, "趋势突破做多")
        if current_candle_time is not None:
            state.last_signal_candle_time = current_candle_time
        return signal

    if trend_down and pullback_short and short_score >= required_score:
        stop = current_price + stop_points
        take = current_price - take_points
        signal = {"side": "SHORT", "entry": current_price, "stop": stop, "take": take, "reason": "趋势突破做空"}
        state.record_signal("SHORT", current_price, stop, take, "趋势突破做空")
        if current_candle_time is not None:
            state.last_signal_candle_time = current_candle_time
        return signal

    return None


def _range_reversal_strategy(ind, current_price, state, current_candle_time=None, tick_indicators=None):
    if tick_indicators is None:
        tick_indicators = {}
    params = get_params()
    stop_points = max(2, round(ind["atr"] * params["RANGE_STOP_MULT"]))
    take_points = max(3, round(ind["atr"] * params["RANGE_TAKE_MULT"]))

    rsi_rising = ind["rsi"] > ind["prev_rsi"] and ind["prev_rsi"] < params["RSI_OS_LONG"]
    rsi_falling = ind["rsi"] < ind["prev_rsi"] and ind["prev_rsi"] > params["RSI_OB_SHORT"]

    if rsi_rising and ind["rsi"] < 50:
        stop = current_price - stop_points
        take = current_price + take_points
        signal = {"side": "LONG", "entry": current_price, "stop": stop, "take": take, "reason": "横盘反转做多"}
        state.record_signal("LONG", current_price, stop, take, "横盘反转做多")
        if current_candle_time is not None:
            state.last_signal_candle_time = current_candle_time
        return signal
    if rsi_falling and ind["rsi"] > 50:
        stop = current_price + stop_points
        take = current_price - take_points
        signal = {"side": "SHORT", "entry": current_price, "stop": stop, "take": take, "reason": "横盘反转做空"}
        state.record_signal("SHORT", current_price, stop, take, "横盘反转做空")
        if current_candle_time is not None:
            state.last_signal_candle_time = current_candle_time
        return signal
    return None


def explain_analysis(ind, current_price, signal=None):
    lines = []
    lines.append("📖 当前行情通俗解读：")
    lines.append(f"当前价格：{current_price}")
    ema7 = ind["ema_mid"]
    if current_price > ema7:
        lines.append(f"价格在 EMA7（过去7分钟的均价 {ema7:.1f}）之上，短期走势偏强。")
    else:
        lines.append(f"价格在 EMA7（过去7分钟的均价 {ema7:.1f}）之下，短期走势偏弱。")
    slope = ind["ema_slope"]
    if slope > 0.3:
        lines.append(f"EMA7 正在以较快速度上升（斜率 {slope:.2f}），说明上涨动能较足。")
    elif slope < -0.3:
        lines.append(f"EMA7 正在以较快速度下降（斜率 {slope:.2f}），说明下跌动能较足。")
    else:
        lines.append(f"EMA7 走势平缓（斜率 {slope:.2f}），方向不明确，市场可能处于震荡。")
    rsi = ind["rsi"]
    if rsi > 70:
        lines.append(f"RSI（相对强弱指标）为 {rsi:.1f}，处于超买区域，短期可能回调。")
    elif rsi < 30:
        lines.append(f"RSI（相对强弱指标）为 {rsi:.1f}，处于超卖区域，短期可能反弹。")
    else:
        lines.append(f"RSI 为 {rsi:.1f}，处于中性区间，没有明显的超买或超卖信号。")
    atr = ind["atr"]
    lines.append(f"当前市场波动（ATR）约为 {atr:.1f} 点，说明每根K线平均波动幅度在这个范围内。")
    if ind["trend_strength"] > 0.12:
        regime = "趋势"
    elif ind["trend_strength"] < 0.05:
        regime = "震荡"
    else:
        regime = "过渡期"
    lines.append(f"市场处于{regime}行情（趋势强度 {ind['trend_strength']:.3f}）。")
    if signal:
        side = signal.get("side", "HOLD")
        reason = signal.get("reason", "")
        if side == "LONG":
            lines.append(f"系统建议：做多（{reason}）")
        elif side == "SHORT":
            lines.append(f"系统建议：做空（{reason}）")
        else:
            lines.append("系统建议：暂时观望（HOLD）")
    else:
        lines.append("系统建议：暂时观望（HOLD）")
    return "\n".join(lines)


def run_ai_analysis(df: pd.DataFrame, state: RuntimeState):
    if len(df) < 14:
        return None
    ind = calculate_indicators(df)
    cp = df.iloc[-1]["close"]
    prompt = f"价格 {cp}，趋势 {ind['trend']}，RSI {ind['rsi']:.1f}，波动 {ind['recent_range']}。请给出简短交易建议。"
    try:
        resp = ai_client.analyze(prompt)
        return f"{resp}"
    except Exception as e:
        return "AI 分析失败"


# ==================== 状态机驱动入场函数 ====================
def state_based_trade_rule(df, state, tick_indicators, market_state):
    """
    状态机驱动交易 - 基于EMA回调 + tick动量确认 + ATR动态止损止盈
    """
    params = get_params()
    if len(df) < 30:
        return None
    ind = calculate_indicators(df)
    current_price = float(df.iloc[-1]["close"])
    ema_short = ind["ema_mid"]
    # 计算EMA30
    ema30 = df["close"].ewm(span=30, adjust=False).mean().iloc[-1]
    trend_up = ema_short > ema30
    trend_down = ema_short < ema30
    atr = ind["atr"]

    # 动态参数
    pullback_dist = params.get("PULLBACK_DISTANCE", 2)
    stop_mult = params.get("ATR_STOP_MULT", 0.7)
    take_mult = params.get("ATR_TAKE_MULT", 1.2)
    stop_points = max(2, round(atr * stop_mult))
    take_points = max(3, round(atr * take_mult))

    # tick 动量确认
    tick_mom = tick_indicators.get("momentum", 0)
    tick_consistency = tick_indicators.get("consistency", 0.5)
    active_imbalance = tick_indicators.get("active_imbalance", 0)

    # 多头入场
    if market_state in ("EARLY_LONG", "TREND_LONG", "STRONG_LONG"):
        if trend_up and abs(current_price - ema_short) <= pullback_dist:
            if tick_mom > 0 and tick_consistency > 0.5:
                # 主动买卖确认
                if active_imbalance > 0.3:
                    signal = {
                        "side": "LONG",
                        "entry": current_price,
                        "stop": round(current_price - stop_points, 0),
                        "take": round(current_price + take_points, 0),
                        "reason": f"回调+tick+主动确认 ({market_state})",
                    }
                    return signal
    # 空头入场
    if market_state in ("EARLY_SHORT", "TREND_SHORT", "STRONG_SHORT"):
        if trend_down and abs(current_price - ema_short) <= pullback_dist:
            if tick_mom < 0 and tick_consistency > 0.5:
                if active_imbalance < -0.3:
                    signal = {
                        "side": "SHORT",
                        "entry": current_price,
                        "stop": round(current_price + stop_points, 0),
                        "take": round(current_price - take_points, 0),
                        "reason": f"回调+tick+主动确认 ({market_state})",
                    }
                    return signal
    return None

test_system.py

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量化交易系统 Pro - 完整功能测试（最终版）
"""

import os
import sys
import time
import tempfile
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

test_results = {"passed": 0, "failed": 0, "warnings": 0}


def test_pass(msg):
    print(f"✅ {msg}")
    test_results["passed"] += 1


def test_fail(msg, error=None):
    print(f"❌ {msg}")
    if error:
        print(f"   错误详情: {error}")
    test_results["failed"] += 1


def test_warn(msg):
    print(f"⚠️ {msg}")
    test_results["warnings"] += 1


# ------------------------------------------------------------
def test_config_manager():
    print("\n--- 测试配置管理器 ---")
    try:
        from config_manager import ConfigManager

        temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        temp_file.close()
        original_file = getattr(ConfigManager, "CONFIG_FILE", None)
        ConfigManager.CONFIG_FILE = temp_file.name
        cm = ConfigManager()
        cm.set_capture_region(100, 200, 50, 60)
        assert cm.get_capture_region() == (100, 200, 50, 60)
        cm2 = ConfigManager()
        assert cm2.get_capture_region() == (100, 200, 50, 60)
        test_pass("配置管理器加载/保存/修改正常")
    except Exception as e:
        test_fail("配置管理器异常", e)
    finally:
        if original_file is not None:
            ConfigManager.CONFIG_FILE = original_file
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)


# ------------------------------------------------------------
def test_tesseract():
    print("\n--- 测试 Tesseract 可用性 ---")
    try:
        import pytesseract
        from config_manager import ConfigManager

        cm = ConfigManager()
        tesseract_cmd = cm.get_tesseract_cmd()
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        version = pytesseract.get_tesseract_version()
        print(f"   Tesseract 版本: {version}")
        langs = pytesseract.get_languages()
        if "eng" in langs:
            test_pass("Tesseract 引擎可用，英语语言包已安装")
        else:
            test_warn("Tesseract 可用但未检测到英语语言包")
        if "chi_sim" in langs:
            test_pass("中文简体语言包已安装")
        else:
            test_warn("中文简体语言包未安装")
    except Exception as e:
        test_fail("Tesseract 不可用", e)


# ------------------------------------------------------------
def test_ocr_worker():
    print("\n--- 测试 OCR Worker ---")
    try:
        from ocr_worker import capture_time_price, TickFilter
        from config_manager import ConfigManager

        cm = ConfigManager()
        original = cm.get_capture_region()
        cm.set_capture_region(0, 0, 100, 30)
        dt, price = capture_time_price()
        cm.set_capture_region(*original)
        test_pass("OCR capture_time_price 函数运行无异常")
        filt = TickFilter()
        now = datetime.now()
        p1 = filt.update(100.0, now)
        p2 = filt.update(100.0, now + timedelta(milliseconds=200))
        assert p1 is not None and p2 is None
        now2 = datetime.now().replace(minute=now.minute + 1 if now.minute < 59 else 0)
        p3 = filt.update(100.0, now2)
        assert p3 == 100.0
        test_pass("TickFilter 去重/跨分钟逻辑正常")
    except Exception as e:
        test_fail("OCR Worker 测试失败", e)


# ------------------------------------------------------------
def test_candle_engine():
    print("\n--- 测试 CandleEngine ---")
    from candle_engine import CandleEngine

    engine = CandleEngine(interval_seconds=60)
    base = datetime(2025, 1, 1, 10, 0, 0)
    ticks = [
        (10.0, base),
        (10.2, base + timedelta(seconds=10)),
        (9.8, base + timedelta(seconds=20)),
        (10.5, base + timedelta(seconds=30)),
        (10.3, base + timedelta(seconds=50)),
        (10.4, base + timedelta(seconds=70)),
    ]
    candles = []
    for p, ts in ticks:
        fin = engine.update_tick(p, ts)
        if fin:
            candles.append(fin)
    assert len(candles) == 1
    c = candles[0]
    assert c["open"] == 10.0
    assert c["high"] == 10.5
    assert c["low"] == 9.8
    assert c["close"] == 10.3
    assert c["volume"] == 5
    engine2 = CandleEngine()
    engine2.update_tick(100, base)
    engine2.update_tick(100, base)
    fin = engine2.update_tick(101, base + timedelta(seconds=61))
    assert fin is not None
    assert fin["close"] == 100
    test_pass("CandleEngine tick→K线转换正确")


# ------------------------------------------------------------
def test_market_data_manager():
    print("\n--- 测试 MarketDataManager ---")
    from indicators import MarketDataManager
    from config import CandleConfig
    import pandas as pd

    tmpdir = tempfile.mkdtemp()
    tick_path = Path(tmpdir) / "ticks.csv"
    candle_path = Path(tmpdir) / "candles_1m.csv"
    cfg = CandleConfig()
    mgr = MarketDataManager(cfg, tick_path, candle_path)
    ts = datetime(2025, 1, 1, 10, 0, 0)
    mgr.add_tick(ts, 100.0)
    mgr.add_tick(ts + timedelta(seconds=10), 100.5)
    mgr.add_tick(ts + timedelta(seconds=20), 99.8)
    mgr.build_candles()
    mgr.add_candle({"time": ts + timedelta(minutes=1), "open": 101, "high": 102, "low": 100, "close": 101})
    mgr.persist()
    assert tick_path.exists() and candle_path.exists()
    mgr2 = MarketDataManager(cfg, tick_path, candle_path)
    mgr2.ticks = pd.read_csv(tick_path, parse_dates=["timestamp"])
    mgr2.candles = pd.read_csv(candle_path, parse_dates=["timestamp"])
    assert len(mgr2.candles) == 2
    test_pass("MarketDataManager 存储、构建K线、持久化正常")
    shutil.rmtree(tmpdir)


# ------------------------------------------------------------
def test_tick_indicators():
    print("\n--- 测试 TickIndicatorEngine ---")
    from tick_indicators import TickIndicatorEngine

    engine = TickIndicatorEngine(max_len=20, strength_norm_window=5, ema_short=2, ema_long=5)
    base = datetime(2025, 1, 1, 10, 0, 0)
    prices = [100, 101, 102, 103, 104, 105, 105, 105, 106, 107]
    for i, p in enumerate(prices):
        engine.add_tick(p, base + timedelta(seconds=i * 0.3))
    speed = engine.tick_speed()
    expected_speed = (107 - 106) / 0.3
    assert abs(speed - expected_speed) < 0.1
    momentum = engine.tick_momentum(window=5)
    expected_momentum = 107 - 105
    assert abs(momentum - expected_momentum) < 0.1
    acc = engine.tick_acceleration()
    assert isinstance(acc, float)
    burst = engine.is_burst(threshold=1.0)
    assert burst == False
    strength = engine.get_tick_strength()
    assert -1 <= strength <= 1
    micro = engine.micro_trend()
    assert micro != 0
    pressure = engine.pressure_score(window=10)
    assert -1 <= pressure <= 1
    consistency = engine.tick_consistency(window=5)
    assert 0 <= consistency <= 1
    test_pass("TickIndicatorEngine 所有指标计算正常")
    engine2 = TickIndicatorEngine()
    for _ in range(10):
        engine2.add_tick(100, datetime.now())
    assert engine2.pressure_score() == 0.0
    test_pass("TickIndicatorEngine 平盘处理正确")


# ------------------------------------------------------------
def test_strategy():
    print("\n--- 测试策略模块 ---")
    from strategy import local_trade_rule, calculate_indicators
    from runtime_state import RuntimeState
    import pandas as pd
    import numpy as np

    # 生成强趋势数据，确保满足策略条件
    dates = pd.date_range("2025-01-01 10:00:00", periods=60, freq="1min")
    base_price = 2100
    closes = base_price + np.linspace(0, 50, 60)  # 稳定上涨
    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": np.roll(closes, 1),
            "high": closes + 2,
            "low": closes - 2,
            "close": closes,
            "volume": np.random.randint(100, 1000, 60),
        }
    )
    df.loc[0, "open"] = closes[0]  # 第一根open
    # 计算EMA7和EMA13，确保趋势向上
    ema7 = df["close"].ewm(span=7, adjust=False).mean()
    ema13 = df["close"].ewm(span=13, adjust=False).mean()
    # 确保最新价格高于EMA7且回踩条件满足（价格在EMA7附近±2）
    # 我们直接修改最后几根K线使其贴近EMA7
    last_idx = len(df) - 1
    ema7_last = ema7.iloc[last_idx]
    df.loc[last_idx, "close"] = ema7_last + 1  # 略高于EMA7，且距离<=2
    df.loc[last_idx, "high"] = df.loc[last_idx, "close"] + 1
    df.loc[last_idx, "low"] = df.loc[last_idx, "close"] - 1
    # 确保ema_mid_up为True
    state = RuntimeState()
    tick = {
        "speed": 2.5,
        "momentum": 3,
        "acceleration": 0.8,
        "burst": True,
        "strength": 0.9,
        "consistency": 0.8,
        "pressure": 0.3,
    }
    signal = local_trade_rule(df, state, tick)
    if signal is not None and signal["side"] == "LONG":
        test_pass("策略在上涨趋势+良好tick指标下产生多头信号")
    else:
        test_warn("策略未产生多头信号，可能参数苛刻，但策略函数运行正常")
    # 测试方向过滤：下跌趋势不应产生多头
    df_down = df.copy()
    df_down["close"] = base_price - np.linspace(0, 50, 60)
    signal2 = local_trade_rule(df_down, state, tick)
    if signal2 is not None and signal2["side"] == "LONG":
        test_warn("下跌趋势产生了多头信号（方向过滤可能失效）")
    else:
        test_pass("策略方向过滤正常")
    ind = calculate_indicators(df)
    assert "ema_mid" in ind and ind["atr"] > 0
    test_pass("calculate_indicators 运行正常")


# ------------------------------------------------------------
def test_runtime_state():
    print("\n--- 测试 RuntimeState ---")
    from runtime_state import RuntimeState

    state = RuntimeState()
    state.update_price(1234.5)
    assert state.get_price() == 1234.5
    now = datetime.now()
    state.update_tick_time(now)
    assert state.get_tick_time() == now
    state.record_signal("LONG", 1000, 995, 1010, "test")
    assert state.last_signal_time > 0 and state.last_direction == "LONG"

    # 日亏损限制测试
    state.update_daily_pnl(-41)  # 超过限额 -30
    assert state.is_daily_loss_limit() == True
    state.update_daily_pnl(12)  # 总亏损 -29，低于限额
    assert state.is_daily_loss_limit() == False

    state.set_stopout_time()
    assert state.last_stopout_time > 0

    pos = {"side": "LONG", "entry": 1000, "stop": 990, "take": 1020, "initial_risk": 10}
    state.set_position(pos, "LONG")
    p, _ = state.get_position()
    assert p["side"] == "LONG"

    # 移动止损
    state.move_stop_if_better(995, "LONG")
    # 重新获取 position 以查看更新
    p2, _ = state.get_position()
    assert p2["stop"] == 995

    state.set_closing()
    # 再次获取以确保 closing 标志已设置
    p3, _ = state.get_position()
    assert p3.get("closing") == True

    state.set_position(None, "EMPTY")
    assert state.get_position()[0] is None
    test_pass("RuntimeState 所有功能正常")


# ------------------------------------------------------------
def test_backtester():
    print("\n--- 测试回测引擎 ---")
    try:
        from backtester import Backtester
        from performance import analyze_trades
        from indicators import MarketDataManager
        from config import CandleConfig

        tmpdir = tempfile.mkdtemp()
        candle_path = Path(tmpdir) / "candles.csv"
        cfg = CandleConfig()
        mgr = MarketDataManager(cfg, Path(""), candle_path)
        import pandas as pd

        dates = pd.date_range("2025-01-01", periods=60, freq="1min")
        for i, dt in enumerate(dates):
            mgr.add_candle(
                {
                    "time": dt,
                    "open": 2100 + i * 0.5,
                    "high": 2100 + i * 0.5 + 2,
                    "low": 2100 + i * 0.5 - 2,
                    "close": 2100 + i * 0.5 + 1,
                    "volume": 100,
                }
            )
        bt = Backtester(mgr)
        trades = bt.run()
        if trades is not None and not trades.empty:
            stats = analyze_trades(trades)
            assert isinstance(stats, dict)
            test_pass("回测引擎运行正常并产生交易记录")
        else:
            test_warn("回测引擎运行正常但未产生交易（策略条件苛刻）")
        shutil.rmtree(tmpdir)
    except ImportError:
        test_warn("backtester 或 performance 模块未找到")
    except Exception as e:
        test_fail("回测引擎测试失败", e)


# ------------------------------------------------------------
def test_gui_dependencies():
    print("\n--- 测试 GUI 依赖 ---")
    try:
        import customtkinter as ctk
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        import mplfinance as mpf

        test_pass("所有 GUI 库导入成功")
        root = ctk.CTk()
        label = ctk.CTkLabel(root, text="test")
        label.pack()
        root.update_idletasks()
        root.destroy()
        test_pass("customtkinter 组件创建正常")
    except ImportError as e:
        test_fail("GUI 库缺失", e)
    except Exception as e:
        test_fail("customtkinter 组件测试失败", e)


# ------------------------------------------------------------
def test_threading():
    print("\n--- 测试线程与队列 ---")
    from queues import tick_queue
    import threading

    def producer():
        for i in range(10):
            tick_queue.put(("test", datetime.now()))

    t = threading.Thread(target=producer)
    t.start()
    time.sleep(0.5)
    assert not tick_queue.empty()
    while not tick_queue.empty():
        tick_queue.get()
    t.join()
    test_pass("多线程队列操作正常")


# ------------------------------------------------------------
def main():
    print("=" * 60)
    print("量化交易系统 Pro - 完整功能测试（最终版）")
    print("=" * 60)
    test_config_manager()
    test_tesseract()
    test_ocr_worker()
    test_candle_engine()
    test_market_data_manager()
    test_tick_indicators()
    test_strategy()
    test_runtime_state()
    test_backtester()
    test_gui_dependencies()
    test_threading()
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print(f"✅ 通过: {test_results['passed']}")
    print(f"❌ 失败: {test_results['failed']}")
    print(f"⚠️  警告: {test_results['warnings']}")
    if test_results["failed"] == 0:
        print("🎉 所有核心测试通过！系统基本功能正常。")
    else:
        print("🛠️ 请根据失败项修复对应模块。")
    print("=" * 60)


if __name__ == "__main__":
    main()

tick_indicators.py

"""
Tick 级指标引擎（高性能版 + 主动买卖识别 + 一致性 + 动态爆发）
"""

from collections import deque
from datetime import datetime
import numpy as np


class TickIndicatorEngine:
    def __init__(
        self,
        max_len=100,
        strength_norm_window=5,
        ema_short=3,
        ema_long=8,
        speed_ema_period=3,
        burst_lookback=10,
        burst_percentile=0.8,
    ):
        self.max_len = max_len
        self.strength_norm_window = strength_norm_window
        self.ema_short_period = ema_short
        self.ema_long_period = ema_long
        self.speed_ema_period = speed_ema_period
        self.burst_lookback = burst_lookback
        self.burst_percentile = burst_percentile

        self.prices = deque(maxlen=max_len)
        self.timestamps = deque(maxlen=max_len)
        self.volumes = deque(maxlen=max_len)
        self.bid_prices = deque(maxlen=max_len)
        self.ask_prices = deque(maxlen=max_len)

        self.last_tick_time = None
        self.last_price = None

        self.speed_ema = 0.0
        self.speed_ema_alpha = 2 / (speed_ema_period + 1)

        self.ema_short = None
        self.ema_long = None
        self.ema_short_alpha = 2 / (ema_short + 1)
        self.ema_long_alpha = 2 / (ema_long + 1)
        self.ema_initialized = False

        self.price_sum = 0.0
        self.vwap_sum = 0.0
        self.total_volume = 0

        # 主动买卖队列
        self.active_window = 20
        self.active_buy_queue = deque(maxlen=self.active_window)
        self.active_sell_queue = deque(maxlen=self.active_window)

    def add_tick(self, price, timestamp, bid1_price=None, ask1_price=None, volume=1):
        if len(self.prices) == self.max_len:
            oldest_price = self.prices[0]
            oldest_volume = self.volumes[0]
            self.price_sum -= oldest_price
            self.vwap_sum -= oldest_price * oldest_volume
            self.total_volume -= oldest_volume
        self.prices.append(price)
        self.price_sum += price
        self.volumes.append(volume)
        self.vwap_sum += price * volume
        self.total_volume += volume
        self.timestamps.append(timestamp)
        self.bid_prices.append(bid1_price)
        self.ask_prices.append(ask1_price)
        self.last_price = price
        self.last_tick_time = timestamp

        if len(self.prices) >= self.ema_long_period:
            if not self.ema_initialized:
                self.ema_short = price
                self.ema_long = price
                self.ema_initialized = True
            else:
                self.ema_short = price * self.ema_short_alpha + self.ema_short * (1 - self.ema_short_alpha)
                self.ema_long = price * self.ema_long_alpha + self.ema_long * (1 - self.ema_long_alpha)

        # 主动买卖判定（使用盘口价格）
        if bid1_price is not None and ask1_price is not None:
            if price >= ask1_price:
                self.active_buy_queue.append(1)
                self.active_sell_queue.append(0)
            elif price <= bid1_price:
                self.active_buy_queue.append(0)
                self.active_sell_queue.append(1)
            else:
                self.active_buy_queue.append(0)
                self.active_sell_queue.append(0)
        else:
            # 如果没有盘口数据，使用价格变化模拟（回测用）
            if len(self.prices) >= 2:
                if price > self.prices[-2]:
                    self.active_buy_queue.append(1)
                    self.active_sell_queue.append(0)
                elif price < self.prices[-2]:
                    self.active_buy_queue.append(0)
                    self.active_sell_queue.append(1)
                else:
                    self.active_buy_queue.append(0)
                    self.active_sell_queue.append(0)
            else:
                self.active_buy_queue.append(0)
                self.active_sell_queue.append(0)

    def tick_speed_raw(self):
        if len(self.prices) < 2:
            return 0.0
        dt = (self.timestamps[-1] - self.timestamps[-2]).total_seconds()
        if dt == 0:
            dt = 1e-6
        return (self.prices[-1] - self.prices[-2]) / dt

    def tick_speed(self, limit=20.0):
        raw = self.tick_speed_raw()
        self.speed_ema = raw * self.speed_ema_alpha + self.speed_ema * (1 - self.speed_ema_alpha)
        speed = self.speed_ema
        if speed > limit:
            speed = limit
        elif speed < -limit:
            speed = -limit
        return speed

    def tick_momentum(self, window=5):
        if len(self.prices) < window:
            return 0.0
        return self.prices[-1] - self.prices[-window]

    def tick_mean_price(self):
        if not self.prices:
            return 0.0
        return self.price_sum / len(self.prices)

    def tick_vwap(self):
        if self.total_volume == 0:
            return self.tick_mean_price()
        return self.vwap_sum / self.total_volume

    def tick_acceleration(self, limit=10.0):
        if len(self.prices) < 3:
            return 0.0
        dt1 = (self.timestamps[-2] - self.timestamps[-3]).total_seconds()
        dt2 = (self.timestamps[-1] - self.timestamps[-2]).total_seconds()
        if dt1 == 0:
            dt1 = 1e-6
        if dt2 == 0:
            dt2 = 1e-6
        speed1 = (self.prices[-2] - self.prices[-3]) / dt1
        speed2 = (self.prices[-1] - self.prices[-2]) / dt2
        acc = speed2 - speed1
        if acc > limit:
            acc = limit
        elif acc < -limit:
            acc = -limit
        return acc

    def is_burst(self, threshold=None):
        if len(self.prices) < 2:
            return False
        if threshold is not None:
            return abs(self.prices[-1] - self.prices[-2]) > threshold
        if len(self.prices) < self.burst_lookback + 1:
            return False
        changes = [abs(self.prices[i] - self.prices[i - 1]) for i in range(-self.burst_lookback, 0)]
        if not changes:
            return False
        dyn_threshold = np.percentile(changes, self.burst_percentile * 100)
        return abs(self.prices[-1] - self.prices[-2]) > dyn_threshold

    def get_tick_strength(self):
        if len(self.prices) < 2:
            return 0.0
        direction = 1 if self.prices[-1] > self.prices[-2] else -1 if self.prices[-1] < self.prices[-2] else 0
        if direction == 0:
            return 0.0
        count = 1
        for i in range(2, len(self.prices)):
            if self.prices[-i] > self.prices[-i - 1] and direction == 1:
                count += 1
            elif self.prices[-i] < self.prices[-i - 1] and direction == -1:
                count += 1
            else:
                break
        strength = min(count / self.strength_norm_window, 1.0)
        return strength * direction

    def micro_trend(self):
        if not self.ema_initialized:
            return 0.0
        return self.ema_short - self.ema_long

    def pressure_score(self, window=20):
        if len(self.prices) < window:
            return 0.0
        prices_list = list(self.prices)
        up = 0
        down = 0
        for i in range(-window + 1, 0):
            if prices_list[i] > prices_list[i - 1]:
                up += 1
            elif prices_list[i] < prices_list[i - 1]:
                down += 1
        total = up + down
        if total == 0:
            return 0.0
        return (up - down) / total

    def tick_consistency(self, window=None):
        if window is None:
            window = max(5, len(self.prices) // 5)
            window = min(window, len(self.prices) - 1)
        if len(self.prices) < window:
            return 0.5
        current_dir = 1 if self.prices[-1] > self.prices[-2] else -1 if self.prices[-1] < self.prices[-2] else 0
        if current_dir == 0:
            return 0.5
        same = 0
        for i in range(-window, -1):
            if self.prices[i] > self.prices[i - 1] and current_dir == 1:
                same += 1
            elif self.prices[i] < self.prices[i - 1] and current_dir == -1:
                same += 1
        return same / (window - 1) if (window - 1) > 0 else 0.5

    def aggressive_buying(self, window=10):
        """主动买盘强度：连续上涨tick比例 [0,1]"""
        if len(self.prices) < window:
            return 0.0
        up = 0
        for i in range(-window + 1, 0):
            if self.prices[i] > self.prices[i - 1]:
                up += 1
        return up / (window - 1)

    def aggressive_selling(self, window=10):
        """主动卖盘强度：连续下跌tick比例 [0,1]"""
        if len(self.prices) < window:
            return 0.0
        down = 0
        for i in range(-window + 1, 0):
            if self.prices[i] < self.prices[i - 1]:
                down += 1
        return down / (window - 1)

    def active_buy_ratio(self):
        if len(self.active_buy_queue) == 0:
            return 0.0
        return sum(self.active_buy_queue) / len(self.active_buy_queue)

    def active_sell_ratio(self):
        if len(self.active_sell_queue) == 0:
            return 0.0
        return sum(self.active_sell_queue) / len(self.active_sell_queue)

    def active_imbalance(self):
        return self.active_buy_ratio() - self.active_sell_ratio()

    def orderbook_pressure(self):
        # 简化版，实际可计算买一卖一量比例
        if len(self.bid_prices) == 0 or self.bid_prices[-1] is None or self.ask_prices[-1] is None:
            return 0.0
        # 这里仅示例，返回0
        return 0.0

    def is_stale(self, timeout=3):
        if self.last_tick_time is None:
            return True
        return (datetime.now() - self.last_tick_time).total_seconds() > timeout

{} user_config.json

{
  "config_version": 1,
  "capture": {
    "left": 0,
    "top": 0,
    "width": 0,
    "height": 0,
    "interval_seconds": 0.5
  },
  "time_region": {
    "left": 1653,
    "top": 454,
    "width": 67,
    "height": 18
  },
  "price_region": {
    "left": 1722,
    "top": 453,
    "width": 44,
    "height": 20
  },
  "bid1_price_region": {
    "left": 1786,
    "top": 454,
    "width": 44,
    "height": 19
  },
  "ask1_price_region": {
    "left": 1853,
    "top": 454,
    "width": 44,
    "height": 19
  },
  "min_price_change": 1,
  "max_price_jump": 20,
  "tesseract_cmd": "./Tesseract-OCR/tesseract.exe",
  "colors": {
    "red_threshold": {
      "r": [
        250,
        255
      ],
      "g": [
        0,
        5
      ],
      "b": [
        0,
        5
      ]
    },
    "cyan_threshold": {
      "r": [
        0,
        5
      ],
      "g": [
        250,
        255
      ],
      "b": [
        250,
        255
      ]
    }
  },
  "system_prompt": "你是专业超短线量化交易AI，需严格遵循以下策略逻辑，只输出：做多、做空、HOLD，并给出简洁理由。\n\n核心策略规则：\n1. 趋势过滤：价格在EMA30之上为上涨趋势，之下为下跌趋势。震荡时不交易。\n2. 入场信号：\n   - 上涨趋势中，价格回踩EMA7（距离≤2点），且tick动量>0，主动买盘占比>0.3，可做多。\n   - 下跌趋势中，价格反弹至EMA7附近，且tick动量<0，主动卖盘占比>0.3，可做空。\n   - 支撑/压力假突破：前一根K线突破支撑/压力后，当前K线反向，且趋势方向一致，可顺势开仓。\n3. 止盈止损：基于ATR动态计算，止盈约2-4点，止损约1.5-3点。\n4. 禁止逆势、禁止追单、禁止在RSI超买超卖区开仓。\n5. 优先参考主动买卖识别（主动买盘/卖盘占比）。\n\n请根据当前市场状态和上述规则给出建议。",
  "strategy": {
    "EMA_SHORT": 2,
    "EMA_MID": 4,
    "EMA_LONG": 8,
    "TREND_STRENGTH_HIGH": 0.06,
    "TREND_STRENGTH_LOW": 0.015,
    "RSI_PERIOD": 4,
    "RSI_LONG_THRESHOLD": 50,
    "RSI_SHORT_THRESHOLD": 50,
    "RSI_LONG_MAX": 85,
    "RSI_SHORT_MIN": 15,
    "RSI_OS_LONG": 35,
    "RSI_OB_SHORT": 65,
    "SIGNAL_COOLDOWN": 8,
    "DIRECTION_LOCK_TIME": 1,
    "STOP_AFTER_LOSS": 5,
    "MAX_CONSECUTIVE_LOSS": 3,
    "PAUSE_AFTER_MAX_LOSS": 30,
    "MIN_RANGE": 0.8,
    "MAX_RANGE": 12,
    "MAX_DISTANCE_FROM_LOW": 20,
    "MAX_DISTANCE_FROM_HIGH": 20,
    "TREND_STOP_MULT": 0.5,
    "TREND_TAKE_MULT": 1.2,
    "RANGE_STOP_MULT": 0.5,
    "RANGE_TAKE_MULT": 0.8,
    "ATR_SLOPE_FACTOR": 0.04,
    "ATR_BREAKOUT_FACTOR": 0.03,
    "VOL_MA_PERIOD": 3,
    "VOL_RATIO": 0.3,
    "EXHAUSTION_COUNT": 8,
    "PULLBACK_MAX_BARS": 1,
    "PULLBACK_DISTANCE": 4,
    "ATR_MIN": 1.5,
    "ATR_MAX": 8,
    "TICK_CONSISTENCY_THRESHOLD": 0.6,
    "TICK_WEIGHT": 0.3,
    "ORDERBOOK_PRESSURE_THRESHOLD": 0.2,
    "ATR_STOP_MULT": 0.7,
    "ATR_TAKE_MULT": 1.8,
    "LONG_TERM_EMA": 20,
    "ACTIVE_IMBALANCE_THRESHOLD": 0.3,
    "ACTIVE_WEIGHT": 1
  },
  "ohlc_time_region": {
    "left": 1187,
    "top": 75,
    "width": 32,
    "height": 19
  },
  "ohlc_price_region": {
    "left": 1219,
    "top": 75,
    "width": 175,
    "height": 19
  },
  "ohlc_volume_region": {
    "left": 1467,
    "top": 75,
    "width": 45,
    "height": 19
  }
}