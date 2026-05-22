"""
屏幕 OCR 行情监控 + DeepSeek 手动分析（仅提醒，不下单）
优化点：
1) 线程安全：用 Lock/Event 管理共享状态，菜单输入时暂停采集。
2) 稳定 OCR：增加图像增强与更稳健的数字解析。
3) 易用性：DeepSeek Key 放在脚本配置区，开箱即用。
4) AI 结果强校验：自动解析 JSON 并做字段兜底。
5) 提醒防抖：冷却时间避免连续弹窗轰炸。
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import pyautogui
import pytesseract
import requests
from PIL import ImageEnhance, ImageFilter

# ==================== 基础配置 ====================
# Windows 默认安装路径；如需覆盖请设置环境变量 TESSERACT_CMD
pytesseract.pytesseract.tesseract_cmd = os.getenv(
    "TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

REGIONS = {
    "time": (1661, 934, 57, 16),
    "deal": (1721, 934, 38, 16),
    "buy1": (1781, 934, 39, 16),
    "sell1": (1842, 934, 39, 16),
}
# 如果你的界面像示例图一样四个字段在同一行，可直接改为这一整行区域：
# 例如图中这一条可近似设置为 (x, y, 190, 20)
COMBINED_REGION = None  # e.g. (1661, 934, 220, 18)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = "请替换成你的DeepSeek Key"
MAX_PRICE_HISTORY = 60
POLL_INTERVAL_SEC = 1.0
ALERT_COOLDOWN_SEC = 15


@dataclass
class TradeState:
    position: str = "空仓"  # 空仓/多/空
    entry: Optional[float] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    alert_threshold: float = 2.0


@dataclass
class Runtime:
    prices: deque[int] = field(default_factory=lambda: deque(maxlen=MAX_PRICE_HISTORY))
    latest_time: str = ""
    latest_deal: str = ""
    latest_buy1: str = ""
    latest_sell1: str = ""
    ai_meta: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    pause_event: threading.Event = field(default_factory=threading.Event)
    stop_event: threading.Event = field(default_factory=threading.Event)
    last_alert_ts: float = 0.0


def _enhance_for_ocr(img):
    gray = img.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(2.2)
    gray = ImageEnhance.Sharpness(gray).enhance(2.0)
    gray = gray.filter(ImageFilter.MedianFilter(size=3))
    return gray


def _extract_digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def ocr_region(region, is_time=False) -> str:
    try:
        img = pyautogui.screenshot(region=region)
        img = _enhance_for_ocr(img)
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789:" if is_time else "--psm 7 -c tessedit_char_whitelist=0123456789"
        raw = pytesseract.image_to_string(img, config=cfg).strip()
        if is_time:
            return raw
        return _extract_digits(raw)[:8]  # 防止OCR粘连过长
    except Exception:
        return ""




def _parse_combined_line(text: str):
    clean = re.sub(r"[^0-9: ]", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    t = re.search(r"\b\d{1,2}:\d{2}:\d{2}\b", clean)
    nums = re.findall(r"\d+", clean)

    time_text = t.group(0) if t else ""
    # 如果识别出时间，去掉时间里的3段数字，保留成交/买1/卖1
    if time_text:
        hh, mm, ss = time_text.split(":")
        remaining = nums.copy()
        for seg in (hh, mm, ss):
            if seg in remaining:
                remaining.remove(seg)
        nums = remaining

    deal = nums[0] if len(nums) > 0 else ""
    buy1 = nums[1] if len(nums) > 1 else ""
    sell1 = nums[2] if len(nums) > 2 else ""
    return time_text, deal, buy1, sell1


def snapshot_market_combined(region):
    raw = ocr_region(region, is_time=True)
    return _parse_combined_line(raw)

def snapshot_market():
    if COMBINED_REGION is not None:
        t, d, b, s = snapshot_market_combined(COMBINED_REGION)
        # 容错：某一项识别失败时，回退到单字段识别
        if t and d and b and s:
            return t, d, b, s

    t = ocr_region(REGIONS["time"], is_time=True)
    d = ocr_region(REGIONS["deal"])
    b = ocr_region(REGIONS["buy1"])
    s = ocr_region(REGIONS["sell1"])
    return t, d, b, s


def beep():
    try:
        import winsound

        winsound.Beep(900, 180)
        time.sleep(0.08)
        winsound.Beep(900, 180)
        time.sleep(0.08)
        winsound.Beep(1200, 260)
    except Exception:
        print("\a", end="", flush=True)


def popup(msg: str):
    ctypes.windll.user32.MessageBoxW(0, msg, "AI交易提醒", 0x10)


def _safe_num(v, default=None):
    try:
        return float(v)
    except Exception:
        return default


def ai_analyze_and_set_params(rt: Runtime, st: TradeState) -> str:
    api_key = DEEPSEEK_API_KEY.strip()
    if not api_key or "请替换" in api_key:
        return "❌ 请先在代码顶部配置 DEEPSEEK_API_KEY"

    with rt.lock:
        prices = list(rt.prices)
        pos = st.position
        ent = st.entry

    if len(prices) < 10:
        return "❌ 数据不足，请等待至少10条价格后再分析"

    recent_5 = prices[-5:]
    recent_10 = prices[-10:]
    recent_30 = prices[-30:] if len(prices) >= 30 else prices
    recent_60 = prices[-60:] if len(prices) >= 60 else prices

    system_prompt = (
        "你是专业金融行情分析师，只根据历史价格做分析。"
        "必须严格输出 JSON，不要任何额外文字。"
        "JSON字段：trend,support,pressure,enter_advice,hold_advice,take_profit,stop_loss,alert_threshold,reason。"
        "其中 support/pressure/take_profit/stop_loss/alert_threshold 都必须是数字。"
    )

    user_content = {
        "position": pos,
        "entry": ent,
        "current": prices[-1],
        "recent_5": recent_5,
        "recent_10": recent_10,
        "recent_30": recent_30,
        "recent_60": recent_60,
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=15)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        result = json.loads(content)
    except Exception as e:
        return f"❌ AI分析失败：{e}"

    tp = _safe_num(result.get("take_profit"))
    sl = _safe_num(result.get("stop_loss"))
    threshold = _safe_num(result.get("alert_threshold"), st.alert_threshold)

    if tp is None or sl is None:
        return "❌ AI 返回缺少 take_profit/stop_loss 数值，未应用"

    st.tp = tp
    st.sl = sl
    st.alert_threshold = max(0.1, float(threshold))

    with rt.lock:
        rt.ai_meta = result

    return (
        "\n📊 AI 完整分析报告\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"当前趋势：{result.get('trend', '未知')}\n"
        f"支撑位：{result.get('support', '未知')}\n"
        f"压力位：{result.get('pressure', '未知')}\n"
        f"开仓建议：{result.get('enter_advice', '未知')}\n"
        f"持仓建议：{result.get('hold_advice', '未知')}\n"
        f"✅ 自动设置止盈：{st.tp}\n"
        f"✅ 自动设置止损：{st.sl}\n"
        f"✅ 自动设置波动提醒阈值：{st.alert_threshold}点\n"
        f"理由：{result.get('reason', '无')}"
    )


def auto_alert(rt: Runtime, st: TradeState, price: int):
    now = time.time()
    if now - rt.last_alert_ts < ALERT_COOLDOWN_SEC:
        return

    if st.position in {"多", "空"} and st.tp is not None and st.sl is not None:
        if st.position == "多":
            if price >= st.tp:
                popup(f"✅ 多单止盈触发！当前价：{price}，AI止盈价：{st.tp}")
                beep()
                rt.last_alert_ts = now
                return
            if price <= st.sl:
                popup(f"⚠️ 多单止损触发！当前价：{price}，AI止损价：{st.sl}")
                beep()
                rt.last_alert_ts = now
                return
        else:
            if price <= st.tp:
                popup(f"✅ 空单止盈触发！当前价：{price}，AI止盈价：{st.tp}")
                beep()
                rt.last_alert_ts = now
                return
            if price >= st.sl:
                popup(f"⚠️ 空单止损触发！当前价：{price}，AI止损价：{st.sl}")
                beep()
                rt.last_alert_ts = now
                return
    else:
        with rt.lock:
            prices = list(rt.prices)
        if len(prices) >= 10:
            avg_10 = sum(prices[-10:]) / 10
            if abs(price - avg_10) >= st.alert_threshold:
                direction = "上涨" if price > avg_10 else "下跌"
                popup(f"📢 AI检测到大幅{direction}！当前价：{price}，10分钟均价：{int(avg_10)}，波动超过{st.alert_threshold}点")
                beep()
                rt.last_alert_ts = now


def show_loop(rt: Runtime, st: TradeState):
    while not rt.stop_event.is_set():
        if rt.pause_event.is_set():
            time.sleep(0.1)
            continue

        t, d, b, s = snapshot_market()
        with rt.lock:
            rt.latest_time, rt.latest_deal, rt.latest_buy1, rt.latest_sell1 = t, d, b, s

        tp_text = f" 止盈:{st.tp}" if st.tp is not None else ""
        sl_text = f" 止损:{st.sl}" if st.sl is not None else ""
        print(f"{t:10} | 成交:{d:>6} | 买1:{b:>6} | 卖1:{s:>6} | 状态:{st.position}{tp_text}{sl_text}")

        if d.isdigit():
            p = int(d)
            with rt.lock:
                rt.prices.append(p)
            auto_alert(rt, st, p)

        time.sleep(POLL_INTERVAL_SEC)


def main_menu(rt: Runtime, st: TradeState):
    rt.pause_event.set()
    try:
        print("\n" + "=" * 44)
        print("【主菜单】")
        print("1. 切换持仓状态")
        print("2. 手动触发AI分析（自动设置止盈止损）")
        print("3. 查看当前AI参数")
        print("4. 清空历史价格数据")
        print("0. 返回监控")
        print("=" * 44)

        opt = input("请选择功能：").strip()
        if opt == "1":
            print("\n【持仓切换】\n1 空仓\n2 多单\n3 空单")
            sub = input("请选择：").strip()
            if sub == "1":
                st.position = "空仓"
                st.entry = None
                st.tp = None
                st.sl = None
                print("✅ 已切换：空仓")
            elif sub == "2":
                st.position = "多"
                st.entry = float(input("输入开仓价：").strip())
                print("✅ 已切换：多单，请触发AI分析")
            elif sub == "3":
                st.position = "空"
                st.entry = float(input("输入开仓价：").strip())
                print("✅ 已切换：空单，请触发AI分析")

        elif opt == "2":
            print("\n⏳ 正在进行AI分析...")
            print(ai_analyze_and_set_params(rt, st))

        elif opt == "3":
            with rt.lock:
                count = len(rt.prices)
            print("\n【当前AI参数】")
            print(f"持仓：{st.position} 开仓价：{st.entry if st.entry is not None else '无'}")
            print(f"止盈价：{st.tp if st.tp is not None else '未设置'}")
            print(f"止损价：{st.sl if st.sl is not None else '未设置'}")
            print(f"波动提醒阈值：{st.alert_threshold}点")
            print(f"已收集价格数据：{count}条")

        elif opt == "4":
            with rt.lock:
                rt.prices.clear()
            print("✅ 已清空历史价格数据")
    finally:
        rt.pause_event.clear()


def main():
    rt = Runtime()
    st = TradeState()

    print("=" * 65)
    print("🔥 AI全自动参数版（DeepSeek）· 平时0 token")
    print("✅ 后台持续收集数据，平时不调用API")
    print("✅ 手动触发AI，自动计算止盈止损和波动阈值")
    print("✅ 自动提醒完全基于本地参数")
    print("✅ 支持同一行OCR解析：时间/成交/买1/卖1")
    print("✅ 按回车打开主菜单，输入 q 回车退出")
    print("=" * 65)

    threading.Thread(target=show_loop, args=(rt, st), daemon=True).start()

    while True:
        cmd = input("\n👉 按回车打开主菜单 >>> ").strip().lower()
        if cmd == "q":
            rt.stop_event.set()
            break
        main_menu(rt, st)


if __name__ == "__main__":
    main()
