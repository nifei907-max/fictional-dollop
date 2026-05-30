from __future__ import annotations
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import pandas as pd
from config import CandleConfig


@dataclass
class MarketDataManager:
    candle_cfg: CandleConfig
    tick_path: Path
    candle_path: Path

    def __post_init__(self) -> None:
        self.ticks = pd.DataFrame(columns=["timestamp", "price", "volume"])
        self.candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        self._data_lock = threading.RLock()

    def add_tick(self, timestamp: datetime, price: float, volume: float = 0.0) -> None:
        self.ticks.loc[len(self.ticks)] = [timestamp, price, volume]
        if len(self.ticks) > self.candle_cfg.max_rows:
            self.ticks = self.ticks.iloc[-self.candle_cfg.max_rows :].reset_index(drop=True)

    def build_candles(self) -> pd.DataFrame:
        if self.ticks.empty:
            return self.candles
        df = self.ticks.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        ohlc = df["price"].resample("1min").ohlc()
        vol = df["volume"].resample("1min").sum()
        merged = ohlc.join(vol.rename("volume")).dropna().reset_index()
        merged.rename(columns={"timestamp": "timestamp"}, inplace=True)
        self.candles = merged.tail(self.candle_cfg.max_rows).copy()
        return self.candles

    def add_candle(self, candle: dict) -> None:
        with self._data_lock:
            row = {
                "timestamp": pd.to_datetime(candle["time"]),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle.get("volume", 0)),
            }
            if self.candles.empty:
                self.candles = pd.DataFrame([row])
            else:
                self.candles = pd.concat([self.candles, pd.DataFrame([row])], ignore_index=True)
            if len(self.candles) > self.candle_cfg.max_rows:
                self.candles = self.candles.iloc[-self.candle_cfg.max_rows :].reset_index(drop=True)

    def latest_row(self) -> Optional[pd.Series]:
        if self.candles.empty:
            return None
        return self.candles.iloc[-1]

    def persist(self) -> None:
        self.tick_path.parent.mkdir(parents=True, exist_ok=True)
        self.candle_path.parent.mkdir(parents=True, exist_ok=True)
        self.ticks.to_csv(self.tick_path, index=False)
        self.candles.to_csv(self.candle_path, index=False)
