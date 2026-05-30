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
