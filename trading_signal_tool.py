"""
屏幕 OCR 行情监控 + AI 自动分析交易（仅提醒，不下单）

功能概览：
1) 每秒 OCR 读取固定屏幕区域：时间、成交价、买1、卖1。
2) 后台持续运行，缓存最近 60 条价格历史。
3) 默认完全本地监控，不调用任何远程 API。
4) 按回车进入菜单：切换持仓、手动触发 AI 分析。
5) AI 返回 JSON（趋势/支撑压力/止盈止损/波动阈值），程序自动解析并生效。
6) 本地提醒：
   - 持仓时命中止盈止损提醒；
   - 空仓时超阈值波动提醒。

注意：
- 本程序不包含任何自动下单逻辑。
- 首次运行前请安装 Tesseract 并配置 pytesseract.pytesseract.tesseract_cmd。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

import pyautogui
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

try:
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None  # type: ignore


@dataclass
class OcrZones:
    # 你后续按自己的软件界面修改这些坐标
    time_box: Tuple[int, int, int, int] = (120, 180, 220, 34)
    last_px_box: Tuple[int, int, int, int] = (120, 230, 220, 34)
    bid1_box: Tuple[int, int, int, int] = (120, 280, 220, 34)
    ask1_box: Tuple[int, int, int, int] = (120, 330, 220, 34)


@dataclass
class RuntimeProfile:
    ocr_interval_sec: float = 1.0
    history_window: int = 60
    cool_down_sec: int = 20


@dataclass
class HoldingState:
    side: str = "FLAT"  # FLAT / LONG / SHORT
    entry_px: Optional[float] = None


@dataclass
class AiTradePlan:
    trend: str = "unknown"
    support: Optional[float] = None
    resistance: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    swing_alert_threshold: Optional[float] = None  # 绝对价格阈值
    generated_at: Optional[str] = None


@dataclass
class SharedRuntime:
    latest_tick: Dict[str, Optional[float | str]] = field(
        default_factory=lambda: {"time": None, "price": None, "bid1": None, "ask1": None}
    )
    price_tape: deque = field(default_factory=lambda: deque(maxlen=60))
    hold: HoldingState = field(default_factory=HoldingState)
    ai_plan: AiTradePlan = field(default_factory=AiTradePlan)
    lock: threading.Lock = field(default_factory=threading.Lock)
    pause_event: threading.Event = field(default_factory=threading.Event)
    stop_event: threading.Event = field(default_factory=threading.Event)
    last_alert_ts: float = 0.0


def beep_alert() -> None:
    try:
        import winsound

        winsound.Beep(1400, 250)
        winsound.Beep(1200, 250)
    except Exception:
        print("\a", end="", flush=True)


def popup_hint(title: str, message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showwarning(title, message)
        root.destroy()
    except Exception:
        print(f"[POPUP FALLBACK] {title}: {message}")


def clean_float(text: str) -> Optional[float]:
    matched = re.findall(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
    if not matched:
        return None
    try:
        return float(matched[0])
    except ValueError:
        return None


def prep_image(img: Image.Image) -> Image.Image:
    gray = img.convert("L")
    sharp = ImageEnhance.Sharpness(gray).enhance(2.2)
    contrast = ImageEnhance.Contrast(sharp).enhance(2.0)
    denoise = contrast.filter(ImageFilter.MedianFilter(size=3))
    return denoise


def read_box_number(region: Tuple[int, int, int, int]) -> Optional[float]:
    snap = pyautogui.screenshot(region=region)
    txt = pytesseract.image_to_string(prep_image(snap), config="--psm 7 -c tessedit_char_whitelist=0123456789.-:")
    return clean_float(txt)


def read_box_text(region: Tuple[int, int, int, int]) -> str:
    snap = pyautogui.screenshot(region=region)
    txt = pytesseract.image_to_string(prep_image(snap), config="--psm 7")
    return txt.strip()


def screen_ocr_once(zones: OcrZones) -> Dict[str, Optional[float | str]]:
    tick_time = read_box_text(zones.time_box)
    last_px = read_box_number(zones.last_px_box)
    bid1 = read_box_number(zones.bid1_box)
    ask1 = read_box_number(zones.ask1_box)
    return {"time": tick_time, "price": last_px, "bid1": bid1, "ask1": ask1}


def trend_from_prices(prices: list[float]) -> str:
    if len(prices) < 8:
        return "sideways"
    first = prices[0]
    last = prices[-1]
    delta = (last - first) / first if first else 0
    if delta > 0.003:
        return "up"
    if delta < -0.003:
        return "down"
    return "sideways"


def build_ai_prompt(history: list[float], hold: HoldingState, last_tick: Dict[str, Optional[float | str]]) -> str:
    return (
        "你是盘中风控分析助手。仅返回 JSON，不要任何额外解释。\n"
        "输出字段必须包含：trend,support,resistance,take_profit,stop_loss,swing_alert_threshold,reasoning_brief。\n"
        "规则：\n"
        "1) trend 只能是 up/down/sideways。\n"
        "2) support,resistance,take_profit,stop_loss,swing_alert_threshold 都必须是数字。\n"
        "3) 若当前持仓为空仓，take_profit/stop_loss 也要给出“假设入场后”的参考值。\n"
        "4) swing_alert_threshold 表示绝对价格变化阈值（非百分比）。\n"
        f"当前持仓: {hold.side}, entry_px={hold.entry_px}\n"
        f"最新行情: {last_tick}\n"
        f"最近{len(history)}条价格: {history}\n"
        "请输出紧凑 JSON。"
    )


def call_ai_analyzer(state: SharedRuntime) -> bool:
    if OpenAI is None:
        print("[AI] SDK 未安装，无法调用 DeepSeek 分析。")
        return False

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("[AI] 未检测到 DEEPSEEK_API_KEY，跳过 AI 分析。")
        return False

    with state.lock:
        history = list(state.price_tape)
        hold = HoldingState(state.hold.side, state.hold.entry_px)
        last_tick = dict(state.latest_tick)

    if len(history) < 12:
        print("[AI] 价格历史少于12条，建议再观察后分析。")
        return False

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    prompt = build_ai_prompt(history, hold, last_tick)

    try:
        resp = client.responses.create(
            model="deepseek-chat",
            input=prompt,
            temperature=0.2,
        )
        raw = (resp.output_text or "").strip()
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"[AI] 分析失败: {exc}")
        return False

    try:
        plan = AiTradePlan(
            trend=str(parsed["trend"]),
            support=float(parsed["support"]),
            resistance=float(parsed["resistance"]),
            take_profit=float(parsed["take_profit"]),
            stop_loss=float(parsed["stop_loss"]),
            swing_alert_threshold=float(parsed["swing_alert_threshold"]),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[AI] JSON 字段不完整或格式错误: {exc}")
        return False

    with state.lock:
        state.ai_plan = plan

    print("[AI] 分析成功并已更新本地风控参数。")
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    return True


def monitor_loop(state: SharedRuntime, zones: OcrZones, cfg: RuntimeProfile) -> None:
    while not state.stop_event.is_set():
        if state.pause_event.is_set():
            time.sleep(0.05)
            continue

        tick = screen_ocr_once(zones)
        px = tick.get("price")

        with state.lock:
            state.latest_tick = tick
            if isinstance(px, float):
                state.price_tape.append(px)
            history = list(state.price_tape)
            hold = HoldingState(state.hold.side, state.hold.entry_px)
            plan = state.ai_plan

        evaluate_alerts(state, hold, plan, history, tick, cfg)
        log_line = f"[{datetime.now().strftime('%H:%M:%S')}] T={tick.get('time')} P={tick.get('price')} B1={tick.get('bid1')} A1={tick.get('ask1')}"
        print(log_line)
        time.sleep(cfg.ocr_interval_sec)


def evaluate_alerts(
    state: SharedRuntime,
    hold: HoldingState,
    plan: AiTradePlan,
    history: list[float],
    tick: Dict[str, Optional[float | str]],
    cfg: RuntimeProfile,
) -> None:
    now_ts = time.time()
    if now_ts - state.last_alert_ts < cfg.cool_down_sec:
        return

    price = tick.get("price")
    if not isinstance(price, float):
        return

    # 持仓提醒：命中止盈止损
    if hold.side in {"LONG", "SHORT"} and plan.take_profit is not None and plan.stop_loss is not None:
        hit_tp = hold.side == "LONG" and price >= plan.take_profit or hold.side == "SHORT" and price <= plan.take_profit
        hit_sl = hold.side == "LONG" and price <= plan.stop_loss or hold.side == "SHORT" and price >= plan.stop_loss

        if hit_tp or hit_sl:
            typ = "止盈触发" if hit_tp else "止损触发"
            msg = f"{typ}\n最新价: {price}\n止盈: {plan.take_profit}\n止损: {plan.stop_loss}"
            beep_alert()
            popup_hint("持仓预警", msg)
            state.last_alert_ts = now_ts
            return

    # 空仓提醒：近期波动超阈值
    if hold.side == "FLAT" and plan.swing_alert_threshold is not None and len(history) >= 2:
        move = abs(history[-1] - history[-2])
        if move >= plan.swing_alert_threshold:
            msg = f"空仓波动预警\n最新跳动: {move:.4f}\n阈值: {plan.swing_alert_threshold:.4f}"
            beep_alert()
            popup_hint("空仓波动提醒", msg)
            state.last_alert_ts = now_ts


def show_menu() -> None:
    print("\n====== 手动菜单 ======")
    print("1) 切换持仓")
    print("2) 手动触发 AI 分析")
    print("3) 查看当前状态")
    print("0) 返回监控")


def handle_position_input(state: SharedRuntime) -> None:
    while True:
        mode = input("选择持仓 [FLAT/LONG/SHORT]: ").strip().upper()
        if mode not in {"FLAT", "LONG", "SHORT"}:
            print("输入无效，请重试。")
            continue

        entry_px = None
        if mode in {"LONG", "SHORT"}:
            raw = input("输入开仓价: ").strip()
            val = clean_float(raw)
            if val is None:
                print("开仓价无效。")
                continue
            entry_px = val

        with state.lock:
            state.hold.side = mode
            state.hold.entry_px = entry_px
        print(f"持仓已更新 -> {mode}, entry={entry_px}")
        return


def print_snapshot(state: SharedRuntime) -> None:
    with state.lock:
        tick = dict(state.latest_tick)
        hist = list(state.price_tape)
        hold = state.hold
        plan = state.ai_plan

    print("\n------ 当前状态 ------")
    print(f"最新: {tick}")
    print(f"价格历史条数: {len(hist)}")
    print(f"持仓: side={hold.side}, entry={hold.entry_px}")
    print(
        "AI参数: "
        f"trend={plan.trend}, support={plan.support}, resistance={plan.resistance}, "
        f"tp={plan.take_profit}, sl={plan.stop_loss}, swing={plan.swing_alert_threshold}, at={plan.generated_at}"
    )


def control_loop(state: SharedRuntime) -> None:
    print("监控启动：按回车打开菜单，输入 q 回车退出。")
    while not state.stop_event.is_set():
        cmd = input()
        if cmd.strip().lower() == "q":
            state.stop_event.set()
            return

        state.pause_event.set()
        try:
            while True:
                show_menu()
                opt = input("请选择: ").strip()
                if opt == "1":
                    handle_position_input(state)
                elif opt == "2":
                    ok = call_ai_analyzer(state)
                    if not ok:
                        print("AI 分析未生效，请检查上方日志。")
                elif opt == "3":
                    print_snapshot(state)
                elif opt == "0":
                    break
                else:
                    print("无效选项，请重试。")
        finally:
            state.pause_event.clear()


def main() -> None:
    pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD", pytesseract.pytesseract.tesseract_cmd)

    zones = OcrZones()
    cfg = RuntimeProfile()
    state = SharedRuntime(price_tape=deque(maxlen=cfg.history_window))

    t = threading.Thread(target=monitor_loop, args=(state, zones, cfg), daemon=True)
    t.start()

    try:
        control_loop(state)
    except KeyboardInterrupt:
        state.stop_event.set()
    finally:
        print("程序退出中...")


if __name__ == "__main__":
    main()
