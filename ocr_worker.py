"""
OCR 线程：只识别最新成交价（高速版）
- 区域仅包含价格数字
- 使用系统时间作为 tick 时间戳
- 采样间隔 0.2 秒
- 灰度图直接识别，不二值化
- 价格去重 + 跨分钟强制推送
"""

import time
import threading
import logging
import pyautogui
import pytesseract
from datetime import datetime
from queues import tick_queue
from runtime_state import RuntimeState
from config_manager import ConfigManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("OCR")

config_mgr = ConfigManager()
pytesseract.pytesseract.tesseract_cmd = config_mgr.config.get("tesseract_cmd", r"./Tesseract-OCR/tesseract.exe")

PRICE_MIN = 2000
PRICE_MAX = 3500
MIN_PRICE_CHANGE = config_mgr.config.get("min_price_change", 1)
MAX_PRICE_JUMP = config_mgr.config.get("max_price_jump", 20)


class TickFilter:
    def __init__(self, max_jump=MAX_PRICE_JUMP, min_interval=0.2, min_change=MIN_PRICE_CHANGE):
        self.last_price = None
        self.max_jump = max_jump
        self.last_push_time = 0
        self.last_push_dt = None
        self.min_interval = min_interval
        self.min_change = min_change

    def update(self, price, tick_dt):
        now_ts = tick_dt.timestamp()
        if self.last_push_dt is not None:
            if tick_dt.minute != self.last_push_dt.minute:
                self.last_price = price
                self.last_push_time = now_ts
                self.last_push_dt = tick_dt
                return price
        if self.last_price is not None and price == self.last_price:
            if (now_ts - self.last_push_time) < self.min_interval:
                return None
        if self.last_price is not None:
            price_change = abs(price - self.last_price)
            if price_change < self.min_change:
                return None
            if price_change > self.max_jump:
                return None
        self.last_price = price
        self.last_push_time = now_ts
        self.last_push_dt = tick_dt
        return price


def capture_price():
    left, top, width, height = config_mgr.get_price_region()
    if width <= 0 or height <= 0:
        logger.error("价格区域未设置，请先标定 price_region")
        return None
    try:
        img = pyautogui.screenshot(region=(left, top, width, height))
        # 灰度图，不做二值化（保留更多信息）
        img = img.convert("L")
        # 快速识别，只允许数字
        config = "--psm 7 -c tessedit_char_whitelist=0123456789"
        text = pytesseract.image_to_string(img, config=config)
        text = text.strip()
        if not text:
            return None
        price = int(text)
        if PRICE_MIN <= price <= PRICE_MAX:
            return float(price)
        else:
            return None
    except Exception as e:
        logger.exception("价格识别异常")
        return None


def run_ocr_worker(state: RuntimeState, stop_event: threading.Event, tick_engine=None):
    filt = TickFilter()
    last_price = None
    consecutive_failures = 0
    logger.info("[OCR] 工作线程已启动（高速版）")
    while not stop_event.is_set():
        price = capture_price()
        if price is None:
            consecutive_failures += 1
            if consecutive_failures >= 5:
                logger.warning(f"OCR 连续 {consecutive_failures} 次识别失败，请检查区域")
                consecutive_failures = 0
            stop_event.wait(0.2)
            continue
        consecutive_failures = 0

        if price == last_price:
            stop_event.wait(0.2)
            continue
        last_price = price

        # 使用系统当前时间作为 tick 时间戳
        tick_time = datetime.now()
        price = filt.update(price, tick_time)
        if price is None:
            stop_event.wait(0.2)
            continue

        state.update_price(price)
        state.update_tick_time(tick_time)
        try:
            tick_queue.put_nowait((price, tick_time))
        except:
            pass
        if tick_engine is not None:
            tick_engine.add_tick(price, tick_time)
        stop_event.wait(0.2)  # 0.2秒采样一次
    logger.info("[OCR] 工作线程已停止")
