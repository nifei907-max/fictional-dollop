# 27/27补齐：剩余 UI/OCR 12 个文件可直接覆盖代码

> 这是你上一步确认的“下一步”：把剩余 UI/OCR 文件一次性补齐。  
> 下面代码与前一版核心模块（队列拆分、timestamp统一）兼容。

---

## 1) `deepseek_client.py`
```python
"""DeepSeek API 封装（健壮版）"""
from __future__ import annotations

import requests
from config import APIConfig


class DeepSeekClient:
    def __init__(self, config: APIConfig):
        self.base_url = config.base_url.rstrip("/")
        self.endpoint = config.endpoint
        self.model = config.model
        self.api_key = config.api_key
        self.timeout = config.timeout_seconds

    def analyze(self, prompt: str) -> str:
        if not self.api_key or self.api_key.startswith("sk-your"):
            return "API Error: Missing DEEPSEEK_API_KEY"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a professional quantitative trading analyst."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 256,
            "temperature": 0.1,
        }
        try:
            resp = requests.post(
                f"{self.base_url}{self.endpoint}",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, IndexError, TypeError) as e:
            return f"API Error: {e}"
```

## 2) `ocr_worker.py`
```python
"""OCR线程：读取屏幕价格，去抖，入 tick_queue"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone

import pyautogui
import pytesseract

from config import OCRConfig
from config_manager import ConfigManager
from queues import tick_queue
from runtime_state import RuntimeState

ocr_cfg = OCRConfig()
config_mgr = ConfigManager()
pytesseract.pytesseract.tesseract_cmd = config_mgr.config.get(
    "tesseract_cmd", ocr_cfg.tesseract_cmd
)


class TickFilter:
    def __init__(self, max_jump: float = 20.0):
        self.last_price = None
        self.max_jump = max_jump

    def update(self, price: float):
        if self.last_price is None:
            self.last_price = price
            return price
        if abs(price - self.last_price) > self.max_jump:
            return None
        self.last_price = price
        return price


def capture_price():
    left, top, width, height = config_mgr.get_capture_region()
    if width <= 0 or height <= 0:
        return None

    for _ in range(ocr_cfg.retry_times):
        try:
            img = pyautogui.screenshot(region=(left, top, width, height))
            img = img.convert("L")
            img = img.point(lambda p: 255 if p > 128 else 0)
            text = pytesseract.image_to_string(
                img,
                config="--psm 7 -c tessedit_char_whitelist=0123456789.",
            )
            txt = re.sub(r"[^0-9.]", "", text)
            if not txt:
                continue
            price = float(txt)
            price = round(price / 2) * 2
            return price
        except (ValueError, OSError):
            time.sleep(ocr_cfg.retry_interval_seconds)
    return None


def run_ocr_worker(state: RuntimeState, stop_event: threading.Event):
    filt = TickFilter(max_jump=20)
    while not stop_event.is_set():
        raw = capture_price()
        if raw is None:
            time.sleep(0.1)
            continue
        price = filt.update(raw)
        if price is None:
            continue
        tick_time = datetime.now(timezone.utc)
        state.update_price(price)
        try:
            tick_queue.put((price, tick_time), timeout=0.2)
        except Exception:
            pass
        time.sleep(0.5)
```

## 3) `main_gui.py`
```python
"""GUI主程序（兼容 signal_queue_ui）"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from analysis_worker import run_analysis_worker
from candle_worker import run_candle_worker
from config import AppConfig, CandleConfig
from execution_worker import run_execution_worker
from history_viewer import HistoryViewerDialog
from indicators import MarketDataManager
from kline_chart import KlineChartWindow
from ocr_worker import run_ocr_worker
from queues import signal_queue_ui
from risk_worker import risk_worker
from runtime_state import RuntimeState

state = RuntimeState()
stop_event = threading.Event()
app_cfg = AppConfig()
candle_cfg = CandleConfig()
data_mgr = MarketDataManager(candle_cfg, app_cfg.tick_csv, app_cfg.candle_csv)


class TradingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("量化交易系统")
        self.root.geometry("900x760")

        self.price_label = ttk.Label(root, text="价格: --", font=("微软雅黑", 16, "bold"))
        self.price_label.pack(pady=8)

        btn = ttk.Frame(root)
        btn.pack(fill=tk.X, padx=8)
        ttk.Button(btn, text="启动", command=self.start_threads).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn, text="停止", command=self.stop_system).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn, text="历史", command=self.open_history).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn, text="K线图", command=self.open_chart).pack(side=tk.LEFT, padx=4)

        self.signal_label = ttk.Label(root, text="信号: --", font=("微软雅黑", 13))
        self.signal_label.pack(pady=6)

        self.log = scrolledtext.ScrolledText(root, height=26)
        self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self._started = False
        self.root.after(300, self.refresh_ui)

    def start_threads(self):
        if self._started:
            return
        self._started = True
        workers = [
            threading.Thread(target=run_ocr_worker, args=(state, stop_event), daemon=True),
            threading.Thread(target=run_candle_worker, args=(state, stop_event), daemon=True),
            threading.Thread(target=run_analysis_worker, args=(state, stop_event, data_mgr), daemon=True),
            threading.Thread(target=run_execution_worker, args=(state, stop_event), daemon=True),
            threading.Thread(target=risk_worker, args=(state, stop_event), daemon=True),
        ]
        for t in workers:
            t.start()
        self.log.insert(tk.END, "系统已启动\n")

    def stop_system(self):
        stop_event.set()
        self.log.insert(tk.END, "系统已停止\n")

    def open_history(self):
        HistoryViewerDialog(self.root, data_mgr)

    def open_chart(self):
        KlineChartWindow(self.root, data_mgr)

    def refresh_ui(self):
        p = state.get_price()
        if p is not None:
            self.price_label.config(text=f"价格: {p:.2f}")

        try:
            while True:
                s = signal_queue_ui.get_nowait()
                self.signal_label.config(text=f"信号: {s.get('side', '--')} @ {s.get('entry', '--')}")
                self.log.insert(tk.END, f"信号: {s}\n")
        except queue.Empty:
            pass

        self.root.after(300, self.refresh_ui)


if __name__ == "__main__":
    root = tk.Tk()
    app = TradingApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (stop_event.set(), root.destroy()))
    root.mainloop()
```

## 4) `kline_chart.py`
```python
"""实时K线图"""
from __future__ import annotations

import threading
import time
import tkinter as tk

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class KlineChartWindow:
    def __init__(self, root, data_mgr, refresh_interval=2):
        self.data_mgr = data_mgr
        self.running = True
        self.refresh_interval = refresh_interval

        self.win = tk.Toplevel(root)
        self.win.title("实时K线图")
        self.win.geometry("800x600")
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

        self.fig = plt.figure(figsize=(8, 5))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.win)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        threading.Thread(target=self.auto_refresh, daemon=True).start()

    def auto_refresh(self):
        while self.running:
            self.win.after(0, self.draw_chart)
            time.sleep(self.refresh_interval)

    def draw_chart(self):
        if self.data_mgr is None or self.data_mgr.candles.empty:
            return
        df = self.data_mgr.candles.tail(80).copy()
        df.rename(columns={
            "timestamp": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
        }, inplace=True)
        required = ["Date", "Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in required):
            return
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Date", "Open", "High", "Low", "Close"], inplace=True)
        if df.empty:
            return
        df.set_index("Date", inplace=True)

        self.fig.clear()
        ax1 = self.fig.add_subplot(2, 1, 1)
        ax2 = self.fig.add_subplot(2, 1, 2, sharex=ax1)
        mpf.plot(df, type="candle", style="charles", ax=ax1, volume=ax2, show_nontrading=False)
        self.canvas.draw()

    def on_close(self):
        self.running = False
        self.win.destroy()
```

## 5) `history_viewer.py`
```python
"""历史K线查看"""
import tkinter as tk
from tkinter import ttk
import pandas as pd


class HistoryViewerDialog:
    def __init__(self, root, data_mgr):
        self.data_mgr = data_mgr
        self.win = tk.Toplevel(root)
        self.win.title("历史K线")
        self.win.geometry("760x420")

        cols = ("时间", "开", "高", "低", "收", "量")
        self.tree = ttk.Treeview(self.win, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=120, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.load_data()

    def load_data(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        if self.data_mgr is None or self.data_mgr.candles.empty:
            return
        df = self.data_mgr.candles.tail(80).copy()
        df["ts"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%m-%d %H:%M")
        for _, r in df.iterrows():
            self.tree.insert("", tk.END, values=(r["ts"], r["open"], r["high"], r["low"], r["close"], r.get("volume", 0)))
```

## 6) `kline_ocr_scraper.py`
```python
"""历史K线 OCR 抓取（简版）"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import pyautogui
import pydirectinput
import pytesseract


def ocr_text(region):
    if region[2] <= 0 or region[3] <= 0:
        return ""
    img = pyautogui.screenshot(region=region)
    img = img.convert("L")
    return pytesseract.image_to_string(img, config="--psm 7 -l chi_sim+eng")


def parse_ohlc(text):
    nums = re.findall(r"[\d,.]+", text)
    if len(nums) < 4:
        return None
    try:
        o, h, l, c = [float(x.replace(",", "")) for x in nums[-4:]]
        return {"open": o, "high": h, "low": l, "close": c}
    except ValueError:
        return None


def scrape_historical_klines(state, data_mgr_ref, total=60, stop_event=None):
    now = datetime.now(timezone.utc)
    candles = []
    for i in range(total):
        if stop_event and stop_event.is_set():
            break
        txt = ""  # 这里接你的 OCR 文本来源
        ohlc = parse_ohlc(txt)
        if ohlc:
            ts = now - timedelta(minutes=(total - i))
            candles.append({"timestamp": ts, **ohlc, "volume": 0.0})
        if i < total - 1:
            pydirectinput.press("left")
            time.sleep(0.15)

    if candles:
        new_mgr = data_mgr_ref[0]
        for c in candles:
            new_mgr.add_candle(c)
        state.base_price = candles[-1]["close"]
        state.update_price(state.base_price)
```

## 7) `settings_dialog.py`
```python
"""OCR截图区域设置"""
import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui


class SettingsDialog:
    def __init__(self, root, config_mgr, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("OCR区域")
        self.win.geometry("420x280")

        self.entries = {}
        frm = ttk.Frame(self.win)
        frm.pack(padx=10, pady=10)
        for i, key in enumerate(["left", "top", "width", "height"]):
            ttk.Label(frm, text=key).grid(row=i, column=0, sticky=tk.W, pady=3)
            e = ttk.Entry(frm, width=10)
            e.grid(row=i, column=1, pady=3)
            self.entries[key] = e

        c = self.config_mgr.config.get("capture", {})
        for k, e in self.entries.items():
            e.insert(0, str(c.get(k, 0)))

        ttk.Button(self.win, text="拾取坐标(3秒)", command=self.capture_pos).pack(pady=4)
        ttk.Button(self.win, text="保存", command=self.save).pack(pady=4)

    def capture_pos(self):
        self.win.after(3000, self._capture_now)

    def _capture_now(self):
        x, y = pyautogui.position()
        self.entries["left"].delete(0, tk.END); self.entries["left"].insert(0, str(x))
        self.entries["top"].delete(0, tk.END); self.entries["top"].insert(0, str(y))

    def save(self):
        try:
            left = int(self.entries["left"].get())
            top = int(self.entries["top"].get())
            width = int(self.entries["width"].get())
            height = int(self.entries["height"].get())
            if width <= 0 or height <= 0:
                raise ValueError("宽高必须>0")
            self.config_mgr.set_capture_region(left, top, width, height)
            if self.on_save:
                self.on_save()
            self.win.destroy()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
```

## 8) `ohlc_settings_dialog.py`
```python
"""OHLC三区域设置"""
import tkinter as tk
from tkinter import ttk, messagebox


class OHLCSettingsDialog:
    def __init__(self, root, config_mgr, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("OHLC三区域")
        self.win.geometry("560x380")

        self.entries = {}
        keys = ["ohlc_time_region", "ohlc_price_region", "ohlc_volume_region"]
        for idx, key in enumerate(keys):
            lf = ttk.LabelFrame(self.win, text=key)
            lf.pack(fill=tk.X, padx=8, pady=6)
            self.entries[key] = {}
            cfg = self.config_mgr.config.get(key, {})
            for i, field in enumerate(["left", "top", "width", "height"]):
                ttk.Label(lf, text=field).grid(row=0, column=i * 2, padx=3, pady=3)
                e = ttk.Entry(lf, width=7)
                e.grid(row=0, column=i * 2 + 1, padx=3)
                e.insert(0, str(cfg.get(field, 0)))
                self.entries[key][field] = e

        ttk.Button(self.win, text="保存", command=self.save).pack(pady=8)

    def save(self):
        try:
            for key, v in self.entries.items():
                left = int(v["left"].get()); top = int(v["top"].get())
                width = int(v["width"].get()); height = int(v["height"].get())
                if width <= 0 or height <= 0:
                    raise ValueError(f"{key} 宽高必须>0")
                self.config_mgr.config[key] = {"left": left, "top": top, "width": width, "height": height}
            self.config_mgr.save()
            if self.on_save:
                self.on_save()
            self.win.destroy()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
```

## 9) `prompt_editor.py`
```python
"""提示词编辑"""
import tkinter as tk
from tkinter import ttk, messagebox

DEFAULT_PROMPT = """你是专业量化交易分析AI。
请基于最近K线输出: side/entry/stop/take/reason。
side仅可为 LONG/SHORT/HOLD。
"""


class PromptEditor:
    def __init__(self, root, config_mgr, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("AI提示词")
        self.win.geometry("640x520")

        self.txt = tk.Text(self.win)
        self.txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.txt.insert(tk.END, self.config_mgr.get_system_prompt() or DEFAULT_PROMPT)

        frm = ttk.Frame(self.win)
        frm.pack(pady=6)
        ttk.Button(frm, text="保存", command=self.save).pack(side=tk.LEFT, padx=4)
        ttk.Button(frm, text="默认", command=self.reset_default).pack(side=tk.LEFT, padx=4)

    def save(self):
        p = self.txt.get("1.0", tk.END).strip()
        if not p:
            messagebox.showerror("错误", "提示词不能为空")
            return
        self.config_mgr.set_system_prompt(p)
        if self.on_save:
            self.on_save()
        self.win.destroy()

    def reset_default(self):
        self.txt.delete("1.0", tk.END)
        self.txt.insert(tk.END, DEFAULT_PROMPT)
```

## 10) `strategy_settings_dialog.py`
```python
"""策略参数设置"""
import tkinter as tk
from tkinter import ttk, messagebox


class StrategySettingsDialog:
    def __init__(self, root, config_mgr, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("策略参数")
        self.win.geometry("420x360")

        self.keys = [
            "macd_threshold", "rsi_upper", "rsi_lower",
            "min_range", "fake_breakout_distance", "risk_reward_ratio",
        ]
        params = self.config_mgr.get_strategy_params()

        self.entries = {}
        for i, k in enumerate(self.keys):
            ttk.Label(self.win, text=k).grid(row=i, column=0, sticky=tk.W, padx=8, pady=6)
            e = ttk.Entry(self.win, width=12)
            e.grid(row=i, column=1, padx=8, pady=6)
            e.insert(0, str(params.get(k, 0)))
            self.entries[k] = e

        ttk.Button(self.win, text="保存", command=self.save).grid(row=7, column=0, columnspan=2, pady=10)

    def save(self):
        try:
            p = {k: float(e.get()) for k, e in self.entries.items()}
            if p["rsi_upper"] <= p["rsi_lower"]:
                raise ValueError("rsi_upper 必须 > rsi_lower")
            self.config_mgr.set_strategy_params(p)
            if self.on_save:
                self.on_save()
            self.win.destroy()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
```

## 11) `simulate.py`
```python
"""模拟盘启动器"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pandas as pd

from main_gui import TradingApp, data_mgr, state, stop_event
from queues import tick_queue
import tkinter as tk


def load_sim_data(path="sim_data.csv"):
    df = pd.read_csv(path)
    if "timestamp" not in df.columns and "time" in df.columns:
        df["timestamp"] = pd.to_datetime(df["time"], errors="coerce")
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    for _, r in df.dropna(subset=["timestamp"]).iterrows():
        data_mgr.add_candle({
            "timestamp": r["timestamp"].to_pydatetime().replace(tzinfo=timezone.utc),
            "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
            "volume": r.get("volume", 0),
        })

    def feed():
        for _, r in df.tail(60).iterrows():
            p = float(r["close"])
            state.update_price(p)
            tick_queue.put((p, datetime.now(timezone.utc)), timeout=0.2)
            time.sleep(0.8)

    threading.Thread(target=feed, daemon=True).start()


if __name__ == "__main__":
    load_sim_data()
    root = tk.Tk()
    app = TradingApp(root)
    root.mainloop()
```

## 12) `spike_filter.py`
```python
"""瞬时波动熔断"""
import time


class SpikeFilter:
    def __init__(self, spike_threshold=8, block_seconds=30):
        self.last_price = None
        self.blocked_until = 0
        self.spike_threshold = spike_threshold
        self.block_seconds = block_seconds

    def check(self, price: float) -> bool:
        now = time.time()
        if now < self.blocked_until:
            return False
        if self.last_price is not None and abs(price - self.last_price) >= self.spike_threshold:
            self.blocked_until = now + self.block_seconds
            self.last_price = price
            return False
        self.last_price = price
        return True
```

---

## 对接说明（很重要）

1. 你前面已覆盖的核心文件继续保留：
   - `queues.py`（必须包含 `signal_queue_ui`）
   - `analysis_worker.py`（必须同时投递 exec/ui 两个信号队列）
2. `main_gui.py` 只消费 `signal_queue_ui`，不要再直接读 `signal_queue_exec`。
3. K线字段统一 `timestamp`；兼容导入层可接收 `time` 后转换。

