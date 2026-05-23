"""策略拼装模块：组织提示词并生成分析请求。"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd


@dataclass
class StrategyBuilder:
    """将行情与指标拼接成 DeepSeek 用户提示词。"""

    def build_prompt(self, candles: pd.DataFrame) -> str:
        latest = candles.iloc[-1]
        recent = candles.tail(20)

        support = float(recent["low"].min())
        resistance = float(recent["high"].max())
        volume = float(recent["volume"].sum())

        candles_json = recent.to_dict(orient="records")

        return f"""当前市场数据：

价格: {latest['close']}

最近20根K线:
{json.dumps(candles_json, ensure_ascii=False)}

指标数据：

EMA20: {latest.get('ema20', 0)}
EMA50: {latest.get('ema50', 0)}

RSI: {latest.get('rsi', 0)}

MACD:
- DIF: {latest.get('macd_dif', 0)}
- DEA: {latest.get('macd_dea', 0)}
- HIST: {latest.get('macd_hist', 0)}

ATR: {latest.get('atr', 0)}

成交量:
{volume}

支撑位:
{support}

压力位:
{resistance}

请按以下步骤分析：

1. 判断趋势
2. 判断多空强弱
3. 判断是否突破
4. 判断风险
5. 最终给出交易建议

如果信号不明确，必须返回 HOLD。
最终只返回JSON。"""
