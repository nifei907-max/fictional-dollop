"""
实时K线图窗口（修复数据类型错误，支持自动清洗）
"""
import tkinter as tk
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import mplfinance as mpf

class KlineChartWindow:
    def __init__(self, root, data_mgr, refresh_interval=2):
        self.root = root
        self.data_mgr = data_mgr
        self.refresh_interval = refresh_interval
        self.running = True

        self.win = tk.Toplevel(root)
        self.win.title("📉 实时K线图")
        self.win.geometry("800x600")
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

        self.fig = plt.figure(figsize=(8, 5))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.win)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.schedule_refresh()

    def schedule_refresh(self):
        if not self.running:
            return
        self.draw_chart()
        self.win.after(int(self.refresh_interval * 1000), self.schedule_refresh)

    def sanitize_ohlc(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        col_map = {
            'timestamp': 'Date', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'volume': 'Volume'
        }
        for old, new in col_map.items():
            if old in df.columns and new not in df.columns:
                df.rename(columns={old: new}, inplace=True)

        required = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        for col in required:
            if col not in df.columns:
                if col == 'Volume':
                    df[col] = 0.0
                else:
                    return pd.DataFrame()

        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df.dropna(subset=['Open', 'High', 'Low', 'Close'], inplace=True)
        df = df[df['High'] >= df['Low']]

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df.dropna(subset=['Date'], inplace=True)
        df.set_index('Date', inplace=True)

        return df

    def draw_chart(self):
        if self.data_mgr is None or self.data_mgr.candles.empty:
            return

        df = self.data_mgr.candles.tail(60).copy()
        if df.empty:
            return

        df = self.sanitize_ohlc(df)
        if df.empty:
            return

        self.fig.clear()
        ax1 = self.fig.add_subplot(2, 1, 1)
        ax2 = self.fig.add_subplot(2, 1, 2, sharex=ax1)

        try:
            mpf.plot(df, type='candle', style='charles',
                     ax=ax1, volume=ax2, show_nontrading=False,
                     ylabel='Price', ylabel_lower='Volume')
        except Exception as e:
            print(f"K线图绘制错误: {e}")

        self.canvas.draw()

    def on_close(self):
        self.running = False
        self.win.destroy()