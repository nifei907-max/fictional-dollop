from datetime import datetime
from typing import Optional, Dict, Any

class CandleEngine:
    def __init__(self, interval_seconds: int = 60):
        self.interval = interval_seconds
        self.current_candle: Optional[Dict[str, Any]] = None

    def update_tick(self, price: float, tick_time: datetime) -> Optional[Dict]:
        minute_key = tick_time.replace(second=0, microsecond=0)
        if self.current_candle is None:
            self.current_candle = {
                "time": minute_key,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1
            }
            return None
        if minute_key == self.current_candle["time"]:
            self.current_candle["high"] = max(self.current_candle["high"], price)
            self.current_candle["low"] = min(self.current_candle["low"], price)
            self.current_candle["close"] = price
            self.current_candle["volume"] += 1
            return None
        finished = self.current_candle.copy()
        self.current_candle = {
            "time": minute_key,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1
            
        }
        return finished

    def force_flush(self) -> Optional[Dict]:
        if self.current_candle is None:
            return None
        finished = self.current_candle.copy()
        self.current_candle = None
        return finished