"""
量化交易系统 GUI 版 - 最终纯净版（折线图，无 mplfinance 警告）
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
import time
import queue
import sys
import os
from datetime import datetime, timezone

if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

import win32gui
import win32con
import win32api

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd

from runtime_state import RuntimeState
from queues import tick_queue, candle_queue, signal_queue
from ocr_worker import run_ocr_worker
from candle_worker import run_candle_worker
from analysis_worker import run_analysis_worker
from risk_worker import risk_worker

from data_manager import MarketDataManager
from config import CandleConfig, AppConfig

from config_manager import ConfigManager
from realtime_regions_dialog import RealTimeRegionsDialog
from prompt_editor import PromptEditor
from strategy_settings_dialog import StrategySettingsDialog
from history_viewer import HistoryViewerDialog
from kline_chart import KlineChartWindow
from ohlc_settings_dialog import OHLCSettingsDialog
import kline_ocr_scraper
import strategy
import analysis_worker
import candle_worker
import risk_worker as rw

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

config_mgr = ConfigManager()
candle_cfg = CandleConfig()
app_cfg = AppConfig()
data_mgr = MarketDataManager(candle_cfg, app_cfg.tick_csv, app_cfg.candle_csv)
data_mgr_ref = [data_mgr]

analysis_worker.data_mgr = data_mgr
candle_worker.data_mgr = data_mgr

state = RuntimeState()
stop_event = threading.Event()
gui_queue = queue.Queue(maxsize=1000)
system_running = False

MANUAL_STOP_POINTS = 4
MANUAL_TAKE_POINTS = 6

TRADING_WINDOW_TITLE = "华中九通"
TRADING_WINDOW_WIDTH = 957
TRADING_WINDOW_HEIGHT = 569


def set_trading_window_topmost():
    hwnd = None

    def callback(hwnd_enum, _):
        nonlocal hwnd
        if win32gui.IsWindowVisible(hwnd_enum):
            title = win32gui.GetWindowText(hwnd_enum)
            if TRADING_WINDOW_TITLE in title:
                hwnd = hwnd_enum
                return False

    win32gui.EnumWindows(callback, None)
    if hwnd is None:
        messagebox.showwarning("未找到窗口", f"未找到包含 '{TRADING_WINDOW_TITLE}' 的窗口")
        return False
    screen_width = win32api.GetSystemMetrics(0)
    x = screen_width - TRADING_WINDOW_WIDTH
    y = 0
    win32gui.SetWindowPos(
        hwnd, win32con.HWND_TOPMOST, x, y, TRADING_WINDOW_WIDTH, TRADING_WINDOW_HEIGHT, win32con.SWP_SHOWWINDOW
    )
    return True


class TradingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("量化交易系统 Pro")
        self.root.geometry("950x950")
        self.root.minsize(700, 800)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.threads = []
        self.signal_thread = None
        self.last_chart_update = 0
        self.analysis_lock = threading.Lock()
        self.tick_engine = None
        self.history_loading = False

        self.create_widgets()
        self.update_gui()
        self.update_button_states(start_enabled=True, stop_enabled=False)

    def log(self, msg):
        try:
            gui_queue.put_nowait(("log", str(msg) + "\n"))
        except queue.Full:
            pass

    def update_button_states(self, start_enabled=None, stop_enabled=None):
        if start_enabled is not None:
            self.btn_start.configure(state="normal" if start_enabled else "disabled")
        if stop_enabled is not None:
            self.btn_stop.configure(state="normal" if stop_enabled else "disabled")
        if self.history_loading:
            self.btn_init.configure(state="disabled")
        else:
            self.btn_init.configure(state="normal")

    def create_widgets(self):
        self.main_container = ctk.CTkFrame(self.root, fg_color="#f1f5f9")
        self.main_container.pack(fill="both", expand=True, padx=5, pady=5)

        # 顶部价格与状态
        self.price_card = ctk.CTkFrame(self.main_container, height=70, corner_radius=12, fg_color="#2563eb")
        self.price_card.pack(fill="x", padx=5, pady=(5, 3))
        self.price_label = ctk.CTkLabel(
            self.price_card, text="2174.00", font=("微软雅黑", 40, "bold"), text_color="white"
        )
        self.price_label.pack(side="left", padx=20, pady=8)
        self.time_label = ctk.CTkLabel(
            self.price_card, text="--:--:--", font=("微软雅黑", 18, "bold"), text_color="#dcfce7"
        )
        self.time_label.pack(side="left", padx=20, pady=8)
        self.status_label = ctk.CTkLabel(
            self.price_card, text="⚫ 未启动", font=("微软雅黑", 15, "bold"), text_color="#f1f5f9"
        )
        self.status_label.pack(side="right", padx=20)

        # 按钮行1
        self.btn_row1 = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.btn_row1.pack(fill="x", padx=5, pady=5)
        self.btn_start = self.create_compact_button(self.btn_row1, "▶启动", self.start_system, "#2563eb", 15)
        self.btn_stop = self.create_compact_button(self.btn_row1, "⏹停止", self.stop_system, "#ef4444", 15)
        self.btn_init = self.create_compact_button(self.btn_row1, "📈初始", self.init_history, "#10b981", 15)
        self.create_compact_button(self.btn_row1, "🔄分析", self.force_analysis, "#f59e0b", 15)
        self.create_compact_button(self.btn_row1, "📉K线", self.open_kline_chart, "#8b5cf6", 15)
        self.create_compact_button(self.btn_row1, "📌置顶", self.top_window, "#06b6d4", 15)
        self.create_compact_button(self.btn_row1, "🧠AI", self.ai_mode, "#8b5cf6", 15)
        self.create_compact_button(self.btn_row1, "📊本地", self.local_mode, "#10b981", 15)
        self.create_compact_button(self.btn_row1, "⛔冷却", self.stop_loss, "#ef4444", 15)

        # 按钮行2
        self.btn_row2 = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.btn_row2.pack(fill="x", padx=5, pady=5)
        self.create_compact_button(self.btn_row2, "📁导出", self.export_log, "#6366f1", 15)
        self.create_compact_button(self.btn_row2, "⚙OCR", self.open_realtime_settings, "#64748b", 15)
        self.create_compact_button(self.btn_row2, "🧠提示词", self.open_prompt_editor, "#8b5cf6", 15)
        self.create_compact_button(self.btn_row2, "📈参数", self.open_strategy_settings, "#f59e0b", 15)
        self.create_compact_button(self.btn_row2, "📐OHLC区域", self.open_ohlc_settings, "#10b981", 15)
        self.create_compact_button(self.btn_row2, "🔬回测", self.run_backtest, "#ef4444", 15)
        self.create_compact_button(self.btn_row2, "📋历史K线", self.open_history_viewer, "#6366f1", 15)

        # 中间区域：K线图 + 信号面板
        self.middle_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.middle_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 图表区（纯折线图，无成交量）
        self.chart_frame = ctk.CTkFrame(self.middle_frame, corner_radius=10, fg_color="white")
        self.chart_frame.pack(fill="both", expand=True, padx=0, pady=(0, 5))
        ctk.CTkLabel(self.chart_frame, text="📈 价格走势", font=("微软雅黑", 14, "bold"), text_color="#0f172a").pack(
            anchor="w", padx=10, pady=(5, 0)
        )
        self.fig = plt.Figure(figsize=(6, 2.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=5, pady=5)

        # 信号面板（可滚动）
        self.signal_frame = ctk.CTkFrame(self.middle_frame, corner_radius=10, fg_color="white")
        self.signal_frame.pack(fill="both", expand=True, padx=0, pady=0)
        ctk.CTkLabel(self.signal_frame, text="🧠 交易信号", font=("微软雅黑", 14, "bold"), text_color="#0f172a").pack(
            anchor="center", pady=(5, 0)
        )
        self.signal_scroll = ctk.CTkScrollableFrame(self.signal_frame, fg_color="white", height=180)
        self.signal_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        self.signal_label = ctk.CTkLabel(
            self.signal_scroll, text="HOLD", font=("微软雅黑", 36, "bold"), text_color="#64748b"
        )
        self.signal_label.pack(anchor="center", padx=20, pady=(10, 5))
        self.signal_details = ctk.CTkLabel(
            self.signal_scroll, text="入场: --", font=("微软雅黑", 14), text_color="#334155"
        )
        self.signal_details.pack(anchor="center", padx=20, pady=2)
        self.reason_label = ctk.CTkLabel(
            self.signal_scroll,
            text="等待分析...",
            wraplength=600,
            justify="center",
            font=("微软雅黑", 13),
            text_color="#334155",
        )
        self.reason_label.pack(anchor="center", padx=20)
        self.ai_label = ctk.CTkLabel(
            self.signal_scroll, text="AI: 等待", font=("微软雅黑", 13, "bold"), text_color="#3b82f6"
        )
        self.ai_label.pack(anchor="center", padx=20, pady=2)
        self.explain_label = ctk.CTkLabel(
            self.signal_scroll, text="", wraplength=600, justify="left", font=("微软雅黑", 12), text_color="#475569"
        )
        self.explain_label.pack(anchor="center", padx=20, pady=(5, 0))

        # 指标卡片
        self.info_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.info_container.pack(fill="x", padx=5, pady=5)
        for i in range(6):
            self.info_container.grid_columnconfigure(i, weight=1)
        self.create_metric_card(0, 0, "趋势", "--", "#22c55e", 13, 20)
        self.create_metric_card(0, 1, "RSI", "--", "#3b82f6", 13, 20)
        self.create_metric_card(0, 2, "MACD", "--", "#f59e0b", 13, 20)
        self.create_metric_card(0, 3, "支撑", "--", "#8b5cf6", 13, 20)
        self.create_metric_card(0, 4, "阻力", "--", "#ef4444", 13, 20)
        self.create_metric_card(0, 5, "波动", "--", "#06b6d4", 13, 20)

        # 持仓信息栏
        self.hold_frame = ctk.CTkFrame(self.main_container, corner_radius=10, fg_color="white", height=60)
        self.hold_frame.pack(fill="x", padx=5, pady=5)
        self.hold_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.hold_side_label = ctk.CTkLabel(
            self.hold_frame, text="持仓: 无", font=("微软雅黑", 13), text_color="#64748b"
        )
        self.hold_side_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.hold_time_label = ctk.CTkLabel(
            self.hold_frame, text="持仓时间: 0秒", font=("微软雅黑", 13), text_color="#64748b"
        )
        self.hold_time_label.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        self.hold_pnl_label = ctk.CTkLabel(
            self.hold_frame, text="浮动盈亏: 0.0", font=("微软雅黑", 13), text_color="#64748b"
        )
        self.hold_pnl_label.grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.hold_stop_label = ctk.CTkLabel(
            self.hold_frame, text="止损距离: --", font=("微软雅黑", 13), text_color="#64748b"
        )
        self.hold_stop_label.grid(row=0, column=3, padx=10, pady=5, sticky="w")

        # 手动交易行
        self.trade_row = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.trade_row.pack(fill="x", padx=5, pady=5)
        ctk.CTkButton(
            self.trade_row,
            text="🔴做多",
            command=self.set_long,
            fg_color="#ef4444",
            width=80,
            height=35,
            font=("微软雅黑", 13),
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            self.trade_row,
            text="🔵做空",
            command=self.set_short,
            fg_color="#3b82f6",
            width=80,
            height=35,
            font=("微软雅黑", 13),
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            self.trade_row,
            text="⚪平仓",
            command=self.set_empty,
            fg_color="#64748b",
            width=80,
            height=35,
            font=("微软雅黑", 13),
        ).pack(side="left", padx=5)
        self.manual_price_entry = ctk.CTkEntry(
            self.trade_row, placeholder_text="输入价格", width=120, height=35, font=("微软雅黑", 13)
        )
        self.manual_price_entry.pack(side="left", padx=10)
        ctk.CTkButton(
            self.trade_row,
            text="设置价格",
            command=self.set_manual_price,
            fg_color="#10b981",
            width=90,
            height=35,
            font=("微软雅黑", 13),
        ).pack(side="left", padx=5)

        # 日志区
        self.log_frame = ctk.CTkFrame(self.main_container, corner_radius=10, fg_color="white")
        self.log_frame.pack(fill="both", expand=True, padx=5, pady=(5, 5))
        ctk.CTkLabel(self.log_frame, text="📋 系统日志", font=("微软雅黑", 13, "bold"), text_color="#0f172a").pack(
            anchor="w", padx=10, pady=(5, 0)
        )
        self.log_text = ctk.CTkTextbox(
            self.log_frame, height=120, fg_color="#0f172a", text_color="#e2e8f0", font=("Consolas", 12)
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text._textbox.tag_config("warning", foreground="#ff5555")

        self.progress_bar = ctk.CTkProgressBar(self.log_frame, width=400)
        self.progress_bar.pack(pady=5)
        self.progress_bar.set(0)
        self.progress_bar.pack_forget()

    def create_compact_button(self, parent, text, command, color, font_size=15):
        btn = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color=color,
            height=32,
            width=80,
            corner_radius=8,
            font=("微软雅黑", font_size, "bold"),
        )
        btn.pack(side="left", padx=3)
        return btn

    def create_metric_card(self, row, col, title, value, color, title_font=13, value_font=20):
        card = ctk.CTkFrame(self.info_container, corner_radius=10, fg_color="white", height=70)
        card.grid(row=row, column=col, padx=3, pady=2, sticky="nsew")
        ctk.CTkLabel(card, text=title, font=("微软雅黑", title_font), text_color="#64748b").pack(
            anchor="w", padx=10, pady=(8, 0)
        )
        val_lbl = ctk.CTkLabel(card, text=value, font=("微软雅黑", value_font, "bold"), text_color=color)
        val_lbl.pack(anchor="w", padx=10)
        if title == "趋势":
            self.trend_label = val_lbl
        elif title == "RSI":
            self.rsi_label = val_lbl
        elif title == "MACD":
            self.macd_label = val_lbl
        elif title == "支撑":
            self.support_label = val_lbl
        elif title == "阻力":
            self.resist_label = val_lbl
        elif title == "波动":
            self.range_label = val_lbl

    # ========== 线程管理 ==========
    def start_background_threads(self):
        from tick_indicators import TickIndicatorEngine

        self.tick_engine = TickIndicatorEngine(max_len=200)
        analysis_worker.tick_engine = self.tick_engine
        analysis_worker.gui_queue = gui_queue
        rw.gui_queue = gui_queue
        candle_worker.data_mgr = data_mgr_ref[0]
        analysis_worker.data_mgr = data_mgr_ref[0]
        if self.signal_thread is None or not self.signal_thread.is_alive():
            self.signal_thread = threading.Thread(target=self.signal_monitor, daemon=True)
            self.signal_thread.start()
        self.threads = [
            threading.Thread(target=run_ocr_worker, args=(state, stop_event, self.tick_engine), daemon=True),
            threading.Thread(target=run_candle_worker, args=(state, stop_event), daemon=True),
            threading.Thread(target=run_analysis_worker, args=(state, stop_event), daemon=True),
            threading.Thread(target=rw.risk_worker, args=(state, stop_event), daemon=True),
        ]
        for t in self.threads:
            t.start()

    def start_system(self):
        global system_running
        if system_running:
            self.log("⚠ 系统已经在运行\n")
            return
        alive = any(t.is_alive() for t in self.threads) or (self.signal_thread and self.signal_thread.is_alive())
        if alive:
            self.log("⚠ 检测到残留线程，请先停止\n")
            return
        stop_event.clear()
        self.start_background_threads()
        system_running = True
        self.status_label.configure(text="🟢 运行中")
        self.log("▶ 系统启动成功\n")
        self.update_button_states(start_enabled=False, stop_enabled=True)

    def stop_system(self):
        global system_running
        if not system_running:
            self.log("⚠ 系统未运行\n")
            return
        stop_event.set()
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=0.5)
        if self.signal_thread and self.signal_thread.is_alive():
            self.signal_thread.join(timeout=0.5)
        system_running = False
        self.status_label.configure(text="🔴 已停止")
        self.log("⏹ 系统已停止\n")
        self.update_button_states(start_enabled=True, stop_enabled=False)

    def signal_monitor(self):
        while not stop_event.is_set():
            try:
                signal = signal_queue.get(timeout=0.5)
                if signal:
                    try:
                        gui_queue.put_nowait(("signal", signal))
                    except queue.Full:
                        pass
            except queue.Empty:
                pass
            except Exception as e:
                self.log(f"signal错误: {e}")

    # ========== GUI更新 ==========
    def update_gui(self):
        if not self.root.winfo_exists():
            return
        try:
            while not gui_queue.empty():
                try:
                    msg_type, data = gui_queue.get_nowait()
                except queue.Empty:
                    break
                if msg_type == "signal":
                    self.display_signal(data)
                elif msg_type == "log":
                    self.log_text.insert("end", data)
                    lines = int(self.log_text.index("end-1c").split(".")[0])
                    if lines > 300:
                        self.log_text.delete("1.0", f"{lines-300}.0")
                    self.log_text.see("end")
                elif msg_type == "explain":
                    self.explain_label.configure(text=data)
                elif msg_type == "warning":
                    self.log_text.insert("end", data + "\n", "warning")
                    self.log_text.see("end")
                    original_color = self.status_label.cget("text_color")
                    self.status_label.configure(text_color="orange")
                    self.root.after(3000, lambda: self.status_label.configure(text_color=original_color))
                elif msg_type == "backtest_progress":
                    self.progress_bar.set(data)
                    self.log_text.insert("end", f"回测进度: {int(data*100)}%\n")
                    self.log_text.see("end")
                elif msg_type == "backtest_finished":
                    self.progress_bar.pack_forget()
                    self.log(f"回测完成: {data}\n")
                    messagebox.showinfo("回测完成", data)
                elif msg_type == "ai":
                    self.ai_label.configure(text=f"AI: {data}")
                    self.signal_label.configure(text="AI建议", text_color="#8b5cf6")
                    self.signal_details.configure(text="")
                    self.reason_label.configure(text=data)

            price = state.get_price()
            if price:
                self.price_label.configure(text=f"{price:.2f}")
            tick_time = state.get_tick_time()
            if tick_time:
                self.time_label.configure(text=tick_time.strftime("%H:%M:%S"))

            # 持仓信息
            side, entry, stop, take, hold_seconds, unrealized_pnl = state.get_holding_info()
            if side is not None:
                self.hold_side_label.configure(
                    text=f"持仓: {side}", text_color="#ef4444" if side == "LONG" else "#22c55e"
                )
                self.hold_time_label.configure(text=f"持仓时间: {int(hold_seconds)}秒")
                pnl_color = "#22c55e" if unrealized_pnl > 0 else "#ef4444" if unrealized_pnl < 0 else "#64748b"
                self.hold_pnl_label.configure(text=f"浮动盈亏: {unrealized_pnl:.2f}点", text_color=pnl_color)
                if stop:
                    if side == "LONG":
                        cur_stop_dist = price - stop if price else 0
                    else:
                        cur_stop_dist = stop - price if price else 0
                    self.hold_stop_label.configure(text=f"止损距离: {cur_stop_dist:.2f}")
                    if price and 0 < cur_stop_dist < 0.5:
                        gui_queue.put_nowait(("warning", f"⚠️ 价格接近止损位！当前{price:.2f}，止损{stop}"))
                else:
                    self.hold_stop_label.configure(text="止损距离: --")
            else:
                self.hold_side_label.configure(text="持仓: 无")
                self.hold_time_label.configure(text="持仓时间: 0秒")
                self.hold_pnl_label.configure(text="浮动盈亏: 0.0")
                self.hold_stop_label.configure(text="止损距离: --")

            mgr = data_mgr_ref[0]
            if mgr is not None:
                with mgr._data_lock:
                    df = mgr.candles.tail(100).copy()
                if len(df) >= 5:
                    if len(df) >= 15:
                        ind = strategy.calculate_indicators(df)
                        self.trend_label.configure(text=ind.get("trend", "--"))
                        self.rsi_label.configure(text=f"{ind['rsi']:.1f}")
                        macd_status = "多头" if ind.get("macd_bullish") else "空头"
                        self.macd_label.configure(text=macd_status)
                        self.support_label.configure(text=f"{ind['low_5']:.2f}")
                        self.resist_label.configure(text=f"{ind['high_5']:.2f}")
                        self.range_label.configure(text=f"{ind['recent_range']:.1f}")
                    now = time.time()
                    if now - self.last_chart_update > 1:
                        self.update_chart(df.tail(60), current_price=price)
                        self.last_chart_update = now
        except Exception as e:
            self.log(f"GUI错误: {e}\n")
        self.root.after(800, self.update_gui)

    def update_chart(self, df, current_price=None):
        """纯折线图，无成交量，无 mplfinance"""
        try:
            df = df.copy()
            if df.empty or len(df) < 5:
                return
            if "close" not in df.columns:
                return
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            if len(df) < 5:
                return

            self.fig.clear()
            self.ax = self.fig.add_subplot(111)

            indices = range(len(df))
            prices = df["close"].values

            self.ax.plot(indices, prices, linewidth=1.8, color="#2563eb")
            self.ax.set_ylabel("Price", fontsize=11)
            self.ax.grid(True, alpha=0.3)

            # Y轴范围包含实时价格
            if current_price is not None:
                y_min = min(prices.min(), current_price)
                y_max = max(prices.max(), current_price)
            else:
                y_min = prices.min()
                y_max = prices.max()
            # 避免 min==max 导致警告
            if y_max <= y_min:
                y_max = y_min + 1
            margin = (y_max - y_min) * 0.05
            self.ax.set_ylim(y_min - margin, y_max + margin)

            # X轴标签
            if "timestamp" in df.columns:
                try:
                    times = pd.to_datetime(df["timestamp"]).dt.strftime("%H:%M")
                    step = max(1, len(indices) // 6)
                    self.ax.set_xticks(indices[::step])
                    self.ax.set_xticklabels(times[::step], rotation=30, ha="right", fontsize=9)
                except:
                    pass

            self.canvas.draw_idle()
        except Exception as e:
            self.log(f"绘图失败: {e}\n")

    def display_signal(self, signal):
        if signal.get("type") == "ai":
            return
        side = signal.get("side", "HOLD")
        entry = signal.get("entry", "--")
        stop = signal.get("stop", "--")
        take = signal.get("take", "--")
        reason = signal.get("reason", "")
        if side == "LONG":
            self.signal_label.configure(text="做多 ↑", text_color="#ef4444")
            explain_text = f"系统建议：做多（{reason}）"
        elif side == "SHORT":
            self.signal_label.configure(text="做空 ↓", text_color="#22c55e")
            explain_text = f"系统建议：做空（{reason}）"
        else:
            self.signal_label.configure(text="HOLD", text_color="#64748b")
            explain_text = "系统建议：暂时观望（HOLD）"
        self.signal_details.configure(text=f"入场:{entry} 止损:{stop} 止盈:{take}")
        self.reason_label.configure(text=reason)
        self.explain_label.configure(text=explain_text)

    # ========== 功能方法 ==========
    def top_window(self):
        set_trading_window_topmost()

    def init_history(self):
        if self.history_loading:
            self.log("⚠ 历史K线正在抓取中，请勿重复操作\n")
            return
        threading.Thread(target=self._init_history, daemon=True).start()

    def _init_history(self):
        self.history_loading = True
        self.update_button_states()
        self.log("📈 正在抓取历史K线（一次性）...\n")
        try:
            kline_ocr_scraper.scrape_historical_klines(state, data_mgr_ref, total=60, stop_event=stop_event)
            if data_mgr_ref[0] is not None:
                data_mgr_ref[0].persist()
                analysis_worker.data_mgr = data_mgr_ref[0]
                candle_worker.data_mgr = data_mgr_ref[0]
            self.log("✅ 历史K线抓取完成\n")
            messagebox.showinfo("提示", "历史K线抓取完成")
        except Exception as e:
            self.log(f"❌ 历史K线抓取失败: {e}\n")
            messagebox.showerror("错误", f"抓取失败: {e}")
        finally:
            self.history_loading = False
            self.update_button_states()

    def force_analysis(self):
        if self.analysis_lock.locked():
            self.log("⚠ 分析任务已在执行中\n")
            return
        threading.Thread(target=self._force_analysis_worker, daemon=True).start()

    def _force_analysis_worker(self):
        with self.analysis_lock:
            try:
                candle_queue.put({"force": True})
                self.log("🔄 强制分析已触发\n")
                mgr = data_mgr_ref[0]
                if mgr and len(mgr.candles) >= 15:
                    with mgr._data_lock:
                        df = mgr.candles.tail(61).copy()
                    closed_df = df.iloc[:-1]
                    if len(closed_df) >= 14:
                        ind = strategy.calculate_indicators(closed_df)
                        current_price = closed_df.iloc[-1]["close"]
                        explanation = strategy.explain_analysis(ind, current_price)
                        try:
                            gui_queue.put_nowait(("explain", explanation))
                        except queue.Full:
                            pass
                        self.log(explanation + "\n")
                else:
                    self.log("⚠ 数据不足15根，无法强制分析\n")
            except Exception as e:
                self.log(f"分析失败: {e}\n")

    def ai_mode(self):
        state.analysis_mode = 0
        self.log("🧠 AI模式\n")

    def local_mode(self):
        state.analysis_mode = 1
        self.log("📊 本地规则模式\n")

    def stop_loss(self):
        state.set_stopout_time()
        state.set_position(None, "EMPTY")
        self.log("⛔ 手动止损冷却，已清仓\n")

    def export_log(self):
        import pandas as pd

        with state._lock:
            df = pd.DataFrame(state.trade_log)
        if not df.empty:
            df.to_csv("trade_log.csv", index=False)
            messagebox.showinfo("导出成功", "已保存到 trade_log.csv")
        else:
            messagebox.showinfo("提示", "暂无交易记录")

    def run_backtest(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("回测设置")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text="滑点 (点):").pack(pady=5)
        slippage_entry = ctk.CTkEntry(dialog)
        slippage_entry.insert(0, "0.5")
        slippage_entry.pack(pady=5)
        ctk.CTkLabel(dialog, text="手续费 (点/手):").pack(pady=5)
        commission_entry = ctk.CTkEntry(dialog)
        commission_entry.insert(0, "1.0")
        commission_entry.pack(pady=5)

        def start_backtest():
            try:
                slippage = float(slippage_entry.get())
                commission = float(commission_entry.get())
            except:
                messagebox.showerror("错误", "请输入有效数字")
                return
            dialog.destroy()
            self.log(f"开始回测，滑点={slippage}，手续费={commission}\n")
            self.progress_bar.pack(pady=5)
            self.progress_bar.set(0)
            threading.Thread(target=self._run_backtest_worker, args=(slippage, commission), daemon=True).start()

        ctk.CTkButton(dialog, text="开始回测", command=start_backtest).pack(pady=20)

    def _run_backtest_worker(self, slippage, commission):
        from backtester import Backtester
        from performance import analyze_trades

        try:
            bt = Backtester(data_mgr_ref[0], slippage=slippage, commission=commission)
            trades = bt.run()
            if trades is not None and not trades.empty:
                stats = analyze_trades(trades)
                result = "\n".join([f"{k}: {v}" for k, v in stats.items()])
                gui_queue.put(("backtest_finished", result))
                trades.to_csv("backtest_trades.csv", index=False)
                self.log(f"回测完成，共 {len(trades)} 笔交易\n")
            else:
                gui_queue.put(("backtest_finished", "没有产生任何交易"))
        except Exception as e:
            gui_queue.put(("log", f"回测异常: {e}\n"))
            gui_queue.put(("backtest_finished", f"回测异常: {e}"))

    def open_realtime_settings(self):
        RealTimeRegionsDialog(self.root, config_mgr, on_save_callback=self._on_realtime_regions_saved)

    def _on_realtime_regions_saved(self):
        self.log("✅ 实时区域配置已更新，重启后生效\n")

    def open_prompt_editor(self):
        PromptEditor(self.root, config_mgr)

    def open_strategy_settings(self):
        StrategySettingsDialog(self.root, config_mgr)

    def open_history_viewer(self):
        HistoryViewerDialog(self.root, data_mgr_ref[0])

    def open_kline_chart(self):
        KlineChartWindow(self.root, data_mgr_ref[0])

    def open_ohlc_settings(self):
        OHLCSettingsDialog(self.root, config_mgr, on_save_callback=self._on_ohlc_settings_saved)

    def _on_ohlc_settings_saved(self):
        self.log("✅ OHLC 区域配置已更新，请重新抓取历史K线\n")

    def set_long(self):
        price = state.get_price()
        if price is None:
            self.log("无当前价格，无法开多\n")
            return
        stop = price - MANUAL_STOP_POINTS
        take = price + MANUAL_TAKE_POINTS
        state.set_position(
            {"side": "LONG", "entry": price, "stop": stop, "take": take, "initial_risk": MANUAL_STOP_POINTS}, "LONG"
        )
        self.log(f"🔴 手动开多 @{price}\n")

    def set_short(self):
        price = state.get_price()
        if price is None:
            self.log("无当前价格，无法开空\n")
            return
        stop = price + MANUAL_STOP_POINTS
        take = price - MANUAL_TAKE_POINTS
        state.set_position(
            {"side": "SHORT", "entry": price, "stop": stop, "take": take, "initial_risk": MANUAL_STOP_POINTS}, "SHORT"
        )
        self.log(f"🔵 手动开空 @{price}\n")

    def set_empty(self):
        state.set_position(None, "EMPTY")
        self.log("⚪ 手动平仓\n")

    def set_manual_price(self):
        try:
            price = float(self.manual_price_entry.get())
            tick_time = datetime.now(timezone.utc)
            tick_queue.put((price, tick_time))
            state.update_price(price)
            self.log(f"✏️ 手动注入价格:{price}\n")
            self.manual_price_entry.delete(0, "end")
        except:
            messagebox.showerror("错误", "请输入正确价格")

    def on_close(self):
        if messagebox.askokcancel("退出", "确定退出系统？"):
            global system_running
            stop_event.set()
            system_running = False
            self.root.destroy()
            sys.exit(0)


if __name__ == "__main__":
    root = ctk.CTk()
    app = TradingApp(root)
    root.mainloop()
