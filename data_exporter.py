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