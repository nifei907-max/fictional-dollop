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