"""
Tick 级指标引擎（高性能版 + 主动买卖识别 + 一致性 + 动态爆发）
"""

from collections import deque
from datetime import datetime
import numpy as np


class TickIndicatorEngine:
    def __init__(
        self,
        max_len=100,
        strength_norm_window=5,
        ema_short=3,
        ema_long=8,
        speed_ema_period=3,
        burst_lookback=10,
        burst_percentile=0.8,
    ):
        self.max_len = max_len
        self.strength_norm_window = strength_norm_window
        self.ema_short_period = ema_short
        self.ema_long_period = ema_long
        self.speed_ema_period = speed_ema_period
        self.burst_lookback = burst_lookback
        self.burst_percentile = burst_percentile

        self.prices = deque(maxlen=max_len)
        self.timestamps = deque(maxlen=max_len)
        self.volumes = deque(maxlen=max_len)
        self.bid_prices = deque(maxlen=max_len)
        self.ask_prices = deque(maxlen=max_len)

        self.last_tick_time = None
        self.last_price = None

        self.speed_ema = 0.0
        self.speed_ema_alpha = 2 / (speed_ema_period + 1)

        self.ema_short = None
        self.ema_long = None
        self.ema_short_alpha = 2 / (ema_short + 1)
        self.ema_long_alpha = 2 / (ema_long + 1)
        self.ema_initialized = False

        self.price_sum = 0.0
        self.vwap_sum = 0.0
        self.total_volume = 0

        # 主动买卖队列
        self.active_window = 20
        self.active_buy_queue = deque(maxlen=self.active_window)
        self.active_sell_queue = deque(maxlen=self.active_window)

    def add_tick(self, price, timestamp, bid1_price=None, ask1_price=None, volume=1):
        if len(self.prices) == self.max_len:
            oldest_price = self.prices[0]
            oldest_volume = self.volumes[0]
            self.price_sum -= oldest_price
            self.vwap_sum -= oldest_price * oldest_volume
            self.total_volume -= oldest_volume
        self.prices.append(price)
        self.price_sum += price
        self.volumes.append(volume)
        self.vwap_sum += price * volume
        self.total_volume += volume
        self.timestamps.append(timestamp)
        self.bid_prices.append(bid1_price)
        self.ask_prices.append(ask1_price)
        self.last_price = price
        self.last_tick_time = timestamp

        if len(self.prices) >= self.ema_long_period:
            if not self.ema_initialized:
                self.ema_short = price
                self.ema_long = price
                self.ema_initialized = True
            else:
                self.ema_short = price * self.ema_short_alpha + self.ema_short * (1 - self.ema_short_alpha)
                self.ema_long = price * self.ema_long_alpha + self.ema_long * (1 - self.ema_long_alpha)

        # 主动买卖判定（使用盘口价格）
        if bid1_price is not None and ask1_price is not None:
            if price >= ask1_price:
                self.active_buy_queue.append(1)
                self.active_sell_queue.append(0)
            elif price <= bid1_price:
                self.active_buy_queue.append(0)
                self.active_sell_queue.append(1)
            else:
                self.active_buy_queue.append(0)
                self.active_sell_queue.append(0)
        else:
            # 如果没有盘口数据，使用价格变化模拟（回测用）
            if len(self.prices) >= 2:
                if price > self.prices[-2]:
                    self.active_buy_queue.append(1)
                    self.active_sell_queue.append(0)
                elif price < self.prices[-2]:
                    self.active_buy_queue.append(0)
                    self.active_sell_queue.append(1)
                else:
                    self.active_buy_queue.append(0)
                    self.active_sell_queue.append(0)
            else:
                self.active_buy_queue.append(0)
                self.active_sell_queue.append(0)

    def tick_speed_raw(self):
        if len(self.prices) < 2:
            return 0.0
        dt = (self.timestamps[-1] - self.timestamps[-2]).total_seconds()
        if dt == 0:
            dt = 1e-6
        return (self.prices[-1] - self.prices[-2]) / dt

    def tick_speed(self, limit=20.0):
        raw = self.tick_speed_raw()
        self.speed_ema = raw * self.speed_ema_alpha + self.speed_ema * (1 - self.speed_ema_alpha)
        speed = self.speed_ema
        if speed > limit:
            speed = limit
        elif speed < -limit:
            speed = -limit
        return speed

    def tick_momentum(self, window=5):
        if len(self.prices) < window:
            return 0.0
        return self.prices[-1] - self.prices[-window]

    def tick_mean_price(self):
        if not self.prices:
            return 0.0
        return self.price_sum / len(self.prices)

    def tick_vwap(self):
        if self.total_volume == 0:
            return self.tick_mean_price()
        return self.vwap_sum / self.total_volume

    def tick_acceleration(self, limit=10.0):
        if len(self.prices) < 3:
            return 0.0
        dt1 = (self.timestamps[-2] - self.timestamps[-3]).total_seconds()
        dt2 = (self.timestamps[-1] - self.timestamps[-2]).total_seconds()
        if dt1 == 0:
            dt1 = 1e-6
        if dt2 == 0:
            dt2 = 1e-6
        speed1 = (self.prices[-2] - self.prices[-3]) / dt1
        speed2 = (self.prices[-1] - self.prices[-2]) / dt2
        acc = speed2 - speed1
        if acc > limit:
            acc = limit
        elif acc < -limit:
            acc = -limit
        return acc

    def is_burst(self, threshold=None):
        if len(self.prices) < 2:
            return False
        if threshold is not None:
            return abs(self.prices[-1] - self.prices[-2]) > threshold
        if len(self.prices) < self.burst_lookback + 1:
            return False
        changes = [abs(self.prices[i] - self.prices[i - 1]) for i in range(-self.burst_lookback, 0)]
        if not changes:
            return False
        dyn_threshold = np.percentile(changes, self.burst_percentile * 100)
        return abs(self.prices[-1] - self.prices[-2]) > dyn_threshold

    def get_tick_strength(self):
        if len(self.prices) < 2:
            return 0.0
        direction = 1 if self.prices[-1] > self.prices[-2] else -1 if self.prices[-1] < self.prices[-2] else 0
        if direction == 0:
            return 0.0
        count = 1
        for i in range(2, len(self.prices)):
            if self.prices[-i] > self.prices[-i - 1] and direction == 1:
                count += 1
            elif self.prices[-i] < self.prices[-i - 1] and direction == -1:
                count += 1
            else:
                break
        strength = min(count / self.strength_norm_window, 1.0)
        return strength * direction

    def micro_trend(self):
        if not self.ema_initialized:
            return 0.0
        return self.ema_short - self.ema_long

    def pressure_score(self, window=20):
        if len(self.prices) < window:
            return 0.0
        prices_list = list(self.prices)
        up = 0
        down = 0
        for i in range(-window + 1, 0):
            if prices_list[i] > prices_list[i - 1]:
                up += 1
            elif prices_list[i] < prices_list[i - 1]:
                down += 1
        total = up + down
        if total == 0:
            return 0.0
        return (up - down) / total

    def tick_consistency(self, window=None):
        if window is None:
            window = max(5, len(self.prices) // 5)
            window = min(window, len(self.prices) - 1)
        if len(self.prices) < window:
            return 0.5
        current_dir = 1 if self.prices[-1] > self.prices[-2] else -1 if self.prices[-1] < self.prices[-2] else 0
        if current_dir == 0:
            return 0.5
        same = 0
        for i in range(-window, -1):
            if self.prices[i] > self.prices[i - 1] and current_dir == 1:
                same += 1
            elif self.prices[i] < self.prices[i - 1] and current_dir == -1:
                same += 1
        return same / (window - 1) if (window - 1) > 0 else 0.5

    def aggressive_buying(self, window=10):
        """主动买盘强度：连续上涨tick比例 [0,1]"""
        if len(self.prices) < window:
            return 0.0
        up = 0
        for i in range(-window + 1, 0):
            if self.prices[i] > self.prices[i - 1]:
                up += 1
        return up / (window - 1)

    def aggressive_selling(self, window=10):
        """主动卖盘强度：连续下跌tick比例 [0,1]"""
        if len(self.prices) < window:
            return 0.0
        down = 0
        for i in range(-window + 1, 0):
            if self.prices[i] < self.prices[i - 1]:
                down += 1
        return down / (window - 1)

    def active_buy_ratio(self):
        if len(self.active_buy_queue) == 0:
            return 0.0
        return sum(self.active_buy_queue) / len(self.active_buy_queue)

    def active_sell_ratio(self):
        if len(self.active_sell_queue) == 0:
            return 0.0
        return sum(self.active_sell_queue) / len(self.active_sell_queue)

    def active_imbalance(self):
        return self.active_buy_ratio() - self.active_sell_ratio()

    def orderbook_pressure(self):
        # 简化版，实际可计算买一卖一量比例
        if len(self.bid_prices) == 0 or self.bid_prices[-1] is None or self.ask_prices[-1] is None:
            return 0.0
        # 这里仅示例，返回0
        return 0.0

    def is_stale(self, timeout=3):
        if self.last_tick_time is None:
            return True
        return (datetime.now() - self.last_tick_time).total_seconds() > timeout
