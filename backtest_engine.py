"""
策略回测引擎
"""

import pandas as pd
from strategy import local_trade_rule
from runtime_state import RuntimeState
from performance import analyze_trades


class BacktestEngine:

    def __init__(self, data: pd.DataFrame):

        self.df = data.copy()

        self.state = RuntimeState()

        self.trades = []

    def run(self):

        if len(self.df) < 50:
            print("K线数量不足")
            return {}

        print("开始回测...")

        for i in range(30, len(self.df)):

            current_df = self.df.iloc[:i].copy()

            signal = local_trade_rule(
                current_df,
                self.state
            )

            if signal:

                trade = self._simulate_trade(
                    signal,
                    i
                )

                if trade:
                    self.trades.append(trade)

        result = analyze_trades(
            pd.DataFrame(self.trades)
        )

        print("回测完成")
        print(result)

        return result

    def _simulate_trade(self, signal, start_index):

        side = signal["side"]

        entry = signal["entry"]

        stop = signal["stop"]

        take = signal["take"]

        future = self.df.iloc[start_index:start_index + 20]

        for _, row in future.iterrows():

            high = row["high"]

            low = row["low"]

            if side == "LONG":

                if low <= stop:
                    pnl = stop - entry

                    return {
                        "side": side,
                        "entry": entry,
                        "exit": stop,
                        "pnl": pnl,
                        "reason": "止损"
                    }

                if high >= take:
                    pnl = take - entry

                    return {
                        "side": side,
                        "entry": entry,
                        "exit": take,
                        "pnl": pnl,
                        "reason": "止盈"
                    }

            elif side == "SHORT":

                if high >= stop:
                    pnl = entry - stop

                    return {
                        "side": side,
                        "entry": entry,
                        "exit": stop,
                        "pnl": pnl,
                        "reason": "止损"
                    }

                if low <= take:
                    pnl = entry - take

                    return {
                        "side": side,
                        "entry": entry,
                        "exit": take,
                        "pnl": pnl,
                        "reason": "止盈"
                    }

        return None