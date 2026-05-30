"""
策略模块：1分钟超短线自适应系统（最终稳定版）
- 方向硬过滤：基于 EMA7/EMA13 趋势，禁止逆势开仓
- tick 指标仅作为择时辅助，权重降低为 0.3
- 支持 forming candle 实时分析
- 防止同根K线重复信号
- ATR 波动过滤：避免死盘或疯盘
- 禁止追单：价格必须在 EMA7 附近 ±2 点才允许开仓
- 回踩确认：价格需回撤至 EMA7 附近
- 信号门槛提高至 4 分，减少垃圾信号
- RSI 限制放宽至 85/15
- tick_consistency 加入评分（权重 0.3）
- 新增盘口压力指标 orderbook_pressure 参与评分
- 新增主动买卖识别 active_imbalance 参与评分
"""

import time
import numpy as np
import pandas as pd
from config import NotifyConfig, APIConfig
from runtime_state import RuntimeState
from deepseek_client import DeepSeekClient
from config_manager import ConfigManager

notify_cfg = NotifyConfig()
api_cfg = APIConfig()
ai_client = DeepSeekClient(api_cfg)
config_mgr = ConfigManager()

# 默认参数（当 user_config.json 中无配置时使用）
DEFAULT_PARAMS = {
    "EMA_SHORT": 3,
    "EMA_MID": 7,
    "EMA_LONG": 13,
    "RSI_PERIOD": 6,
    "RSI_LONG_THRESHOLD": 55,
    "RSI_SHORT_THRESHOLD": 45,
    "RSI_LONG_MAX": 75,
    "RSI_SHORT_MIN": 25,
    "RSI_OS_LONG": 30,
    "RSI_OB_SHORT": 70,
    "SIGNAL_COOLDOWN": 20,
    "DIRECTION_LOCK_TIME": 3,
    "STOP_AFTER_LOSS": 20,
    "MAX_CONSECUTIVE_LOSS": 3,
    "PAUSE_AFTER_MAX_LOSS": 180,
    "MIN_RANGE": 2,
    "MAX_RANGE": 30,
    "ATR_SLOPE_FACTOR": 0.08,
    "ATR_BREAKOUT_FACTOR": 0.08,
    "TREND_STRENGTH_HIGH": 0.12,
    "TREND_STRENGTH_LOW": 0.05,
    "MAX_DISTANCE_FROM_LOW": 10,
    "MAX_DISTANCE_FROM_HIGH": 10,
    "EXHAUSTION_COUNT": 5,
    "PULLBACK_MAX_BARS": 2,
    "TREND_STOP_MULT": 0.7,
    "TREND_TAKE_MULT": 1.8,
    "RANGE_STOP_MULT": 0.8,
    "RANGE_TAKE_MULT": 1.0,
    "VOL_MA_PERIOD": 5,
    "VOL_RATIO": 0.6,
    # 新增参数
    "PULLBACK_DISTANCE": 2,
    "ATR_MIN": 2,
    "ATR_MAX": 8,
    "TICK_CONSISTENCY_THRESHOLD": 0.6,
    "TICK_WEIGHT": 0.3,
    "ORDERBOOK_PRESSURE_THRESHOLD": 0.2,
    "ATR_STOP_MULT": 0.7,
    "ATR_TAKE_MULT": 1.2,
    "LONG_TERM_EMA": 20,
    "ACTIVE_IMBALANCE_THRESHOLD": 0.3,
    "ACTIVE_WEIGHT": 1,
}


def get_params():
    user_params = config_mgr.get_strategy_params()
    params = DEFAULT_PARAMS.copy()
    if user_params:
        params.update(user_params)
    int_keys = [
        "EXHAUSTION_COUNT",
        "PULLBACK_MAX_BARS",
        "VOL_MA_PERIOD",
        "RSI_PERIOD",
        "EMA_SHORT",
        "EMA_MID",
        "EMA_LONG",
        "MAX_CONSECUTIVE_LOSS",
        "SIGNAL_COOLDOWN",
        "DIRECTION_LOCK_TIME",
        "STOP_AFTER_LOSS",
        "PAUSE_AFTER_MAX_LOSS",
        "PULLBACK_DISTANCE",
        "LONG_TERM_EMA",
        "ACTIVE_WEIGHT",
    ]
    for key in int_keys:
        if key in params:
            params[key] = int(params[key])
    return params


# 模块级回踩状态（回测用）
_wait_pullback_long = False
_wait_pullback_short = False
_pullback_bars_long = 0
_pullback_bars_short = 0


def round_to_even_price(price):
    """价格最小变动单位为 2 点，统一取最近偶数整数。"""
    return int(round(float(price) / 2) * 2)


def even_points(points, min_points=2):
    """止盈止损点数统一为偶数点。"""
    value = max(min_points, int(round(float(points))))
    return max(2, int(round(value / 2) * 2))


def calculate_atr(high, low, close, period=14):
    close_series = pd.Series(close)
    prev_close = close_series.shift(1).fillna(close[0])
    high_low = high - low
    high_close = np.abs(high - prev_close.values)
    low_close = np.abs(low - prev_close.values)
    tr = np.maximum(high_low, np.maximum(high_close, low_close))
    return float(np.mean(tr[-period:])) if len(tr) >= period else float(np.mean(tr))


def consecutive_count(opens, closes, direction="bull"):
    count = 0
    for o, c in zip(opens[::-1], closes[::-1]):
        if direction == "bull" and c > o:
            count += 1
        elif direction == "bear" and c < o:
            count += 1
        else:
            break
    return count


def calculate_indicators(df: pd.DataFrame) -> dict:
    params = get_params()
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    ema_short = df["close"].ewm(span=params["EMA_SHORT"], adjust=False).mean().iloc[-1]
    ema_mid = df["close"].ewm(span=params["EMA_MID"], adjust=False).mean().iloc[-1]
    ema_long = df["close"].ewm(span=params["EMA_LONG"], adjust=False).mean().iloc[-1]

    if len(df) >= 2:
        ema_mid_prev = df["close"].ewm(span=params["EMA_MID"], adjust=False).mean().iloc[-2]
        ema_slope = ema_mid - ema_mid_prev
    else:
        ema_slope = 0.0

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / params["RSI_PERIOD"], adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / params["RSI_PERIOD"], adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi_series = 100 - (100 / (1 + rs))
    rsi = rsi_series.iloc[-1]
    prev_rsi = rsi_series.iloc[-2] if len(rsi_series) >= 2 else rsi

    recent_range = np.max(close[-5:]) - np.min(close[-5:])
    low_5 = np.min(low[-5:])
    high_5 = np.max(high[-5:])

    atr = calculate_atr(high, low, close, 14)
    atr = max(atr, 0.5)

    dynamic_slope_threshold = max(0.1, atr * params["ATR_SLOPE_FACTOR"])
    ema_mid_up = ema_slope > dynamic_slope_threshold
    ema_mid_down = ema_slope < -dynamic_slope_threshold
    trend_strength = abs(ema_slope) / max(atr, 2)

    opens = df["open"].values
    closes_arr = df["close"].values
    exhaustion_count = params["EXHAUSTION_COUNT"]
    bull_consecutive = consecutive_count(opens[-exhaustion_count:], closes_arr[-exhaustion_count:], "bull")
    bear_consecutive = consecutive_count(opens[-exhaustion_count:], closes_arr[-exhaustion_count:], "bear")

    volume_active = False
    vol_ma_period = params["VOL_MA_PERIOD"]
    if "volume" in df.columns and len(df) >= vol_ma_period:
        vol_ma = df["volume"].rolling(vol_ma_period).mean().iloc[-1]
        last_closed_vol = df["volume"].iloc[-1]
        if vol_ma > 0:
            volume_active = last_closed_vol > vol_ma * params["VOL_RATIO"]

    macd_bullish = ema_mid > ema_long
    macd_bearish = ema_mid < ema_long

    return {
        "ema_short": ema_short,
        "ema_mid": ema_mid,
        "ema_long": ema_long,
        "ema_slope": ema_slope,
        "ema_mid_up": ema_mid_up,
        "ema_mid_down": ema_mid_down,
        "rsi": rsi,
        "prev_rsi": prev_rsi,
        "recent_range": recent_range,
        "low_5": low_5,
        "high_5": high_5,
        "atr": atr,
        "breakout_margin": 0,
        "bull_consecutive": bull_consecutive,
        "bear_consecutive": bear_consecutive,
        "trend_strength": trend_strength,
        "volume_active": volume_active,
        "trend": "上涨" if ema_mid > ema_long else "下跌" if ema_mid < ema_long else "震荡",
        "support": low_5,
        "resistance": high_5,
        "macd_bullish": macd_bullish,
        "macd_bearish": macd_bearish,
    }


def is_active_time():
    return True


def local_trade_rule(df: pd.DataFrame, state: RuntimeState, tick_indicators: dict = None):
    global _wait_pullback_long, _wait_pullback_short, _pullback_bars_long, _pullback_bars_short
    if tick_indicators is None:
        tick_indicators = {}
    params = get_params()

    if len(df) < 15:
        return None
    if not is_active_time():
        return None
    if state.is_daily_loss_limit():
        return None

    pos, _ = state.get_position()
    if pos is not None:
        return None

    current_price = df.iloc[-1]["close"]
    current_candle_time = None
    if "timestamp" in df.columns:
        try:
            current_candle_time = pd.Timestamp(df.iloc[-1]["timestamp"])
        except:
            pass

    ind = calculate_indicators(df)

    if ind["atr"] < params["ATR_MIN"] or ind["atr"] > params["ATR_MAX"]:
        return None

    risk = state.get_risk_state()
    now = time.time()

    if state.consecutive_losses >= params["MAX_CONSECUTIVE_LOSS"]:
        if now - state.last_stopout_time < params["PAUSE_AFTER_MAX_LOSS"]:
            return None
        else:
            state.consecutive_losses = 0

    if current_candle_time is not None and state.last_signal_candle_time is not None:
        elapsed = abs((current_candle_time - state.last_signal_candle_time).total_seconds())
        if elapsed < params["SIGNAL_COOLDOWN"]:
            return None
    else:
        if now - risk["last_signal_time"] < params["SIGNAL_COOLDOWN"]:
            return None

    if now - risk["last_stopout_time"] < params["STOP_AFTER_LOSS"]:
        return None

    if ind["recent_range"] < params["MIN_RANGE"]:
        return None
    if ind["recent_range"] > params["MAX_RANGE"]:
        return None

    pullback_max = params["PULLBACK_MAX_BARS"]
    if _wait_pullback_long:
        _pullback_bars_long += 1
        if _pullback_bars_long > pullback_max:
            _wait_pullback_long = False
            _pullback_bars_long = 0
    if _wait_pullback_short:
        _pullback_bars_short += 1
        if _pullback_bars_short > pullback_max:
            _wait_pullback_short = False
            _pullback_bars_short = 0

    if ind["trend_strength"] > params["TREND_STRENGTH_HIGH"]:
        regime = "trend"
        required_score = 4
    elif ind["trend_strength"] < params["TREND_STRENGTH_LOW"]:
        regime = "range"
        required_score = 0
    else:
        regime = "transition"
        required_score = 4

    if regime == "range":
        return _range_reversal_strategy(ind, current_price, state, current_candle_time, tick_indicators)
    return _trend_breakout_strategy(ind, current_price, state, required_score, current_candle_time, tick_indicators)


def _trend_breakout_strategy(ind, current_price, state, required_score, current_candle_time=None, tick_indicators=None):
    if tick_indicators is None:
        tick_indicators = {}
    params = get_params()
    stop_points = even_points(ind["atr"] * params["TREND_STOP_MULT"], 2)
    take_points = even_points(ind["atr"] * params["TREND_TAKE_MULT"], 4)

    ema7 = ind["ema_mid"]
    ema13 = ind["ema_long"]
    trend_up = ema7 > ema13 and ind["ema_slope"] > 0
    trend_down = ema7 < ema13 and ind["ema_slope"] < 0

    if ind["rsi"] > 85:
        return None
    if ind["rsi"] < 15:
        return None

    exhaustion = params["EXHAUSTION_COUNT"]
    if ind["bull_consecutive"] >= exhaustion:
        return None
    if ind["bear_consecutive"] >= exhaustion:
        return None

    if not ind["volume_active"]:
        return None

    tick_speed = tick_indicators.get("speed", 0.0)
    tick_momentum = tick_indicators.get("momentum", 0.0)
    tick_acceleration = tick_indicators.get("acceleration", 0.0)
    tick_burst = tick_indicators.get("burst", False)
    tick_strength = tick_indicators.get("strength", 0.0)
    tick_consistency = tick_indicators.get("consistency", 0.5)
    orderbook_pressure = tick_indicators.get("orderbook_pressure", 0.0)
    active_imbalance = tick_indicators.get("active_imbalance", 0.0)

    long_score = 0
    short_score = 0
    distance_to_ema = abs(current_price - ema7)

    pullback_long = current_price >= ema7 and current_price <= ema7 + 2
    pullback_short = current_price <= ema7 and current_price >= ema7 - 2

    if trend_up and pullback_long:
        if current_price > ema7:
            long_score += 2
        if ind["ema_mid_up"]:
            long_score += 2
        if ind["rsi"] > params["RSI_LONG_THRESHOLD"]:
            long_score += 1
        if (current_price - ind["low_5"]) < params["MAX_DISTANCE_FROM_LOW"]:
            long_score += 1
        if tick_momentum > 0:
            long_score += 0.3
        if tick_speed > 2.0:
            long_score += 0.3
        if tick_acceleration > 0:
            long_score += 0.3
        if tick_burst and tick_momentum > 0:
            long_score += 0.3
        if tick_strength > 0.7:
            long_score += 0.3
        if tick_consistency > 0.6:
            long_score += 0.3
        if orderbook_pressure > 0.2:
            long_score += 0.3
        if active_imbalance > 0.3:
            long_score += 1

    if trend_down and pullback_short:
        if current_price < ema7:
            short_score += 2
        if ind["ema_mid_down"]:
            short_score += 2
        if ind["rsi"] < params["RSI_SHORT_THRESHOLD"]:
            short_score += 1
        if (ind["high_5"] - current_price) < params["MAX_DISTANCE_FROM_HIGH"]:
            short_score += 1
        if tick_momentum < 0:
            short_score += 0.3
        if tick_speed < -2.0:
            short_score += 0.3
        if tick_acceleration < 0:
            short_score += 0.3
        if tick_burst and tick_momentum < 0:
            short_score += 0.3
        if tick_strength < -0.7:
            short_score += 0.3
        if tick_consistency > 0.6:
            short_score += 0.3
        if orderbook_pressure < -0.2:
            short_score += 0.3
        if active_imbalance < -0.3:
            short_score += 1

    if trend_up and pullback_long and long_score >= required_score:
        entry = round_to_even_price(current_price)
        stop = entry - stop_points
        take = entry + take_points
        signal = {"side": "LONG", "entry": entry, "stop": stop, "take": take, "reason": "趋势突破做多"}
        state.record_signal("LONG", entry, stop, take, "趋势突破做多")
        if current_candle_time is not None:
            state.last_signal_candle_time = current_candle_time
        return signal

    if trend_down and pullback_short and short_score >= required_score:
        entry = round_to_even_price(current_price)
        stop = entry + stop_points
        take = entry - take_points
        signal = {"side": "SHORT", "entry": entry, "stop": stop, "take": take, "reason": "趋势突破做空"}
        state.record_signal("SHORT", entry, stop, take, "趋势突破做空")
        if current_candle_time is not None:
            state.last_signal_candle_time = current_candle_time
        return signal

    return None


def _range_reversal_strategy(ind, current_price, state, current_candle_time=None, tick_indicators=None):
    if tick_indicators is None:
        tick_indicators = {}
    params = get_params()
    stop_points = even_points(ind["atr"] * params["RANGE_STOP_MULT"], 2)
    take_points = even_points(ind["atr"] * params["RANGE_TAKE_MULT"], 4)

    rsi_rising = ind["rsi"] > ind["prev_rsi"] and ind["prev_rsi"] < params["RSI_OS_LONG"]
    rsi_falling = ind["rsi"] < ind["prev_rsi"] and ind["prev_rsi"] > params["RSI_OB_SHORT"]

    if rsi_rising and ind["rsi"] < 50:
        entry = round_to_even_price(current_price)
        stop = entry - stop_points
        take = entry + take_points
        signal = {"side": "LONG", "entry": entry, "stop": stop, "take": take, "reason": "横盘反转做多"}
        state.record_signal("LONG", entry, stop, take, "横盘反转做多")
        if current_candle_time is not None:
            state.last_signal_candle_time = current_candle_time
        return signal
    if rsi_falling and ind["rsi"] > 50:
        entry = round_to_even_price(current_price)
        stop = entry + stop_points
        take = entry - take_points
        signal = {"side": "SHORT", "entry": entry, "stop": stop, "take": take, "reason": "横盘反转做空"}
        state.record_signal("SHORT", entry, stop, take, "横盘反转做空")
        if current_candle_time is not None:
            state.last_signal_candle_time = current_candle_time
        return signal
    return None


def explain_analysis(ind, current_price, signal=None):
    lines = []
    lines.append("📖 当前行情通俗解读：")
    lines.append(f"当前价格：{current_price}")
    ema7 = ind["ema_mid"]
    if current_price > ema7:
        lines.append(f"价格在 EMA7（过去7分钟的均价 {ema7:.1f}）之上，短期走势偏强。")
    else:
        lines.append(f"价格在 EMA7（过去7分钟的均价 {ema7:.1f}）之下，短期走势偏弱。")
    slope = ind["ema_slope"]
    if slope > 0.3:
        lines.append(f"EMA7 正在以较快速度上升（斜率 {slope:.2f}），说明上涨动能较足。")
    elif slope < -0.3:
        lines.append(f"EMA7 正在以较快速度下降（斜率 {slope:.2f}），说明下跌动能较足。")
    else:
        lines.append(f"EMA7 走势平缓（斜率 {slope:.2f}），方向不明确，市场可能处于震荡。")
    rsi = ind["rsi"]
    if rsi > 70:
        lines.append(f"RSI（相对强弱指标）为 {rsi:.1f}，处于超买区域，短期可能回调。")
    elif rsi < 30:
        lines.append(f"RSI（相对强弱指标）为 {rsi:.1f}，处于超卖区域，短期可能反弹。")
    else:
        lines.append(f"RSI 为 {rsi:.1f}，处于中性区间，没有明显的超买或超卖信号。")
    atr = ind["atr"]
    lines.append(f"当前市场波动（ATR）约为 {atr:.1f} 点，说明每根K线平均波动幅度在这个范围内。")
    if ind["trend_strength"] > 0.12:
        regime = "趋势"
    elif ind["trend_strength"] < 0.05:
        regime = "震荡"
    else:
        regime = "过渡期"
    lines.append(f"市场处于{regime}行情（趋势强度 {ind['trend_strength']:.3f}）。")
    if signal:
        side = signal.get("side", "HOLD")
        reason = signal.get("reason", "")
        if side == "LONG":
            lines.append(f"系统建议：做多（{reason}）")
        elif side == "SHORT":
            lines.append(f"系统建议：做空（{reason}）")
        else:
            lines.append("系统建议：暂时观望（HOLD）")
    else:
        lines.append("系统建议：暂时观望（HOLD）")
    return "\n".join(lines)


def run_ai_analysis(df: pd.DataFrame, state: RuntimeState):
    if len(df) < 14:
        return None
    ind = calculate_indicators(df)
    cp = df.iloc[-1]["close"]
    prompt = f"价格 {cp}，趋势 {ind['trend']}，RSI {ind['rsi']:.1f}，波动 {ind['recent_range']}。请给出简短交易建议。"
    try:
        resp = ai_client.analyze(prompt)
        return f"{resp}"
    except Exception as e:
        return "AI 分析失败"


# ==================== 状态机驱动入场函数 ====================
def _current_candle_time(df):
    if "timestamp" not in df.columns:
        return None
    try:
        return pd.Timestamp(df.iloc[-1]["timestamp"])
    except Exception:
        return None


def _pass_common_signal_filters(df, state, ind, params, current_candle_time):
    if not is_active_time():
        return False
    if state.is_daily_loss_limit():
        return False
    pos, _ = state.get_position()
    if pos is not None:
        return False
    if ind["atr"] < params["ATR_MIN"] or ind["atr"] > params["ATR_MAX"]:
        return False
    if ind["rsi"] > params["RSI_LONG_MAX"] or ind["rsi"] < params["RSI_SHORT_MIN"]:
        return False
    if ind["bull_consecutive"] >= params["EXHAUSTION_COUNT"]:
        return False
    if ind["bear_consecutive"] >= params["EXHAUSTION_COUNT"]:
        return False
    if ind["recent_range"] < params["MIN_RANGE"] or ind["recent_range"] > params["MAX_RANGE"]:
        return False

    now = time.time()
    if state.consecutive_losses >= params["MAX_CONSECUTIVE_LOSS"]:
        if now - state.last_stopout_time < params["PAUSE_AFTER_MAX_LOSS"]:
            return False
        state.consecutive_losses = 0

    risk = state.get_risk_state()
    if current_candle_time is not None and state.last_signal_candle_time is not None:
        elapsed = abs((current_candle_time - state.last_signal_candle_time).total_seconds())
        if elapsed < params["SIGNAL_COOLDOWN"]:
            return False
    elif now - risk["last_signal_time"] < params["SIGNAL_COOLDOWN"]:
        return False

    if now - risk["last_stopout_time"] < params["STOP_AFTER_LOSS"]:
        return False
    return True


def _build_signal(state, side, entry_price, stop_points, take_points, reason, current_candle_time):
    entry = round_to_even_price(entry_price)
    if side == "LONG":
        stop = entry - stop_points
        take = entry + take_points
    else:
        stop = entry + stop_points
        take = entry - take_points

    signal = {"side": side, "entry": entry, "stop": stop, "take": take, "reason": reason}
    state.record_signal(side, entry, stop, take, reason)
    if current_candle_time is not None:
        state.last_signal_candle_time = current_candle_time
    return signal


def state_based_trade_rule(df, state, tick_indicators, market_state):
    """状态机驱动交易：EMA 回调 + tick 动量 + 主动买卖确认。"""
    params = get_params()
    if tick_indicators is None:
        tick_indicators = {}
    if len(df) < 30:
        return None

    ind = calculate_indicators(df)
    current_candle_time = _current_candle_time(df)
    if not _pass_common_signal_filters(df, state, ind, params, current_candle_time):
        return None

    current_price = float(df.iloc[-1]["close"])
    ema_fast = ind["ema_mid"]
    ema30 = df["close"].ewm(span=30, adjust=False).mean().iloc[-1]
    trend_up = current_price > ema30 and ema_fast > ema30
    trend_down = current_price < ema30 and ema_fast < ema30

    pullback_dist = params.get("PULLBACK_DISTANCE", 2)
    stop_points = even_points(ind["atr"] * params.get("ATR_STOP_MULT", 0.8), 2)
    take_points = even_points(ind["atr"] * params.get("ATR_TAKE_MULT", 1.5), 4)

    tick_mom = tick_indicators.get("momentum", 0)
    tick_consistency = tick_indicators.get("consistency", 0.5)
    active_imbalance = tick_indicators.get("active_imbalance", 0)
    active_threshold = params.get("ACTIVE_IMBALANCE_THRESHOLD", 0.3)
    consistency_threshold = params.get("TICK_CONSISTENCY_THRESHOLD", 0.6)

    near_ema = abs(current_price - ema_fast) <= pullback_dist

    if market_state in ("EARLY_LONG", "TREND_LONG", "STRONG_LONG"):
        if trend_up and near_ema and current_price >= ema_fast:
            if tick_mom > 0 and tick_consistency >= consistency_threshold and active_imbalance >= active_threshold:
                return _build_signal(
                    state,
                    "LONG",
                    current_price,
                    stop_points,
                    take_points,
                    f"回调+tick+主动确认 ({market_state})",
                    current_candle_time,
                )

    if market_state in ("EARLY_SHORT", "TREND_SHORT", "STRONG_SHORT"):
        if trend_down and near_ema and current_price <= ema_fast:
            if tick_mom < 0 and tick_consistency >= consistency_threshold and active_imbalance <= -active_threshold:
                return _build_signal(
                    state,
                    "SHORT",
                    current_price,
                    stop_points,
                    take_points,
                    f"回调+tick+主动确认 ({market_state})",
                    current_candle_time,
                )

    return None
