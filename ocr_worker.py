"""
OCR 线程：识别最新成交价、时间、买一价、卖一价（高速版）
- 使用独立区域识别 time_region / price_region / bid1_price_region / ask1_price_region
- 使用系统时间作为兜底 tick 时间戳
- 价格去重 + 跨分钟强制推送
- 将 bid/ask 传入 TickIndicatorEngine，用于主动买卖识别
"""

import logging
import re
import threading
from datetime import datetime

import pyautogui
import pytesseract

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
        if self.last_push_dt is not None and tick_dt.minute != self.last_push_dt.minute:
            self.last_price = price
            self.last_push_time = now_ts
            self.last_push_dt = tick_dt
            return price

        if self.last_price is not None and price == self.last_price:
            if (now_ts - self.last_push_time) < self.min_interval:
                return None

        if self.last_price is not None:
            price_change = abs(price - self.last_price)
            if price_change < self.min_change or price_change > self.max_jump:
                return None

        self.last_price = price
        self.last_push_time = now_ts
        self.last_push_dt = tick_dt
        return price


def _ocr_region(region, whitelist="0123456789"):
    left, top, width, height = region
    if width <= 0 or height <= 0:
        return ""
    img = pyautogui.screenshot(region=(left, top, width, height)).convert("L")
    config = f"--psm 7 -c tessedit_char_whitelist={whitelist}"
    return pytesseract.image_to_string(img, config=config).strip()


def _parse_number(text):
    if not text:
        return None
    match = re.search(r"\d+", text.replace(",", ""))
    if not match:
        return None
    return float(int(match.group(0)))


def _parse_time(text):
    if not text:
        return None
    match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", text)
    if not match:
        return None
    now = datetime.now()
    time_str = match.group(1)
    fmt = "%H:%M:%S" if time_str.count(":") == 2 else "%H:%M"
    parsed = datetime.strptime(time_str, fmt)
    return now.replace(hour=parsed.hour, minute=parsed.minute, second=parsed.second, microsecond=0)


def capture_number_region(config_key):
    """识别指定配置区域中的整数价格。"""
    try:
        text = _ocr_region(config_mgr.get_region(config_key))
        return _parse_number(text)
    except Exception:
        logger.exception("%s 识别异常", config_key)
        return None


def capture_price():
    price = capture_number_region("price_region")
    if price is None:
        return None
    if PRICE_MIN <= price <= PRICE_MAX:
        return price
    return None


def capture_time_price():
    """兼容旧测试/旧接口：返回 (tick_time, price)。"""
    tick_time = None
    try:
        time_text = _ocr_region(config_mgr.get_time_region(), whitelist="0123456789:")
        tick_time = _parse_time(time_text)
    except Exception:
        logger.exception("时间识别异常")
    return tick_time or datetime.now(), capture_price()


def capture_realtime_tick():
    """返回 (price, tick_time, bid1, ask1)。"""
    tick_time, price = capture_time_price()
    bid1 = capture_number_region("bid1_price_region")
    ask1 = capture_number_region("ask1_price_region")
    return price, tick_time, bid1, ask1


def run_ocr_worker(state: RuntimeState, stop_event: threading.Event, tick_engine=None):
    filt = TickFilter()
    consecutive_failures = 0
    logger.info("[OCR] 工作线程已启动（高速版）")

    while not stop_event.is_set():
        price, tick_time, bid1, ask1 = capture_realtime_tick()
        if price is None:
            consecutive_failures += 1
            if consecutive_failures >= 5:
                logger.warning("OCR 连续 %s 次识别失败，请检查区域", consecutive_failures)
                consecutive_failures = 0
            stop_event.wait(0.2)
            continue

        consecutive_failures = 0
        filtered_price = filt.update(price, tick_time)
        if filtered_price is None:
            stop_event.wait(0.2)
            continue

        state.update_price(filtered_price)
        state.update_tick_time(tick_time)
        try:
            tick_queue.put_nowait((filtered_price, tick_time, bid1, ask1))
        except Exception:
            pass

        if tick_engine is not None:
            tick_engine.add_tick(filtered_price, tick_time, bid1_price=bid1, ask1_price=ask1)

        stop_event.wait(0.2)

    logger.info("[OCR] 工作线程已停止")
