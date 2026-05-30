# 可直接复制的完整版（单文件可运行版）

> 你当前仓库里没有 27 个分文件源码，因此这里给你一个**可直接复制运行**的“单文件整合版”。
> 文件名建议：`trading_system_full.py`

```python
"""
整合版量化信号系统（可运行骨架版）
- 统一 timestamp 字段
- 分离 signal_queue_exec / signal_queue_ui
- 精确异常处理
- 线程安全 RuntimeState
- 跨平台声音通知降级
"""
from __future__ import annotations

import copy
import json
import logging
import os
import platform
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

# ========================= logging =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("trading_system")

# ========================= queues =========================
tick_queue: queue.Queue = queue.Queue(maxsize=5000)
candle_queue: queue.Queue = queue.Queue(maxsize=500)
signal_queue_exec: queue.Queue = queue.Queue(maxsize=50)
signal_queue_ui: queue.Queue = queue.Queue(maxsize=100)


def safe_put(q: queue.Queue, item: Any, timeout: float = 0.2) -> bool:
    try:
        q.put(item, timeout=timeout)
        return True
    except queue.Full:
        logger.warning("Queue full, dropped item: %s", type(item))
        return False

# ========================= config =========================
@dataclass
class CandleConfig:
    interval_seconds: int = 60
    max_rows: int = 2000

@dataclass
class AppConfig:
    tick_csv: Path = Path("project/data/ticks.csv")
    candle_csv: Path = Path("project/data/candles_1m.csv")

DEFAULT_CONFIG = {
    "capture": {"left": 0, "top": 0, "width": 100, "height": 30, "interval_seconds": 1.0},
    "strategy": {"risk_reward_ratio": 1.5},
    "system_prompt": "你是专业量化交易分析AI。",
}

class ConfigManager:
    def __init__(self, path: str = "user_config.json"):
        self.path = path
        self.config = self.load()

    def load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.exception("Config broken, fallback default")
        return copy.deepcopy(DEFAULT_CONFIG)

    def save(self) -> None:
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

# ========================= state =========================
class RuntimeState:
    def __init__(self):
        self._lock = threading.RLock()
        self.latest_price: Optional[float] = None
        self.base_price: Optional[float] = None
        self.position: Optional[Dict[str, Any]] = None
        self.current_pos: str = "EMPTY"
        self.analysis_mode: int = 1
        self.trade_log: list = []
        self.price_updated = threading.Event()
        self.daily_pnl = 0.0
        self.max_daily_loss = -30.0
        self.last_pnl_reset_date = date.today()

    def update_price(self, price: float):
        with self._lock:
            self.latest_price = price
            self.price_updated.set()

    def get_price(self) -> Optional[float]:
        with self._lock:
            return self.latest_price

    def set_position(self, pos: Optional[Dict[str, Any]], current_pos: str):
        with self._lock:
            if pos is not None:
                pos = copy.copy(pos)
                pos.setdefault("entry_time", time.time())
                pos.setdefault("trade_id", str(uuid.uuid4()))
                pos["closing"] = False
            self.position = pos
            self.current_pos = current_pos

    def get_position(self) -> Tuple[Optional[Dict[str, Any]], str]:
        with self._lock:
            return copy.copy(self.position), self.current_pos

    def update_daily_pnl(self, pnl: float):
        with self._lock:
            if date.today() != self.last_pnl_reset_date:
                self.daily_pnl = 0.0
                self.last_pnl_reset_date = date.today()
            self.daily_pnl += pnl

# ========================= market data =========================
class MarketDataManager:
    def __init__(self, cfg: CandleConfig, tick_path: Path, candle_path: Path):
        self.candle_cfg = cfg
        self.tick_path = tick_path
        self.candle_path = candle_path
        self.ticks = pd.DataFrame(columns=["timestamp", "price", "volume"])
        self.candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    def add_candle(self, candle: dict) -> None:
        ts = candle.get("timestamp", candle.get("time"))
        row = {
            "timestamp": pd.to_datetime(ts, utc=True),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle.get("volume", 0)),
        }
        self.candles = pd.concat([self.candles, pd.DataFrame([row])], ignore_index=True)
        if len(self.candles) > self.candle_cfg.max_rows:
            self.candles = self.candles.iloc[-self.candle_cfg.max_rows:].reset_index(drop=True)

# ========================= strategy =========================
def local_trade_rule(candles: pd.DataFrame, state: RuntimeState) -> Optional[dict]:
    if len(candles) < 15:
        return None
    c = candles.iloc[-1]
    prev = candles.iloc[-2]
    if c["close"] > prev["high"]:
        entry = float(c["close"])
        stop = float(prev["low"])
        take = entry + (entry - stop) * 1.5
        return {"side": "LONG", "entry": entry, "stop": stop, "take": take, "reason": "breakout_up"}
    if c["close"] < prev["low"]:
        entry = float(c["close"])
        stop = float(prev["high"])
        take = entry - (stop - entry) * 1.5
        return {"side": "SHORT", "entry": entry, "stop": stop, "take": take, "reason": "breakout_down"}
    return None

# ========================= candle engine =========================
def floor_time(dt: datetime, interval_seconds: int) -> datetime:
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % interval_seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)

class CandleEngine:
    def __init__(self, interval_seconds: int = 60):
        self.interval_seconds = interval_seconds
        self.current_candle = None
        self.current_bucket = None

    def update_tick(self, price: float, tick_time: datetime):
        bucket = floor_time(tick_time, self.interval_seconds)
        if self.current_candle is None:
            self.current_bucket = bucket
            self.current_candle = {"timestamp": bucket, "open": price, "high": price, "low": price, "close": price, "volume": 0.0}
            return None
        if bucket == self.current_bucket:
            self.current_candle["high"] = max(self.current_candle["high"], price)
            self.current_candle["low"] = min(self.current_candle["low"], price)
            self.current_candle["close"] = price
            return None
        finished = self.current_candle.copy()
        self.current_bucket = bucket
        self.current_candle = {"timestamp": bucket, "open": price, "high": price, "low": price, "close": price, "volume": 0.0}
        return finished

    def flush(self):
        return None if self.current_candle is None else self.current_candle.copy()

# ========================= notifier =========================
_last_beep_ts = 0.0

def play_sound(freq: int, dur: int):
    global _last_beep_ts
    now = time.time()
    if now - _last_beep_ts < 0.3:
        return
    _last_beep_ts = now
    if platform.system().lower().startswith("win"):
        try:
            import winsound
            threading.Thread(target=lambda: winsound.Beep(freq, dur), daemon=True).start()
            return
        except Exception:
            logger.exception("winsound failed")
    logger.info("BEEP %sHz %sms", freq, dur)

# ========================= workers =========================
def run_candle_worker(state: RuntimeState, stop_event: threading.Event, cfg: CandleConfig):
    engine = CandleEngine(interval_seconds=cfg.interval_seconds)
    while not stop_event.is_set():
        try:
            price, tick_time = tick_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            finished = engine.update_tick(float(price), tick_time)
            if finished is not None:
                state.base_price = finished["close"]
                safe_put(candle_queue, finished)
        finally:
            tick_queue.task_done()


def run_analysis_worker(state: RuntimeState, stop_event: threading.Event, data_mgr: MarketDataManager):
    while not stop_event.is_set():
        try:
            candle = candle_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            if candle is not None:
                data_mgr.add_candle(candle)
                state.base_price = float(candle["close"])
            if len(data_mgr.candles) < 15:
                continue
            signal = local_trade_rule(data_mgr.candles, state)
            if signal:
                safe_put(signal_queue_exec, signal)
                safe_put(signal_queue_ui, copy.deepcopy(signal))
        except Exception:
            logger.exception("analysis worker error")
        finally:
            candle_queue.task_done()


def run_execution_worker(state: RuntimeState, stop_event: threading.Event):
    while not stop_event.is_set():
        try:
            signal = signal_queue_exec.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            pos, _ = state.get_position()
            if pos is not None:
                continue
            state.set_position({
                "side": signal["side"], "entry": signal["entry"], "stop": signal["stop"],
                "take": signal["take"], "initial_risk": abs(signal["entry"] - signal["stop"]),
            }, signal["side"])
            play_sound(1200, 150)
            logger.info("Open %s @ %s", signal["side"], signal["entry"])
        finally:
            signal_queue_exec.task_done()


def run_risk_worker(state: RuntimeState, stop_event: threading.Event):
    while not stop_event.is_set():
        state.price_updated.wait(timeout=0.1)
        state.price_updated.clear()
        pos, _ = state.get_position()
        if not pos or pos.get("closing"):
            continue
        price = state.get_price()
        if price is None:
            continue
        side, entry, stop, take = pos["side"], pos["entry"], pos["stop"], pos["take"]
        hit = (side == "LONG" and (price <= stop or price >= take)) or (side == "SHORT" and (price >= stop or price <= take))
        if not hit:
            continue
        pos["closing"] = True
        pnl = (price - entry) * (1 if side == "LONG" else -1)
        state.update_daily_pnl(pnl)
        state.set_position(None, "EMPTY")
        play_sound(500 if pnl < 0 else 1500, 220)
        logger.info("Close %s @ %s pnl=%.2f", side, price, pnl)

# ========================= demo feeder =========================
def run_demo_feeder(state: RuntimeState, stop_event: threading.Event):
    px = 100.0
    direction = 1
    while not stop_event.is_set():
        px += direction * 0.8
        if px > 110:
            direction = -1
        elif px < 90:
            direction = 1
        state.update_price(px)
        safe_put(tick_queue, (px, datetime.now(timezone.utc)))
        time.sleep(1)


def main():
    state = RuntimeState()
    stop_event = threading.Event()
    ccfg = CandleConfig()
    acfg = AppConfig()
    data_mgr = MarketDataManager(ccfg, acfg.tick_csv, acfg.candle_csv)

    threads = [
        threading.Thread(target=run_demo_feeder, args=(state, stop_event), daemon=True),
        threading.Thread(target=run_candle_worker, args=(state, stop_event, ccfg), daemon=True),
        threading.Thread(target=run_analysis_worker, args=(state, stop_event, data_mgr), daemon=True),
        threading.Thread(target=run_execution_worker, args=(state, stop_event), daemon=True),
        threading.Thread(target=run_risk_worker, args=(state, stop_event), daemon=True),
    ]
    for t in threads:
        t.start()

    logger.info("System started. Ctrl+C exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
        logger.info("System stopped")


if __name__ == "__main__":
    main()
```

## 使用方法

1. 新建 `trading_system_full.py`，粘贴上面全部代码。
2. 安装依赖：
   ```bash
   pip install pandas
   ```
3. 运行：
   ```bash
   python trading_system_full.py
   ```

如果你要，我下一条可以直接给你**27个分文件版本**（每个文件单独代码块，可直接覆盖原项目文件）。
