"""
历史K线抓取模块（一次性使用）- 本地时间，无时区
抓取完整 OHLC（开、高、低、收）和时间，直接保存为 K 线
配置键：ohlc_time_region, ohlc_price_region
"""

import win32gui
import time, re, os, pyautogui, pytesseract, pydirectinput, pygetwindow as gw
from PIL import Image
from datetime import datetime, timedelta
from config import CandleConfig, AppConfig
from config_manager import ConfigManager
from indicators import MarketDataManager

config_mgr = ConfigManager()
candle_cfg = CandleConfig()
app_cfg = AppConfig()

# ------------------------------------------------------------
# 1. 自动定位 Tesseract 可执行文件和 tessdata 目录
# ------------------------------------------------------------
base_dir = os.path.dirname(os.path.abspath(__file__))
tesseract_cmd = config_mgr.config.get("tesseract_cmd", "")
if not tesseract_cmd or not os.path.isfile(tesseract_cmd):
    parent_dir = os.path.dirname(base_dir)
    possible_path = os.path.join(parent_dir, "Tesseract-OCR", "tesseract.exe")
    if os.path.isfile(possible_path):
        tesseract_cmd = possible_path
    else:
        possible_path = os.path.join(base_dir, "Tesseract-OCR", "tesseract.exe")
        if os.path.isfile(possible_path):
            tesseract_cmd = possible_path
        else:
            tesseract_cmd = "tesseract"

if os.path.isfile(tesseract_cmd):
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    tessdata_dir = os.path.join(os.path.dirname(tesseract_cmd), "tessdata")
    if os.path.isdir(tessdata_dir):
        os.environ["TESSDATA_PREFIX"] = tessdata_dir
        print(f"[OK] Tesseract 路径: {tesseract_cmd}")
        print(f"[OK] tessdata 目录: {tessdata_dir}")
    else:
        print(f"[WARN] tessdata 目录不存在: {tessdata_dir}")
else:
    print(f"[ERROR] 找不到 tesseract.exe，请安装或配置路径")
    pytesseract.pytesseract.tesseract_cmd = "tesseract"

TRADING_WINDOW_TITLE = "华中九通"


def get_trading_window_client_left_top():
    title_keyword = "华中九通"
    hwnd = None

    def enum_callback(hwnd_enum, _):
        nonlocal hwnd
        text = win32gui.GetWindowText(hwnd_enum)
        if title_keyword in text and win32gui.IsWindowVisible(hwnd_enum):
            hwnd = hwnd_enum
            return False

    win32gui.EnumWindows(enum_callback, None)
    if hwnd is None:
        return None
    return win32gui.ClientToScreen(hwnd, (0, 0))


def get_region(config_key):
    cfg = config_mgr.config.get(config_key, {})
    left = cfg.get("left", 0)
    top = cfg.get("top", 0)
    width = cfg.get("width", 0)
    height = cfg.get("height", 0)
    rel_left = cfg.get("rel_left", 0)
    rel_top = cfg.get("rel_top", 0)
    if rel_left > 0 or rel_top > 0:
        client_coord = get_trading_window_client_left_top()
        if client_coord is not None:
            left = client_coord[0] + rel_left
            top = client_coord[1] + rel_top
    return (left, top, width, height)


def enlarge_image(img, scale=3):
    w, h = img.size
    return img.resize((w * scale, h * scale), Image.LANCZOS)


def ocr_text(region):
    if region[2] <= 0 or region[3] <= 0:
        return ""
    img = pyautogui.screenshot(region=region)
    img = img.convert("L")
    img = enlarge_image(img, scale=3)
    config = "--psm 7 -l chi_sim+eng"
    try:
        return pytesseract.image_to_string(img, config=config)
    except Exception as e:
        print(f"OCR 错误: {e}")
        return ""


def parse_time(text):
    match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", text)
    if match:
        return match.group(1)
    return None


def parse_ohlc(text):
    if not text:
        return None
    patterns = [
        r"开\s*[:：]?\s*([\d,.]+)\s*高\s*[:：]?\s*([\d,.]+)\s*低\s*[:：]?\s*([\d,.]+)\s*收\s*[:：]?\s*([\d,.]+)",
        r"开\s*([\d,.]+)\s*高\s*([\d,.]+)\s*低\s*([\d,.]+)\s*收\s*([\d,.]+)",
        r"高\s*([\d,.]+)\s*低\s*([\d,.]+)\s*收\s*([\d,.]+)",
        r"([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 4:
                open_val, high_val, low_val, close_val = groups
            elif len(groups) == 3:
                high_val, low_val, close_val = groups
                open_val = close_val
            else:
                continue
            try:
                o = float(open_val.replace(",", ""))
                h = float(high_val.replace(",", ""))
                l = float(low_val.replace(",", ""))
                c = float(close_val.replace(",", ""))
                if h < l:
                    h, l = l, h
                o = max(l, min(h, o))
                c = max(l, min(h, c))
                return {"open": o, "high": h, "low": l, "close": c}
            except:
                continue
    return None


def validate_ohlc(ohlc):
    if not ohlc:
        return None
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    if h < l:
        h, l = l, h
    o = max(l, min(h, o))
    c = max(l, min(h, c))
    ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"] = o, h, l, c
    return ohlc


def scrape_historical_klines(state, data_mgr_ref, total=60, stop_event=None):
    time_region = get_region("ohlc_time_region")
    price_region = get_region("ohlc_price_region")
    if price_region[2] <= 0 or price_region[3] <= 0:
        print("❌ OHLC 价格区域未设置，请在 user_config.json 中配置 ohlc_price_region")
        return
    if time_region[2] <= 0:
        print("⚠️ 时间区域未设置，将尝试从价格区域解析时间")

    SAFE_X, SAFE_Y = 100, 100
    pyautogui.moveTo(SAFE_X, SAFE_Y)
    print("⏳ 5 秒后开始抓取历史 K 线（完整 OHLC）...")
    for i in range(5, 0, -1):
        if stop_event and stop_event.is_set():
            return
        print(f"  {i}...")
        time.sleep(1)
    print("🚀 开始抓取")

    now = datetime.now()  # 本地时间，无时区
    candles = []
    for i in range(total):
        if stop_event and stop_event.is_set():
            break
        pyautogui.moveTo(SAFE_X, SAFE_Y)
        time_text = ocr_text(time_region) if time_region[2] > 0 else ""
        price_text = ocr_text(price_region)
        time_str = parse_time(time_text) or parse_time(price_text)
        ohlc = parse_ohlc(price_text)
        ohlc = validate_ohlc(ohlc)
        if ohlc and time_str:
            try:
                if ":" in time_str:
                    if time_str.count(":") == 1:
                        dt = datetime.strptime(f"{now.date()} {time_str}:00", "%Y-%m-%d %H:%M:%S")
                    else:
                        dt = datetime.strptime(f"{now.date()} {time_str}", "%Y-%m-%d %H:%M:%S")
                else:
                    dt = now - timedelta(minutes=(total - i))
                # 关键：不添加时区，保持 naive datetime
                candles.insert(
                    0,
                    {
                        "time": dt,
                        "open": ohlc["open"],
                        "high": ohlc["high"],
                        "low": ohlc["low"],
                        "close": ohlc["close"],
                    },
                )
                print(
                    f"   ✅ 第{i+1}根 {dt.strftime('%H:%M')} O:{ohlc['open']} H:{ohlc['high']} L:{ohlc['low']} C:{ohlc['close']}"
                )
            except Exception as e:
                print(f"   ⚠️ 时间解析失败: {time_str}, {e}")
        else:
            print(f"   ⚠️ 第{i+1}根识别失败（价格文本: {price_text[:50]})")
        if i < total - 1:
            pydirectinput.press("left")
            time.sleep(0.15)

    if not candles:
        print("❌ 未抓取到任何有效K线")
        return

    # 清空旧文件
    try:
        if os.path.exists(app_cfg.tick_csv):
            os.remove(app_cfg.tick_csv)
        if os.path.exists(app_cfg.candle_csv):
            os.remove(app_cfg.candle_csv)
    except:
        pass

    new_mgr = MarketDataManager(candle_cfg, app_cfg.tick_csv, app_cfg.candle_csv)
    for c in candles:
        new_mgr.add_candle(
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"], "volume": 0}
        )
    data_mgr_ref[0] = new_mgr
    state.base_price = candles[-1]["close"]
    state.update_price(state.base_price)
    print(f"✅ 历史K线抓取完成，共 {len(candles)} 根")
