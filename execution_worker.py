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