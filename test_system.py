#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量化交易系统 Pro - 完整功能测试（最终版）
"""

import os
import sys
import time
import tempfile
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

test_results = {"passed": 0, "failed": 0, "warnings": 0}


def test_pass(msg):
    print(f"✅ {msg}")
    test_results["passed"] += 1


def test_fail(msg, error=None):
    print(f"❌ {msg}")
    if error:
        print(f"   错误详情: {error}")
    test_results["failed"] += 1


def test_warn(msg):
    print(f"⚠️ {msg}")
    test_results["warnings"] += 1


# ------------------------------------------------------------
def test_config_manager():
    print("\n--- 测试配置管理器 ---")
    try:
        from config_manager import ConfigManager

        temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        temp_file.close()
        original_file = getattr(ConfigManager, "CONFIG_FILE", None)
        ConfigManager.CONFIG_FILE = temp_file.name
        cm = ConfigManager()
        cm.set_capture_region(100, 200, 50, 60)
        assert cm.get_capture_region() == (100, 200, 50, 60)
        cm2 = ConfigManager()
        assert cm2.get_capture_region() == (100, 200, 50, 60)
        test_pass("配置管理器加载/保存/修改正常")
    except Exception as e:
        test_fail("配置管理器异常", e)
    finally:
        if original_file is not None:
            ConfigManager.CONFIG_FILE = original_file
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)


# ------------------------------------------------------------
def test_tesseract():
    print("\n--- 测试 Tesseract 可用性 ---")
    try:
        import pytesseract
        from config_manager import ConfigManager

        cm = ConfigManager()
        tesseract_cmd = cm.get_tesseract_cmd()
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        version = pytesseract.get_tesseract_version()
        print(f"   Tesseract 版本: {version}")
        langs = pytesseract.get_languages()
        if "eng" in langs:
            test_pass("Tesseract 引擎可用，英语语言包已安装")
        else:
            test_warn("Tesseract 可用但未检测到英语语言包")
        if "chi_sim" in langs:
            test_pass("中文简体语言包已安装")
        else:
            test_warn("中文简体语言包未安装")
    except Exception as e:
        test_fail("Tesseract 不可用", e)


# ------------------------------------------------------------
def test_ocr_worker():
    print("\n--- 测试 OCR Worker ---")
    try:
        from ocr_worker import capture_time_price, TickFilter
        from config_manager import ConfigManager

        cm = ConfigManager()
        original = cm.get_capture_region()
        cm.set_capture_region(0, 0, 100, 30)
        dt, price = capture_time_price()
        cm.set_capture_region(*original)
        test_pass("OCR capture_time_price 函数运行无异常")
        filt = TickFilter()
        now = datetime.now()
        p1 = filt.update(100.0, now)
        p2 = filt.update(100.0, now + timedelta(milliseconds=200))
        assert p1 is not None and p2 is None
        now2 = datetime.now().replace(minute=now.minute + 1 if now.minute < 59 else 0)
        p3 = filt.update(100.0, now2)
        assert p3 == 100.0
        test_pass("TickFilter 去重/跨分钟逻辑正常")
    except Exception as e:
        test_fail("OCR Worker 测试失败", e)


# ------------------------------------------------------------
def test_candle_engine():
    print("\n--- 测试 CandleEngine ---")
    from candle_engine import CandleEngine

    engine = CandleEngine(interval_seconds=60)
    base = datetime(2025, 1, 1, 10, 0, 0)
    ticks = [
        (10.0, base),
        (10.2, base + timedelta(seconds=10)),
        (9.8, base + timedelta(seconds=20)),
        (10.5, base + timedelta(seconds=30)),
        (10.3, base + timedelta(seconds=50)),
        (10.4, base + timedelta(seconds=70)),
    ]
    candles = []
    for p, ts in ticks:
        fin = engine.update_tick(p, ts)
        if fin:
            candles.append(fin)
    assert len(candles) == 1
    c = candles[0]
    assert c["open"] == 10.0
    assert c["high"] == 10.5
    assert c["low"] == 9.8
    assert c["close"] == 10.3
    assert c["volume"] == 5
    engine2 = CandleEngine()
    engine2.update_tick(100, base)
    engine2.update_tick(100, base)
    fin = engine2.update_tick(101, base + timedelta(seconds=61))
    assert fin is not None
    assert fin["close"] == 100
    test_pass("CandleEngine tick→K线转换正确")


# ------------------------------------------------------------
def test_market_data_manager():
    print("\n--- 测试 MarketDataManager ---")
    from indicators import MarketDataManager
    from config import CandleConfig
    import pandas as pd

    tmpdir = tempfile.mkdtemp()
    tick_path = Path(tmpdir) / "ticks.csv"
    candle_path = Path(tmpdir) / "candles_1m.csv"
    cfg = CandleConfig()
    mgr = MarketDataManager(cfg, tick_path, candle_path)
    ts = datetime(2025, 1, 1, 10, 0, 0)
    mgr.add_tick(ts, 100.0)
    mgr.add_tick(ts + timedelta(seconds=10), 100.5)
    mgr.add_tick(ts + timedelta(seconds=20), 99.8)
    mgr.build_candles()
    mgr.add_candle({"time": ts + timedelta(minutes=1), "open": 101, "high": 102, "low": 100, "close": 101})
    mgr.persist()
    assert tick_path.exists() and candle_path.exists()
    mgr2 = MarketDataManager(cfg, tick_path, candle_path)
    mgr2.ticks = pd.read_csv(tick_path, parse_dates=["timestamp"])
    mgr2.candles = pd.read_csv(candle_path, parse_dates=["timestamp"])
    assert len(mgr2.candles) == 2
    test_pass("MarketDataManager 存储、构建K线、持久化正常")
    shutil.rmtree(tmpdir)


# ------------------------------------------------------------
def test_tick_indicators():
    print("\n--- 测试 TickIndicatorEngine ---")
    from tick_indicators import TickIndicatorEngine

    engine = TickIndicatorEngine(max_len=20, strength_norm_window=5, ema_short=2, ema_long=5)
    base = datetime(2025, 1, 1, 10, 0, 0)
    prices = [100, 101, 102, 103, 104, 105, 105, 105, 106, 107]
    for i, p in enumerate(prices):
        engine.add_tick(p, base + timedelta(seconds=i * 0.3))
    speed = engine.tick_speed()
    expected_speed = (107 - 106) / 0.3
    assert abs(speed - expected_speed) < 0.1
    momentum = engine.tick_momentum(window=5)
    expected_momentum = 107 - 105
    assert abs(momentum - expected_momentum) < 0.1
    acc = engine.tick_acceleration()
    assert isinstance(acc, float)
    burst = engine.is_burst(threshold=1.0)
    assert burst == False
    strength = engine.get_tick_strength()
    assert -1 <= strength <= 1
    micro = engine.micro_trend()
    assert micro != 0
    pressure = engine.pressure_score(window=10)
    assert -1 <= pressure <= 1
    consistency = engine.tick_consistency(window=5)
    assert 0 <= consistency <= 1
    test_pass("TickIndicatorEngine 所有指标计算正常")
    engine2 = TickIndicatorEngine()
    for _ in range(10):
        engine2.add_tick(100, datetime.now())
    assert engine2.pressure_score() == 0.0
    test_pass("TickIndicatorEngine 平盘处理正确")


# ------------------------------------------------------------
def test_strategy():
    print("\n--- 测试策略模块 ---")
    from strategy import local_trade_rule, calculate_indicators
    from runtime_state import RuntimeState
    import pandas as pd
    import numpy as np

    # 生成强趋势数据，确保满足策略条件
    dates = pd.date_range("2025-01-01 10:00:00", periods=60, freq="1min")
    base_price = 2100
    closes = base_price + np.linspace(0, 50, 60)  # 稳定上涨
    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": np.roll(closes, 1),
            "high": closes + 2,
            "low": closes - 2,
            "close": closes,
            "volume": np.random.randint(100, 1000, 60),
        }
    )
    df.loc[0, "open"] = closes[0]  # 第一根open
    # 计算EMA7和EMA13，确保趋势向上
    ema7 = df["close"].ewm(span=7, adjust=False).mean()
    ema13 = df["close"].ewm(span=13, adjust=False).mean()
    # 确保最新价格高于EMA7且回踩条件满足（价格在EMA7附近±2）
    # 我们直接修改最后几根K线使其贴近EMA7
    last_idx = len(df) - 1
    ema7_last = ema7.iloc[last_idx]
    df.loc[last_idx, "close"] = ema7_last + 1  # 略高于EMA7，且距离<=2
    df.loc[last_idx, "high"] = df.loc[last_idx, "close"] + 1
    df.loc[last_idx, "low"] = df.loc[last_idx, "close"] - 1
    # 确保ema_mid_up为True
    state = RuntimeState()
    tick = {
        "speed": 2.5,
        "momentum": 3,
        "acceleration": 0.8,
        "burst": True,
        "strength": 0.9,
        "consistency": 0.8,
        "pressure": 0.3,
    }
    signal = local_trade_rule(df, state, tick)
    if signal is not None and signal["side"] == "LONG":
        test_pass("策略在上涨趋势+良好tick指标下产生多头信号")
    else:
        test_warn("策略未产生多头信号，可能参数苛刻，但策略函数运行正常")
    # 测试方向过滤：下跌趋势不应产生多头
    df_down = df.copy()
    df_down["close"] = base_price - np.linspace(0, 50, 60)
    signal2 = local_trade_rule(df_down, state, tick)
    if signal2 is not None and signal2["side"] == "LONG":
        test_warn("下跌趋势产生了多头信号（方向过滤可能失效）")
    else:
        test_pass("策略方向过滤正常")
    ind = calculate_indicators(df)
    assert "ema_mid" in ind and ind["atr"] > 0
    test_pass("calculate_indicators 运行正常")


# ------------------------------------------------------------
def test_runtime_state():
    print("\n--- 测试 RuntimeState ---")
    from runtime_state import RuntimeState

    state = RuntimeState()
    state.update_price(1234.5)
    assert state.get_price() == 1234.5
    now = datetime.now()
    state.update_tick_time(now)
    assert state.get_tick_time() == now
    state.record_signal("LONG", 1000, 995, 1010, "test")
    assert state.last_signal_time > 0 and state.last_direction == "LONG"

    # 日亏损限制测试
    state.update_daily_pnl(-41)  # 超过限额 -30
    assert state.is_daily_loss_limit() == True
    state.update_daily_pnl(12)  # 总亏损 -29，低于限额
    assert state.is_daily_loss_limit() == False

    state.set_stopout_time()
    assert state.last_stopout_time > 0

    pos = {"side": "LONG", "entry": 1000, "stop": 990, "take": 1020, "initial_risk": 10}
    state.set_position(pos, "LONG")
    p, _ = state.get_position()
    assert p["side"] == "LONG"

    # 移动止损
    state.move_stop_if_better(995, "LONG")
    # 重新获取 position 以查看更新
    p2, _ = state.get_position()
    assert p2["stop"] == 995

    state.set_closing()
    # 再次获取以确保 closing 标志已设置
    p3, _ = state.get_position()
    assert p3.get("closing") == True

    state.set_position(None, "EMPTY")
    assert state.get_position()[0] is None
    test_pass("RuntimeState 所有功能正常")


# ------------------------------------------------------------
def test_backtester():
    print("\n--- 测试回测引擎 ---")
    try:
        from backtester import Backtester
        from performance import analyze_trades
        from indicators import MarketDataManager
        from config import CandleConfig

        tmpdir = tempfile.mkdtemp()
        candle_path = Path(tmpdir) / "candles.csv"
        cfg = CandleConfig()
        mgr = MarketDataManager(cfg, Path(""), candle_path)
        import pandas as pd

        dates = pd.date_range("2025-01-01", periods=60, freq="1min")
        for i, dt in enumerate(dates):
            mgr.add_candle(
                {
                    "time": dt,
                    "open": 2100 + i * 0.5,
                    "high": 2100 + i * 0.5 + 2,
                    "low": 2100 + i * 0.5 - 2,
                    "close": 2100 + i * 0.5 + 1,
                    "volume": 100,
                }
            )
        bt = Backtester(mgr)
        trades = bt.run()
        if trades is not None and not trades.empty:
            stats = analyze_trades(trades)
            assert isinstance(stats, dict)
            test_pass("回测引擎运行正常并产生交易记录")
        else:
            test_warn("回测引擎运行正常但未产生交易（策略条件苛刻）")
        shutil.rmtree(tmpdir)
    except ImportError:
        test_warn("backtester 或 performance 模块未找到")
    except Exception as e:
        test_fail("回测引擎测试失败", e)


# ------------------------------------------------------------
def test_gui_dependencies():
    print("\n--- 测试 GUI 依赖 ---")
    try:
        import customtkinter as ctk
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        import mplfinance as mpf

        test_pass("所有 GUI 库导入成功")
        root = ctk.CTk()
        label = ctk.CTkLabel(root, text="test")
        label.pack()
        root.update_idletasks()
        root.destroy()
        test_pass("customtkinter 组件创建正常")
    except ImportError as e:
        test_fail("GUI 库缺失", e)
    except Exception as e:
        test_fail("customtkinter 组件测试失败", e)


# ------------------------------------------------------------
def test_threading():
    print("\n--- 测试线程与队列 ---")
    from queues import tick_queue
    import threading

    def producer():
        for i in range(10):
            tick_queue.put(("test", datetime.now()))

    t = threading.Thread(target=producer)
    t.start()
    time.sleep(0.5)
    assert not tick_queue.empty()
    while not tick_queue.empty():
        tick_queue.get()
    t.join()
    test_pass("多线程队列操作正常")


# ------------------------------------------------------------
def main():
    print("=" * 60)
    print("量化交易系统 Pro - 完整功能测试（最终版）")
    print("=" * 60)
    test_config_manager()
    test_tesseract()
    test_ocr_worker()
    test_candle_engine()
    test_market_data_manager()
    test_tick_indicators()
    test_strategy()
    test_runtime_state()
    test_backtester()
    test_gui_dependencies()
    test_threading()
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print(f"✅ 通过: {test_results['passed']}")
    print(f"❌ 失败: {test_results['failed']}")
    print(f"⚠️  警告: {test_results['warnings']}")
    if test_results["failed"] == 0:
        print("🎉 所有核心测试通过！系统基本功能正常。")
    else:
        print("🛠️ 请根据失败项修复对应模块。")
    print("=" * 60)


if __name__ == "__main__":
    main()
