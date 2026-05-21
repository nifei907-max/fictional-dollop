"""
纯行情信号提醒工具（仅策略分析与播报，不含任何下单功能）

特性：
1. 5/10 均线金叉死叉（可配置）
2. 1分钟行情轮询抓取
3. 持仓成本记录 + 动态止盈止损提醒
4. Tkinter 简洁实时界面
5. 买入/卖出/止盈/止损醒目弹窗
6. 无交易接口、无自动挂单
7. 参数易改
8. 异常重连，支持长时间运行
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import requests
import tkinter as tk


@dataclass
class Config:
    # ===== 可自定义参数 =====
    symbol: str = "HUAZHONG_JIUTONG_SPOT"
    short_ma: int = 5
    long_ma: int = 10
    take_profit_pct: float = 0.008   # 0.8%
    stop_loss_pct: float = 0.005     # 0.5%
    poll_interval_sec: int = 10      # 轮询间隔（建议 <= 60）
    max_prices_buffer: int = 200

    # 1分钟行情接口（示例，占位；请替换为你的可用行情源）
    # 约定返回 JSON: {"price": 123.45, "ts": "2026-05-21 12:34:00"}
    market_api_url: str = "http://127.0.0.1:8000/quote_1m"
    request_timeout_sec: int = 5


@dataclass
class PositionState:
    side: Optional[str] = None   # "LONG" / "SHORT" / None
    entry_price: Optional[float] = None
    entry_time: Optional[str] = None

    def clear(self) -> None:
        self.side = None
        self.entry_price = None
        self.entry_time = None


class MarketClient:
    """行情抓取客户端：只读数据，不执行任何交易。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def fetch_latest_price(self) -> float:
        r = requests.get(self.cfg.market_api_url, timeout=self.cfg.request_timeout_sec)
        r.raise_for_status()
        data = r.json()
        if "price" not in data:
            raise ValueError("行情接口缺少 price 字段")
        return float(data["price"])


class SignalEngine:
    """均线信号与持仓风控计算。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.prices: List[float] = []
        self.position = PositionState()

    def _ma(self, n: int) -> Optional[float]:
        if len(self.prices) < n:
            return None
        return sum(self.prices[-n:]) / n

    def _prev_ma(self, n: int) -> Optional[float]:
        if len(self.prices) < n + 1:
            return None
        return sum(self.prices[-n - 1:-1]) / n

    def on_new_price(self, price: float) -> dict:
        self.prices.append(price)
        if len(self.prices) > self.cfg.max_prices_buffer:
            self.prices = self.prices[-self.cfg.max_prices_buffer :]

        short_ma = self._ma(self.cfg.short_ma)
        long_ma = self._ma(self.cfg.long_ma)
        prev_short_ma = self._prev_ma(self.cfg.short_ma)
        prev_long_ma = self._prev_ma(self.cfg.long_ma)

        signal = "等待数据"
        event = None

        # 无未来函数：只用当前和上一根已完成数据
        if None not in (short_ma, long_ma, prev_short_ma, prev_long_ma):
            golden_cross = prev_short_ma <= prev_long_ma and short_ma > long_ma
            dead_cross = prev_short_ma >= prev_long_ma and short_ma < long_ma

            if golden_cross:
                signal = "金叉 → 做多提示"
                event = "BUY"
                self.position.side = "LONG"
                self.position.entry_price = price
                self.position.entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            elif dead_cross:
                signal = "死叉 → 做空提示"
                event = "SELL"
                self.position.side = "SHORT"
                self.position.entry_price = price
                self.position.entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            else:
                signal = "持仓观察"

        risk_event, risk_text = self._check_take_profit_stop_loss(price)
        if risk_event:
            event = risk_event
            signal = risk_text

        return {
            "price": price,
            "short_ma": short_ma,
            "long_ma": long_ma,
            "signal": signal,
            "event": event,
            "position": self.position,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _check_take_profit_stop_loss(self, price: float) -> tuple[Optional[str], str]:
        p = self.position
        if p.side is None or p.entry_price is None:
            return None, ""

        entry = p.entry_price

        if p.side == "LONG":
            pnl = (price - entry) / entry
            if pnl >= self.cfg.take_profit_pct:
                self.position.clear()
                return "TP", f"多单止盈提醒（+{pnl:.2%}）"
            if pnl <= -self.cfg.stop_loss_pct:
                self.position.clear()
                return "SL", f"多单止损提醒（{pnl:.2%}）"

        if p.side == "SHORT":
            pnl = (entry - price) / entry
            if pnl >= self.cfg.take_profit_pct:
                self.position.clear()
                return "TP", f"空单止盈提醒（+{pnl:.2%}）"
            if pnl <= -self.cfg.stop_loss_pct:
                self.position.clear()
                return "SL", f"空单止损提醒（{pnl:.2%}）"

        return None, ""


class SignalApp:
    def __init__(self, root: tk.Tk, cfg: Config):
        self.root = root
        self.cfg = cfg
        self.client = MarketClient(cfg)
        self.engine = SignalEngine(cfg)

        self.root.title("1分钟短线信号提醒（仅分析，不下单）")
        self.root.geometry("650x360")

        self.running = True
        self.reconnect_wait = 2

        self.price_var = tk.StringVar(value="--")
        self.ma_var = tk.StringVar(value="MA5: -- / MA10: --")
        self.signal_var = tk.StringVar(value="等待启动")
        self.position_var = tk.StringVar(value="空仓")
        self.time_var = tk.StringVar(value="--")
        self.status_var = tk.StringVar(value="状态：初始化")

        self._build_ui()
        self._start_worker()

    def _build_ui(self) -> None:
        title = tk.Label(self.root, text="华中九通现货 1分钟信号雷达", font=("Microsoft YaHei", 16, "bold"))
        title.pack(pady=10)

        frame = tk.Frame(self.root)
        frame.pack(padx=16, pady=8, fill="x")

        self._row(frame, "当前价格", self.price_var)
        self._row(frame, "均线数值", self.ma_var)
        self._row(frame, "交易信号", self.signal_var)
        self._row(frame, "持仓状态", self.position_var)
        self._row(frame, "更新时间", self.time_var)

        status_label = tk.Label(self.root, textvariable=self.status_var, fg="gray")
        status_label.pack(side="bottom", pady=10)

        note = tk.Label(
            self.root,
            text="仅做策略提醒：不连接交易接口、不自动下单",
            fg="red",
            font=("Microsoft YaHei", 10, "bold"),
        )
        note.pack(side="bottom", pady=5)

    def _row(self, parent: tk.Frame, name: str, var: tk.StringVar) -> None:
        row = tk.Frame(parent)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=f"{name}：", width=10, anchor="w", font=("Microsoft YaHei", 11)).pack(side="left")
        tk.Label(row, textvariable=var, anchor="w", font=("Consolas", 11)).pack(side="left")

    def _start_worker(self) -> None:
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self) -> None:
        while self.running:
            try:
                price = self.client.fetch_latest_price()
                result = self.engine.on_new_price(price)
                self.reconnect_wait = 2
                self.root.after(0, self._update_ui, result)
                time.sleep(self.cfg.poll_interval_sec)
            except Exception as e:  # 异常重连机制
                msg = f"数据异常：{e}，{self.reconnect_wait}s 后重连"
                self.root.after(0, self.status_var.set, msg)
                time.sleep(self.reconnect_wait)
                self.reconnect_wait = min(self.reconnect_wait * 2, 60)

    def _update_ui(self, result: dict) -> None:
        price = result["price"]
        short_ma = result["short_ma"]
        long_ma = result["long_ma"]
        signal = result["signal"]
        event = result["event"]
        pos = result["position"]
        ts = result["time"]

        self.price_var.set(f"{price:.4f}")
        if short_ma is None or long_ma is None:
            self.ma_var.set("均线数据不足")
        else:
            self.ma_var.set(f"MA{self.cfg.short_ma}: {short_ma:.4f} / MA{self.cfg.long_ma}: {long_ma:.4f}")

        self.signal_var.set(signal)
        self.time_var.set(ts)

        if pos.side and pos.entry_price:
            self.position_var.set(f"{pos.side} @ {pos.entry_price:.4f} ({pos.entry_time})")
        else:
            self.position_var.set("空仓")

        self.status_var.set("状态：运行中")

        if event in {"BUY", "SELL", "TP", "SL"}:
            color_map = {
                "BUY": "green",
                "SELL": "blue",
                "TP": "purple",
                "SL": "red",
            }
            self._popup_alert(event, signal, color_map[event])

    def _popup_alert(self, title: str, text: str, color: str) -> None:
        # Tkinter 默认 messagebox 不支持字体颜色，使用 Toplevel 实现醒目提醒
        top = tk.Toplevel(self.root)
        top.title(f"信号提醒：{title}")
        top.geometry("420x180")
        top.attributes("-topmost", True)

        tk.Label(top, text=title, fg=color, font=("Microsoft YaHei", 20, "bold")).pack(pady=15)
        tk.Label(top, text=text, font=("Microsoft YaHei", 12)).pack(pady=8)
        tk.Button(top, text="知道了", command=top.destroy, width=12).pack(pady=15)

    def stop(self) -> None:
        self.running = False


def main() -> None:
    cfg = Config()
    root = tk.Tk()
    app = SignalApp(root, cfg)

    def on_close():
        app.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
