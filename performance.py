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
