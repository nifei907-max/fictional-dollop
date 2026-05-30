"""
分析线程：从 candle_queue 取已完成的 K 线，运行策略
同时合并当前 forming candle，实现实时决策
增加 AI 分析结果推送，并使用实时价格进行解读
市场状态机（第五阶段：趋势生命周期）
"""

import threading
import queue
import pandas as pd
from queues import candle_queue, signal_queue
from runtime_state import RuntimeState
import strategy
import candle_worker

data_mgr = None
tick_engine = None
gui_queue = None


def update_market_state(state, ind, tick_indicators, current_price):
    """
    更新市场状态机 - 第五阶段：趋势生命周期
    状态：WAITING, EARLY_LONG, TREND_LONG, STRONG_LONG, LONG_EXHAUSTION,
          RANGE, EARLY_SHORT, TREND_SHORT, STRONG_SHORT, SHORT_EXHAUSTION
    """
    ema_fast = ind["ema_mid"]  # EMA7
    ema_slow = ind["ema_long"]  # EMA13
    slope = ind["ema_slope"]
    trend_strength = ind["trend_strength"]
    recent_range = ind["recent_range"]
    rsi = ind["rsi"]
    bull_consecutive = ind["bull_consecutive"]
    bear_consecutive = ind["bear_consecutive"]
    tick_momentum = tick_indicators.get("momentum", 0)
    tick_acc = tick_indicators.get("acceleration", 0)
    buy_pressure = tick_indicators.get("aggressive_buying", 0)
    sell_pressure = tick_indicators.get("aggressive_selling", 0)
    current_state = state.get_market_state()

    # ========== 多头生命周期 ==========
    if current_state == "WAITING":
        if ema_fast > ema_slow and tick_momentum > 0 and buy_pressure > 0.6:
            state.set_market_state("EARLY_LONG")
        elif ema_fast < ema_slow and tick_momentum < 0 and sell_pressure > 0.6:
            state.set_market_state("EARLY_SHORT")

    elif current_state == "EARLY_LONG":
        if trend_strength > 0.05:
            state.set_market_state("TREND_LONG")
        elif ema_fast < ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "TREND_LONG":
        # 进入加速阶段
        if buy_pressure > 0.8 and tick_acc > 0 and bull_consecutive >= 3:
            state.set_market_state("STRONG_LONG")
        elif ema_fast < ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "STRONG_LONG":
        # 进入衰竭
        if rsi > 85 and tick_acc < 0:
            state.set_market_state("LONG_EXHAUSTION")
        elif ema_fast < ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "LONG_EXHAUSTION":
        # 衰竭后进入震荡
        if abs(slope) < 0.03 and recent_range < 3:
            state.set_market_state("RANGE")
        elif ema_fast < ema_slow:
            state.set_market_state("WAITING")
        elif buy_pressure > 0.6 and tick_momentum > 0:
            # 衰竭后重新走强，可回到 TREND_LONG
            state.set_market_state("TREND_LONG")

    # ========== 空头生命周期（镜像）==========
    elif current_state == "EARLY_SHORT":
        if trend_strength > 0.05:
            state.set_market_state("TREND_SHORT")
        elif ema_fast > ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "TREND_SHORT":
        if sell_pressure > 0.8 and tick_acc < 0 and bear_consecutive >= 3:
            state.set_market_state("STRONG_SHORT")
        elif ema_fast > ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "STRONG_SHORT":
        if rsi < 15 and tick_acc > 0:
            state.set_market_state("SHORT_EXHAUSTION")
        elif ema_fast > ema_slow:
            state.set_market_state("WAITING")

    elif current_state == "SHORT_EXHAUSTION":
        if abs(slope) < 0.03 and recent_range < 3:
            state.set_market_state("RANGE")
        elif ema_fast > ema_slow:
            state.set_market_state("WAITING")
        elif sell_pressure > 0.6 and tick_momentum < 0:
            state.set_market_state("TREND_SHORT")

    # ========== RANGE 状态（双向均可转为早期趋势）==========
    elif current_state == "RANGE":
        if ema_fast > ema_slow and tick_momentum > 0 and buy_pressure > 0.6:
            state.set_market_state("EARLY_LONG")
        elif ema_fast < ema_slow and tick_momentum < 0 and sell_pressure > 0.6:
            state.set_market_state("EARLY_SHORT")

    else:
        state.set_market_state("WAITING")


def run_analysis_worker(state: RuntimeState, stop_event: threading.Event):
    global data_mgr, tick_engine, gui_queue
    while not stop_event.is_set():
        try:
            item = candle_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        except Exception:
            continue

        if isinstance(item, dict) and item.get("force"):
            continue

        if data_mgr is None:
            continue

        with data_mgr._data_lock:
            df = data_mgr.candles.tail(100).copy()
        if len(df) < 15:
            continue

        if candle_worker.candle_engine is not None:
            current = candle_worker.candle_engine.current_candle
            if current is not None:
                forming = {
                    "timestamp": current["time"],
                    "open": current["open"],
                    "high": current["high"],
                    "low": current["low"],
                    "close": current["close"],
                    "volume": current["volume"],
                }
                df = pd.concat([df, pd.DataFrame([forming])], ignore_index=True)

        closed_df = df.iloc[:-1]
        if len(closed_df) >= 14:
            ind = strategy.calculate_indicators(closed_df)
            atr = ind.get("atr", 2.0)
            burst_threshold = max(0.5, atr * 0.1)
        else:
            burst_threshold = 0.5

        tick_indicators = {}
        if tick_engine is not None:
            tick_indicators = {
                "speed": tick_engine.tick_speed(),
                "momentum": tick_engine.tick_momentum(),
                "mean_price": tick_engine.tick_mean_price(),
                "acceleration": tick_engine.tick_acceleration(),
                "burst": tick_engine.is_burst(threshold=burst_threshold),
                "strength": tick_engine.get_tick_strength(),
                "micro_trend": tick_engine.micro_trend(),
                "pressure": tick_engine.pressure_score(),
                "consistency": tick_engine.tick_consistency(),
                "orderbook_pressure": tick_engine.orderbook_pressure(),
                "active_imbalance": tick_engine.active_imbalance(),
                "aggressive_buying": tick_engine.aggressive_buying(),
                "aggressive_selling": tick_engine.aggressive_selling(),
            }

        current_price = df.iloc[-1]["close"]
        # 更新市场状态（生命周期）
        update_market_state(state, ind, tick_indicators, current_price)

        # 使用状态机驱动入场
        market_state = state.get_market_state()
        signal = strategy.state_based_trade_rule(
            df=df, state=state, tick_indicators=tick_indicators, market_state=market_state
        )

        if signal:
            signal_queue.put(signal)
            real_time_price = state.get_price()
            if real_time_price is None:
                real_time_price = df.iloc[-1]["close"]
            ind_full = strategy.calculate_indicators(df)
            explanation = strategy.explain_analysis(ind_full, real_time_price, signal)
            if gui_queue:
                try:
                    gui_queue.put_nowait(("explain", explanation))
                except:
                    pass
            # 反向信号提醒
            pos, _ = state.get_position()
            if pos is not None:
                pos_side = pos.get("side")
                signal_side = signal.get("side")
                if pos_side == "LONG" and signal_side == "SHORT":
                    msg = "⚠️ 反向信号：持有多单，出现做空信号，建议平仓！"
                    if gui_queue:
                        try:
                            gui_queue.put_nowait(("warning", msg))
                        except:
                            pass
                elif pos_side == "SHORT" and signal_side == "LONG":
                    msg = "⚠️ 反向信号：持有空单，出现做多信号，建议平仓！"
                    if gui_queue:
                        try:
                            gui_queue.put_nowait(("warning", msg))
                        except:
                            pass

        # AI 分析（当 state.analysis_mode == 0 时）
        if state.analysis_mode == 0 and len(closed_df) >= 14:
            try:
                ai_text = strategy.run_ai_analysis(df, state)
                if ai_text and gui_queue:
                    gui_queue.put_nowait(("ai", ai_text))
            except Exception as e:
                print(f"AI分析异常: {e}")
