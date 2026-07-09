"""数据与技术指标模块。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange

from config import CandleConfig


@dataclass
class MarketDataManager:
    candle_cfg: CandleConfig
    tick_path: Path
    candle_path: Path

    def __post_init__(self) -> None:
        self.ticks = pd.DataFrame(columns=["timestamp", "price", "volume"])
        self.candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    def add_tick(self, timestamp: datetime, price: float, volume: float = 0.0) -> None:
        self.ticks.loc[len(self.ticks)] = [timestamp, price, volume]
        if len(self.ticks) > self.candle_cfg.max_rows:
            self.ticks = self.ticks.iloc[-self.candle_cfg.max_rows :].reset_index(drop=True)

    def build_candles(self) -> pd.DataFrame:
        if self.ticks.empty:
            return self.candles
        df = self.ticks.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
        ohlc = df["price"].resample("1min").ohlc()
        vol = df["volume"].resample("1min").sum()
        merged = ohlc.join(vol.rename("volume")).dropna().reset_index()
        merged.rename(columns={"timestamp": "timestamp"}, inplace=True)
        self.candles = merged.tail(self.candle_cfg.max_rows).copy()
        return self.candles

    def compute_indicators(self) -> pd.DataFrame:
        if len(self.candles) < 60:
            return self.candles
        df = self.candles.copy()
        df["ema20"] = EMAIndicator(df["close"], window=20).ema_indicator()
        df["ema50"] = EMAIndicator(df["close"], window=50).ema_indicator()
        df["rsi"] = RSIIndicator(df["close"], window=14).rsi()

        macd = MACD(df["close"], window_fast=12, window_slow=26, window_sign=9)
        df["macd_dif"] = macd.macd()
        df["macd_dea"] = macd.macd_signal()
        df["macd_hist"] = macd.macd_diff()

        atr = AverageTrueRange(df["high"], df["low"], df["close"], window=14)
        df["atr"] = atr.average_true_range()
        self.candles = df
        return df

    def latest_row(self) -> Optional[pd.Series]:
        if self.candles.empty:
            return None
        return self.candles.iloc[-1]

    def persist(self) -> None:
        self.tick_path.parent.mkdir(parents=True, exist_ok=True)
        self.candle_path.parent.mkdir(parents=True, exist_ok=True)
        self.ticks.to_csv(self.tick_path, index=False)
        self.candles.to_csv(self.candle_path, index=False)
