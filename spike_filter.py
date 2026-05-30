"""瞬时波动熔断"""
import time

class SpikeFilter:
    def __init__(self, spike_threshold=8, block_seconds=30):
        self.last_price = None
        self.blocked_until = 0
        self.spike_threshold = spike_threshold
        self.block_seconds = block_seconds

    def check(self, price: float) -> bool:
        now = time.time()
        if now < self.blocked_until:
            return False
        if self.last_price is not None and abs(price - self.last_price) >= self.spike_threshold:
            self.blocked_until = now + self.block_seconds
            self.last_price = price
            print(f"⚠️ 瞬时波动超过 {self.spike_threshold} 点，暂停 {self.block_seconds} 秒")
            return False
        self.last_price = price
        return True