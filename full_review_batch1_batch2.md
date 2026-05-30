# 量化交易系统代码审查与优化版（第一批+第二批）

## 关键统一改造

1. **统一 K 线时间键名**：全项目统一 `timestamp`，废弃 `time`。
2. **禁用裸 `except:`**：仅捕获可预期异常，如 `queue.Empty`、`ValueError`、`requests.RequestException`。
3. **线程安全**：跨线程共享状态通过 `RuntimeState` 加锁接口访问。
4. **可测试性**：去除 `analysis_worker` 的全局 `data_mgr`，改为参数注入。
5. **可观测性**：用 `logging` 代替 `print`。
6. **配置可靠性**：`DEFAULT_CONFIG` 深拷贝，JSON 原子写入，损坏配置回退并告警。

---

## 优化后的关键代码（可直接替换）

### analysis_worker.py（优化版）

```python
"""分析线程：从 candle_queue 取 K 线，存盘，计算指标，产生信号入 signal_queue"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

from queues import candle_queue, signal_queue
from runtime_state import RuntimeState
from indicators import MarketDataManager
from strategy import local_trade_rule, run_ai_analysis

logger = logging.getLogger(__name__)


def run_analysis_worker(
    state: RuntimeState,
    stop_event: threading.Event,
    data_mgr: MarketDataManager,
    min_bars: int = 15,
) -> None:
    while not stop_event.is_set():
        try:
            candle = candle_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        try:
            if candle is not None:
                data_mgr.add_candle(candle)
                state.base_price = float(candle["close"])

            if len(data_mgr.candles) < min_bars:
                continue

            if state.analysis_mode == 0:
                signal = run_ai_analysis(data_mgr.candles, state)
            else:
                signal = local_trade_rule(data_mgr.candles, state)

            if signal is not None:
                signal_queue.put(signal)
            else:
                logger.debug("No valid signal for current bar")
        except Exception:
            logger.exception("analysis_worker failed on candle=%s", candle)
        finally:
            candle_queue.task_done()
```

### candle_engine.py（优化版）

```python
"""tick 驱动 K 线引擎（支持任意秒级周期）"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


def floor_time(dt: datetime, interval_seconds: int) -> datetime:
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % interval_seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)


@dataclass
class CandleEngine:
    interval_seconds: int = 60

    def __post_init__(self) -> None:
        self.current_candle = None
        self.current_bucket = None

    def update_tick(self, price: float, tick_time: datetime):
        bucket = floor_time(tick_time, self.interval_seconds)

        if self.current_candle is None:
            self.current_bucket = bucket
            self.current_candle = {
                "timestamp": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
            }
            return None

        if bucket == self.current_bucket:
            self.current_candle["high"] = max(self.current_candle["high"], price)
            self.current_candle["low"] = min(self.current_candle["low"], price)
            self.current_candle["close"] = price
            return None

        finished = self.current_candle.copy()
        self.current_bucket = bucket
        self.current_candle = {
            "timestamp": bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0.0,
        }
        return finished

    def flush(self):
        """返回未封口 K 线，供停机时写入。"""
        return None if self.current_candle is None else self.current_candle.copy()
```

### candle_worker.py（优化版）

```python
"""K线线程：从 tick_queue 取 tick，用 CandleEngine 生成 OHLC，放入 candle_queue"""
from __future__ import annotations

import queue
import threading

from candle_engine import CandleEngine
from config import CandleConfig
from queues import candle_queue, tick_queue
from runtime_state import RuntimeState


def run_candle_worker(state: RuntimeState, stop_event: threading.Event):
    cfg = CandleConfig()
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
                candle_queue.put(finished)
        finally:
            tick_queue.task_done()

    tail = engine.flush()
    if tail is not None:
        candle_queue.put(tail)
```

### backtester.py（核心修复）

- 开仓条件应为 `signal and pos is None`（空仓开仓）。
- 建议将成交模型抽为函数，明确“同根止盈止损优先级”。

### config_manager.py（关键修复）

- `DEFAULT_CONFIG.copy()` 改为 `copy.deepcopy(DEFAULT_CONFIG)`。
- save 用临时文件 + `os.replace`。

### deepseek_client.py（健壮性）

- 仅捕获 `requests.RequestException` 与响应结构错误。
- API key 为空时直接抛错，避免误请求。

### main_gui.py（结构修复）

- `signal_queue` 被 `execution_worker` 与 `signal_monitor` 同时消费，会“抢消息”。
  建议：
  - 方案 A：在 `execution_worker` 执行后，将结果写 `gui_queue`；
  - 方案 B：拆分为 `signal_queue_exec` 与 `signal_queue_gui`。

---

## 高优先级缺陷清单（必须先修）

1. `signal_queue` 双消费者竞争导致 GUI 丢信号。
2. `analysis_worker`、`candle_worker`、`execution_worker` 的裸异常吞错。
3. `time` / `timestamp` 混用导致 DataFrame 字段不一致。
4. `Backtester` 开仓条件疑似写反。
5. 配置浅拷贝导致默认配置被运行时污染。

---

## 统一命名约定（建议）

- K线 dict: `timestamp/open/high/low/close/volume`
- side: `LONG/SHORT/EMPTY`
- 策略模式: `ai/local`
- 时间统一 `timezone.utc`

---

## 下一步

你发第三批后，我会把以上优化合并成：
1. **逐文件最终版代码**；
2. **迁移说明（旧字段兼容）**；
3. **最小回归测试清单（线程、回测、GUI、OCR）**。
