"""本地兜底规则引擎。

当 DeepSeek 接口异常或返回无效数据时，给出保守的本地信号判断，
保证系统稳定可运行（优先 HOLD）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class RuleEngine:
    rsi_long_threshold: float = 55.0
    rsi_short_threshold: float = 45.0

    def analyze(self, candles: pd.DataFrame) -> dict[str, Any]:
        latest = candles.iloc[-1]

        ema20 = float(latest.get("ema20", 0.0))
        ema50 = float(latest.get("ema50", 0.0))
        rsi = float(latest.get("rsi", 50.0))
        hist = float(latest.get("macd_hist", 0.0))
        close = float(latest.get("close", 0.0))
        atr = float(latest.get("atr", 0.0))

        signal = "HOLD"
        reason = "趋势或动能不明确，按风控规则观望。"
        risk_level = "LOW"

        if ema20 > ema50 and rsi >= self.rsi_long_threshold and hist > 0:
            signal = "LONG"
            reason = "EMA20 上穿 EMA50 且 RSI 与 MACD 同向，趋势偏多。"
            risk_level = "MEDIUM"
        elif ema20 < ema50 and rsi <= self.rsi_short_threshold and hist < 0:
            signal = "SHORT"
            reason = "EMA20 下穿 EMA50 且 RSI 与 MACD 同向，趋势偏空。"
            risk_level = "MEDIUM"

        entry = close
        stop_loss = max(close - 1.5 * atr, 0) if signal == "LONG" else close + 1.5 * atr
        take_profit = close + 2.0 * atr if signal == "LONG" else max(close - 2.0 * atr, 0)
        if signal == "HOLD":
            stop_loss = close
            take_profit = close

        return {
            "signal": signal,
            "confidence": 60 if signal != "HOLD" else 40,
            "entry": round(entry, 6),
            "stop_loss": round(stop_loss, 6),
            "take_profit": round(take_profit, 6),
            "risk_level": risk_level,
            "reason": reason,
        }
