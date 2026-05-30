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
