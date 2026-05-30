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
