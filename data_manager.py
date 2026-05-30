"""
MarketDataManager
负责：
1. 管理K线DataFrame
2. 线程安全
3. 自动保存CSV
4. 加载历史数据
"""

import os
import threading
import pandas as pd


class MarketDataManager:
    def __init__(self, candle_cfg=None, tick_csv="ticks.csv", candle_csv="candles.csv"):
        self.tick_csv = tick_csv
        self.candle_csv = candle_csv

        self._data_lock = threading.RLock()

        self.candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        self.load()

    # ==========================
    # K线管理
    # ==========================

    def add_candle(self, candle: dict):
        with self._data_lock:

            row = {
                "timestamp": candle.get("time"),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": int(candle.get("volume", 0)),
            }

            self.candles = pd.concat([self.candles, pd.DataFrame([row])], ignore_index=True)

            # 保留最近5000根
            if len(self.candles) > 5000:
                self.candles = self.candles.tail(5000).reset_index(drop=True)

    # ==========================
    # 查询
    # ==========================

    def latest(self, n=100):
        with self._data_lock:
            return self.candles.tail(n).copy()

    def count(self):
        with self._data_lock:
            return len(self.candles)

    def clear(self):
        with self._data_lock:
            self.candles = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    # ==========================
    # 持久化
    # ==========================

    def persist(self):
        with self._data_lock:

            if len(self.candles) == 0:
                return

            self.candles.to_csv(self.candle_csv, index=False, encoding="utf-8-sig")

    def save(self):
        self.persist()

    # ==========================
    # 加载
    # ==========================

    def load(self):

        if not os.path.exists(self.candle_csv):
            return

        try:

            df = pd.read_csv(self.candle_csv)

            required = {"timestamp", "open", "high", "low", "close", "volume"}

            if not required.issubset(df.columns):
                return

            df["timestamp"] = pd.to_datetime(df["timestamp"])

            self.candles = df

            print(f"[DATA] 已加载历史K线 {len(df)} 根")

        except Exception as e:
            print(f"[DATA] 加载失败: {e}")

    # ==========================
    # 导出DataFrame
    # ==========================

    def get_dataframe(self):
        with self._data_lock:
            return self.candles.copy()
