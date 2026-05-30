"""风控线程：监控持仓，止损/止盈，保本移动，并发送GUI通知"""

import threading
import time
from runtime_state import RuntimeState
from notifier import play_sound

MAX_HOLD_SECONDS = 300
gui_queue = None


def risk_worker(state: RuntimeState, stop_event: threading.Event):
    global gui_queue
    while not stop_event.is_set():
        state.price_updated.wait(timeout=0.1)
        state.price_updated.clear()
        pos, _ = state.get_position()
        if pos is None or pos.get("closing"):
            continue

        if "entry_time" in pos:
            if time.time() - pos["entry_time"] > MAX_HOLD_SECONDS:
                price = state.get_price()
                if price is not None:
                    _close_position(state, pos, price, reason="超时平仓")
                continue

        side = pos["side"]
        entry = pos["entry"]
        stop = pos["stop"]
        price = state.get_price()
        if price is None:
            continue

        # 盈利3点自动保本
        if side == "LONG":
            if (price - entry) >= 3 and stop < entry:
                state.move_stop_if_better(entry, "LONG")
        elif side == "SHORT":
            if (entry - price) >= 3 and stop > entry:
                state.move_stop_if_better(entry, "SHORT")

        initial_risk = pos.get("initial_risk", abs(entry - stop))
        if side == "LONG":
            profit = price - entry
            if profit >= initial_risk * 1.5:
                state.move_stop_if_better(entry, "LONG")
            if profit >= initial_risk * 2.0:
                state.move_stop_if_better(entry + initial_risk, "LONG")
            if profit >= initial_risk * 3.0:
                state.move_stop_if_better(entry + initial_risk * 2, "LONG")
        else:
            profit = entry - price
            if profit >= initial_risk * 1.5:
                state.move_stop_if_better(entry, "SHORT")
            if profit >= initial_risk * 2.0:
                state.move_stop_if_better(entry - initial_risk, "SHORT")
            if profit >= initial_risk * 3.0:
                state.move_stop_if_better(entry - initial_risk * 2, "SHORT")

        pos_cur, _ = state.get_position()
        if pos_cur is None:
            continue
        if side == "LONG":
            if price <= pos_cur["stop"]:
                _close_position(state, pos_cur, price, reason="止损")
            elif price >= pos_cur["take"]:
                _close_position(state, pos_cur, price, reason="止盈")
        else:
            if price >= pos_cur["stop"]:
                _close_position(state, pos_cur, price, reason="止损")
            elif price <= pos_cur["take"]:
                _close_position(state, pos_cur, price, reason="止盈")


def _close_position(state, pos, price, reason):
    state.set_closing()
    side, entry = pos["side"], pos["entry"]
    direction = 1 if side == "LONG" else -1
    pnl = (price - entry) * direction
    if reason == "止损":
        slippage = (price - pos["stop"]) * direction
        state.log_slippage(slippage, side, "stop")
    else:
        state.log_slippage(0, side, "take")
    state.update_daily_pnl(pnl)
    trade_info = {
        "trade_id": pos.get("trade_id"),
        "side": side,
        "entry": entry,
        "exit": price,
        "pnl": pnl,
        "reason": reason,
        "entry_time": pos.get("entry_time"),
        "exit_time": time.time(),
    }
    print(f"成交: {trade_info}")
    state.set_position(None, "EMPTY")
    if reason == "止损":
        state.consecutive_losses += 1
    else:
        state.consecutive_losses = 0
    play_sound(500, 500) if reason == "止损" else play_sound(1500, 300)

    if gui_queue is not None:
        try:
            gui_queue.put_nowait(("warning", f"⚠️ 持仓平仓：{reason}，{side} @{price:.2f}，盈亏:{pnl:.2f}点"))
        except:
            pass
