# 可运行版 27 文件（逐文件复制）

下面是一套**一致版本**（互相能对上）的 27 文件代码。你按文件名逐个覆盖即可。

> 依赖：`pip install pandas requests pyautogui pytesseract mplfinance matplotlib pydirectinput`

## 1) config.py
```python
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class CaptureConfig:
    left: int = 100
    top: int = 100
    width: int = 120
    height: int = 36

@dataclass
class OCRConfig:
    retry_times: int = 3
    retry_interval_seconds: float = 0.3
    max_jump: float = 20.0
    tesseract_cmd: str = field(default_factory=lambda: os.getenv("TESSERACT_CMD", "tesseract"))

@dataclass
class CandleConfig:
    interval_seconds: int = 60
    max_rows: int = 2000

@dataclass
class APIConfig:
    base_url: str = "https://api.deepseek.com"
    endpoint: str = "/chat/completions"
    model: str = "deepseek-chat"
    timeout_seconds: int = 20
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))

@dataclass
class AppConfig:
    tick_csv: Path = Path("project/data/ticks.csv")
    candle_csv: Path = Path("project/data/candles_1m.csv")
```

## 2) config_manager.py
```python
import copy, json, os

CONFIG_FILE = "user_config.json"
DEFAULT_CONFIG = {
  "capture": {"left":100,"top":100,"width":120,"height":36},
  "system_prompt": "你是专业量化交易分析AI。",
  "strategy": {
    "risk_reward_ratio": 1.5,
    "macd_threshold": 0.05,
    "rsi_upper": 80,
    "rsi_lower": 20,
    "min_range": 4,
    "fake_breakout_distance": 12
  }
}

class ConfigManager:
    def __init__(self, filepath: str = CONFIG_FILE):
        self.filepath = filepath
        self.config = self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return copy.deepcopy(DEFAULT_CONFIG)

    def save(self):
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.filepath)

    def get_capture_region(self):
        c = self.config["capture"]
        return c["left"], c["top"], c["width"], c["height"]

    def set_capture_region(self, left, top, width, height):
        self.config["capture"] = {"left":left,"top":top,"width":width,"height":height}
        self.save()

    def get_system_prompt(self):
        return self.config.get("system_prompt", "")

    def set_system_prompt(self, p):
        self.config["system_prompt"] = p
        self.save()

    def get_strategy_params(self):
        return self.config.get("strategy", {})

    def set_strategy_params(self, p):
        self.config["strategy"] = p
        self.save()
```

## 3) queues.py
```python
from queue import Queue

tick_queue = Queue(maxsize=5000)
candle_queue = Queue(maxsize=500)
signal_queue_exec = Queue(maxsize=50)
signal_queue_ui = Queue(maxsize=100)
```

## 4) runtime_state.py
```python
import copy, threading, time, uuid
from datetime import date

class RuntimeState:
    def __init__(self):
        self._lock = threading.RLock()
        self.latest_price = None
        self.base_price = None
        self.position = None
        self.current_pos = "EMPTY"
        self.analysis_mode = 1
        self.strategy_mode = "auto"
        self.trade_log = []
        self.daily_pnl = 0.0
        self.max_daily_loss = -30.0
        self.last_pnl_reset_date = date.today()
        self.price_updated = threading.Event()

    def update_price(self, price: float):
        with self._lock:
            self.latest_price = price
            self.price_updated.set()

    def get_price(self):
        with self._lock:
            return self.latest_price

    def set_position(self, pos, current_pos):
        with self._lock:
            if pos is not None:
                pos = copy.copy(pos)
                pos.setdefault("entry_time", time.time())
                pos.setdefault("trade_id", str(uuid.uuid4()))
                pos["closing"] = False
            self.position = pos
            self.current_pos = current_pos

    def get_position(self):
        with self._lock:
            return copy.copy(self.position), self.current_pos

    def update_daily_pnl(self, pnl):
        with self._lock:
            if date.today() != self.last_pnl_reset_date:
                self.daily_pnl = 0.0
                self.last_pnl_reset_date = date.today()
            self.daily_pnl += pnl
```

## 5) indicators.py
```python
import pandas as pd

class MarketDataManager:
    def __init__(self, candle_cfg, tick_path, candle_path):
        self.candle_cfg = candle_cfg
        self.tick_path = tick_path
        self.candle_path = candle_path
        self.candles = pd.DataFrame(columns=["timestamp","open","high","low","close","volume"])

    def add_candle(self, candle: dict):
        ts = candle.get("timestamp", candle.get("time"))
        row = {
            "timestamp": pd.to_datetime(ts, utc=True),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle.get("volume", 0)),
        }
        self.candles = pd.concat([self.candles, pd.DataFrame([row])], ignore_index=True)
        if len(self.candles) > self.candle_cfg.max_rows:
            self.candles = self.candles.iloc[-self.candle_cfg.max_rows:].reset_index(drop=True)
```

## 6) strategy.py
```python
def local_trade_rule(candles, state):
    if len(candles) < 15:
        return None
    c = candles.iloc[-1]
    p = candles.iloc[-2]
    if c["close"] > p["high"]:
        e = float(c["close"]); s = float(p["low"]); t = e + (e - s) * 1.5
        return {"side":"LONG","entry":e,"stop":s,"take":t,"reason":"breakout_up"}
    if c["close"] < p["low"]:
        e = float(c["close"]); s = float(p["high"]); t = e - (s - e) * 1.5
        return {"side":"SHORT","entry":e,"stop":s,"take":t,"reason":"breakout_down"}
    return None

def run_ai_analysis(candles, state):
    return None
```

## 7) candle_engine.py
```python
from datetime import datetime

def floor_time(dt: datetime, sec: int):
    ts = int(dt.timestamp())
    return datetime.fromtimestamp(ts - ts % sec, tz=dt.tzinfo)

class CandleEngine:
    def __init__(self, interval_seconds=60):
        self.interval_seconds = interval_seconds
        self.current = None
        self.bucket = None

    def update_tick(self, price, tick_time):
        b = floor_time(tick_time, self.interval_seconds)
        if self.current is None:
            self.bucket = b
            self.current = {"timestamp":b,"open":price,"high":price,"low":price,"close":price,"volume":0.0}
            return None
        if b == self.bucket:
            self.current["high"] = max(self.current["high"], price)
            self.current["low"] = min(self.current["low"], price)
            self.current["close"] = price
            return None
        done = self.current.copy()
        self.bucket = b
        self.current = {"timestamp":b,"open":price,"high":price,"low":price,"close":price,"volume":0.0}
        return done
```

## 8) analysis_worker.py
```python
import queue
from queues import candle_queue, signal_queue_exec, signal_queue_ui
from strategy import local_trade_rule, run_ai_analysis

def run_analysis_worker(state, stop_event, data_mgr):
    while not stop_event.is_set():
        try:
            candle = candle_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            if candle is not None:
                data_mgr.add_candle(candle)
                state.base_price = float(candle["close"])
            if len(data_mgr.candles) < 15:
                continue
            signal = run_ai_analysis(data_mgr.candles, state) if state.analysis_mode == 0 else local_trade_rule(data_mgr.candles, state)
            if signal:
                signal_queue_exec.put(signal, timeout=0.2)
                signal_queue_ui.put(dict(signal), timeout=0.2)
        finally:
            candle_queue.task_done()
```

## 9) candle_worker.py
```python
import queue
from candle_engine import CandleEngine
from config import CandleConfig
from queues import tick_queue, candle_queue

def run_candle_worker(state, stop_event):
    eng = CandleEngine(CandleConfig().interval_seconds)
    while not stop_event.is_set():
        try:
            p, t = tick_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            c = eng.update_tick(float(p), t)
            if c is not None:
                state.base_price = c["close"]
                candle_queue.put(c, timeout=0.2)
        finally:
            tick_queue.task_done()
```

## 10) execution_worker.py
```python
import queue
from queues import signal_queue_exec
from notifier import play_sound

def run_execution_worker(state, stop_event):
    while not stop_event.is_set():
        try:
            s = signal_queue_exec.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            pos, _ = state.get_position()
            if pos is not None:
                continue
            state.set_position({
                "side": s["side"], "entry": s["entry"], "stop": s["stop"], "take": s["take"],
                "initial_risk": abs(s["entry"] - s["stop"])
            }, s["side"])
            play_sound(1200, 120)
        finally:
            signal_queue_exec.task_done()
```

## 11) risk_worker.py
```python
def risk_worker(state, stop_event):
    while not stop_event.is_set():
        state.price_updated.wait(timeout=0.1)
        state.price_updated.clear()
        pos, _ = state.get_position()
        if not pos or pos.get("closing"):
            continue
        p = state.get_price()
        if p is None:
            continue
        side, e, st, tk = pos["side"], pos["entry"], pos["stop"], pos["take"]
        hit = (side=="LONG" and (p<=st or p>=tk)) or (side=="SHORT" and (p>=st or p<=tk))
        if hit:
            pnl = (p - e) * (1 if side == "LONG" else -1)
            state.update_daily_pnl(pnl)
            state.set_position(None, "EMPTY")
```

## 12) notifier.py
```python
import platform, threading

def play_sound(freq, dur):
    if platform.system().lower().startswith("win"):
        try:
            import winsound
            threading.Thread(target=lambda: winsound.Beep(freq, dur), daemon=True).start()
        except Exception:
            pass
```

## 13) ocr_worker.py
```python
import re, threading, time, queue
from datetime import datetime, timezone
import pyautogui, pytesseract
from config import OCRConfig
from config_manager import ConfigManager
from queues import tick_queue

ocr_cfg = OCRConfig()
config_mgr = ConfigManager()
pytesseract.pytesseract.tesseract_cmd = config_mgr.config.get("tesseract_cmd", ocr_cfg.tesseract_cmd)

class TickFilter:
    def __init__(self, max_jump=20.0):
        self.last = None
        self.max_jump = max_jump
    def update(self, price):
        if self.last is None:
            self.last = price; return price
        if abs(price-self.last) > self.max_jump:
            return None
        self.last = price
        return price

def capture_price():
    left, top, width, height = config_mgr.get_capture_region()
    if width <= 0 or height <= 0:
        return None
    for _ in range(ocr_cfg.retry_times):
        try:
            img = pyautogui.screenshot(region=(left, top, width, height)).convert("L")
            txt = pytesseract.image_to_string(img, config="--psm 7 -c tessedit_char_whitelist=0123456789.")
            txt = re.sub(r"[^0-9.]", "", txt)
            if not txt:
                continue
            return round(float(txt) / 2) * 2
        except (ValueError, OSError):
            time.sleep(ocr_cfg.retry_interval_seconds)
    return None

def run_ocr_worker(state, stop_event):
    f = TickFilter(ocr_cfg.max_jump)
    while not stop_event.is_set():
        raw = capture_price()
        if raw is None:
            time.sleep(0.1); continue
        p = f.update(raw)
        if p is None:
            continue
        state.update_price(p)
        try:
            tick_queue.put((p, datetime.now(timezone.utc)), timeout=0.2)
        except queue.Full:
            pass
        time.sleep(0.5)
```

## 14) history_viewer.py
```python
import tkinter as tk
from tkinter import ttk
import pandas as pd

class HistoryViewerDialog:
    def __init__(self, root, data_mgr):
        self.data_mgr = data_mgr
        self.win = tk.Toplevel(root)
        self.win.title("历史K线")
        self.win.geometry("760x420")
        cols = ("时间","开","高","低","收","量")
        self.tree = ttk.Treeview(self.win, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=120, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.load_data()

    def load_data(self):
        if self.data_mgr is None or self.data_mgr.candles.empty:
            return
        df = self.data_mgr.candles.tail(80).copy()
        df["ts"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%m-%d %H:%M")
        for _, r in df.iterrows():
            self.tree.insert("", tk.END, values=(r["ts"], r["open"], r["high"], r["low"], r["close"], r.get("volume",0)))
```

## 15) kline_chart.py
```python
import threading, time, tkinter as tk
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
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
        self.fig = plt.figure(figsize=(8,5))
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
        df = self.data_mgr.candles.tail(60).copy()
        df.rename(columns={"timestamp":"Date","open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"}, inplace=True)
        if not set(["Date","Open","High","Low","Close","Volume"]).issubset(df.columns):
            return
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        for c in ["Open","High","Low","Close","Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Date","Open","High","Low","Close"], inplace=True)
        if df.empty:
            return
        df.set_index("Date", inplace=True)
        self.fig.clear()
        ax1 = self.fig.add_subplot(2,1,1)
        ax2 = self.fig.add_subplot(2,1,2, sharex=ax1)
        mpf.plot(df, type="candle", style="charles", ax=ax1, volume=ax2, show_nontrading=False)
        self.canvas.draw()

    def on_close(self):
        self.running = False
        self.win.destroy()
```

## 16) deepseek_client.py
```python
import requests
from config import APIConfig

class DeepSeekClient:
    def __init__(self, cfg: APIConfig):
        self.cfg = cfg

    def analyze(self, prompt: str) -> str:
        if not self.cfg.api_key:
            return "API Error: Missing DEEPSEEK_API_KEY"
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role":"system","content":"You are a professional quantitative trading analyst."},
                {"role":"user","content":prompt},
            ],
            "max_tokens": 256,
            "temperature": 0.1,
        }
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type":"application/json"}
        try:
            r = requests.post(f"{self.cfg.base_url}{self.cfg.endpoint}", json=payload, headers=headers, timeout=self.cfg.timeout_seconds)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, IndexError, TypeError) as e:
            return f"API Error: {e}"
```

## 17) main_gui.py
```python
import queue, threading, tkinter as tk
from tkinter import ttk, scrolledtext
from runtime_state import RuntimeState
from config import CandleConfig, AppConfig
from indicators import MarketDataManager
from queues import signal_queue_ui
from ocr_worker import run_ocr_worker
from candle_worker import run_candle_worker
from analysis_worker import run_analysis_worker
from execution_worker import run_execution_worker
from risk_worker import risk_worker
from history_viewer import HistoryViewerDialog
from kline_chart import KlineChartWindow

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
        self.started = False
        self.price = ttk.Label(root, text="价格: --", font=("微软雅黑", 16, "bold"))
        self.price.pack(pady=8)
        bar = ttk.Frame(root); bar.pack(fill=tk.X, padx=8)
        ttk.Button(bar, text="启动", command=self.start).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="停止", command=self.stop).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="历史", command=lambda: HistoryViewerDialog(root, data_mgr)).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="K线图", command=lambda: KlineChartWindow(root, data_mgr)).pack(side=tk.LEFT, padx=4)
        self.sig = ttk.Label(root, text="信号: --"); self.sig.pack(pady=4)
        self.log = scrolledtext.ScrolledText(root, height=26); self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        root.after(300, self.refresh)

    def start(self):
        if self.started: return
        self.started = True
        for target, args in [
            (run_ocr_worker,(state,stop_event)),
            (run_candle_worker,(state,stop_event)),
            (run_analysis_worker,(state,stop_event,data_mgr)),
            (run_execution_worker,(state,stop_event)),
            (risk_worker,(state,stop_event)),
        ]:
            threading.Thread(target=target, args=args, daemon=True).start()
        self.log.insert(tk.END, "系统已启动\n")

    def stop(self):
        stop_event.set(); self.log.insert(tk.END, "系统已停止\n")

    def refresh(self):
        p = state.get_price()
        if p is not None: self.price.config(text=f"价格: {p:.2f}")
        try:
            while True:
                s = signal_queue_ui.get_nowait()
                self.sig.config(text=f"信号: {s.get('side')} @ {s.get('entry')}")
                self.log.insert(tk.END, f"{s}\n")
        except queue.Empty:
            pass
        self.root.after(300, self.refresh)

if __name__ == "__main__":
    root = tk.Tk()
    app = TradingApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (stop_event.set(), root.destroy()))
    root.mainloop()
```

## 18) main.py
```python
import threading, time
from datetime import datetime, timezone
from runtime_state import RuntimeState
from config import CandleConfig, AppConfig
from indicators import MarketDataManager
from queues import tick_queue
from candle_worker import run_candle_worker
from analysis_worker import run_analysis_worker
from execution_worker import run_execution_worker
from risk_worker import risk_worker


def feeder(state, stop_event):
    p = 100.0; d = 1
    while not stop_event.is_set():
        p += d * 0.8
        if p > 110: d = -1
        if p < 90: d = 1
        state.update_price(p)
        tick_queue.put((p, datetime.now(timezone.utc)), timeout=0.2)
        time.sleep(1)

if __name__ == "__main__":
    state = RuntimeState()
    stop_event = threading.Event()
    cfg = CandleConfig(); app = AppConfig()
    data_mgr = MarketDataManager(cfg, app.tick_csv, app.candle_csv)
    for target, args in [
        (feeder,(state,stop_event)),
        (run_candle_worker,(state,stop_event)),
        (run_analysis_worker,(state,stop_event,data_mgr)),
        (run_execution_worker,(state,stop_event)),
        (risk_worker,(state,stop_event)),
    ]:
        threading.Thread(target=target, args=args, daemon=True).start()
    print("system started")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
```

## 19) backtester.py
```python
import pandas as pd
from strategy import local_trade_rule

class Backtester:
    def __init__(self, data_mgr, state):
        self.data_mgr = data_mgr
        self.state = state
        self.trades = []

    def run(self, start_idx=15):
        df = self.data_mgr.candles
        if df.empty: return pd.DataFrame()
        for i in range(start_idx, len(df)-1):
            sig = local_trade_rule(df.iloc[:i+1], self.state)
            pos, _ = self.state.get_position()
            if sig and pos is None:
                self.trades.append({"side":sig["side"],"entry":sig["entry"],"pnl":0.0})
                self.state.set_position(sig, sig["side"])
        return pd.DataFrame(self.trades)
```

## 20) performance.py
```python
import pandas as pd

def analyze_trades(df: pd.DataFrame):
    if df.empty or "pnl" not in df: return {}
    pnl = df["pnl"].dropna()
    if pnl.empty: return {}
    w = pnl[pnl>0]
    return {"total_trades":int(len(pnl)), "win_rate": round(len(w)/len(pnl)*100,2), "net_pnl": round(float(pnl.sum()),2)}
```

## 21) settings_dialog.py
```python
import tkinter as tk
from tkinter import ttk, messagebox

class SettingsDialog:
    def __init__(self, root, config_mgr, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("OCR区域")
        self.win.geometry("420x280")
        self.entries = {}
        frm = ttk.Frame(self.win); frm.pack(padx=10, pady=10)
        for i,k in enumerate(["left","top","width","height"]):
            ttk.Label(frm, text=k).grid(row=i,column=0,sticky=tk.W,pady=3)
            e = ttk.Entry(frm, width=10); e.grid(row=i,column=1,pady=3)
            self.entries[k]=e
        c = self.config_mgr.config.get("capture", {})
        for k,e in self.entries.items(): e.insert(0, str(c.get(k,0)))
        ttk.Button(self.win, text="保存", command=self.save).pack(pady=8)

    def save(self):
        try:
            l = int(self.entries["left"].get()); t = int(self.entries["top"].get())
            w = int(self.entries["width"].get()); h = int(self.entries["height"].get())
            if w<=0 or h<=0: raise ValueError("宽高必须>0")
            self.config_mgr.set_capture_region(l,t,w,h)
            if self.on_save: self.on_save()
            self.win.destroy()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
```

## 22) ohlc_settings_dialog.py
```python
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
        for key in ["ohlc_time_region","ohlc_price_region","ohlc_volume_region"]:
            lf = ttk.LabelFrame(self.win, text=key); lf.pack(fill=tk.X, padx=8, pady=6)
            self.entries[key] = {}
            cfg = self.config_mgr.config.get(key, {})
            for i,f in enumerate(["left","top","width","height"]):
                ttk.Label(lf, text=f).grid(row=0,column=i*2,padx=3,pady=3)
                e = ttk.Entry(lf, width=7); e.grid(row=0,column=i*2+1,padx=3)
                e.insert(0, str(cfg.get(f,0))); self.entries[key][f]=e
        ttk.Button(self.win, text="保存", command=self.save).pack(pady=8)

    def save(self):
        try:
            for k,v in self.entries.items():
                l=int(v["left"].get()); t=int(v["top"].get()); w=int(v["width"].get()); h=int(v["height"].get())
                if w<=0 or h<=0: raise ValueError(f"{k}宽高必须>0")
                self.config_mgr.config[k] = {"left":l,"top":t,"width":w,"height":h}
            self.config_mgr.save()
            if self.on_save: self.on_save()
            self.win.destroy()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
```

## 23) prompt_editor.py
```python
import tkinter as tk
from tkinter import ttk, messagebox

DEFAULT_PROMPT = "你是专业量化交易分析AI。输出 LONG/SHORT/HOLD 与 entry/stop/take/reason。"

class PromptEditor:
    def __init__(self, root, config_mgr, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("AI提示词")
        self.win.geometry("640x520")
        self.txt = tk.Text(self.win); self.txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.txt.insert(tk.END, self.config_mgr.get_system_prompt() or DEFAULT_PROMPT)
        f = ttk.Frame(self.win); f.pack(pady=6)
        ttk.Button(f, text="保存", command=self.save).pack(side=tk.LEFT, padx=4)
        ttk.Button(f, text="默认", command=self.reset).pack(side=tk.LEFT, padx=4)

    def save(self):
        p = self.txt.get("1.0", tk.END).strip()
        if not p:
            messagebox.showerror("错误", "提示词不能为空"); return
        self.config_mgr.set_system_prompt(p)
        if self.on_save: self.on_save()
        self.win.destroy()

    def reset(self):
        self.txt.delete("1.0", tk.END)
        self.txt.insert(tk.END, DEFAULT_PROMPT)
```

## 24) strategy_settings_dialog.py
```python
import tkinter as tk
from tkinter import ttk, messagebox

class StrategySettingsDialog:
    def __init__(self, root, config_mgr, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("策略参数")
        self.win.geometry("420x360")
        self.keys = ["macd_threshold","rsi_upper","rsi_lower","min_range","fake_breakout_distance","risk_reward_ratio"]
        params = self.config_mgr.get_strategy_params()
        self.entries = {}
        for i,k in enumerate(self.keys):
            ttk.Label(self.win,text=k).grid(row=i,column=0,sticky=tk.W,padx=8,pady=6)
            e = ttk.Entry(self.win,width=12); e.grid(row=i,column=1,padx=8,pady=6)
            e.insert(0,str(params.get(k,0))); self.entries[k]=e
        ttk.Button(self.win,text="保存",command=self.save).grid(row=7,column=0,columnspan=2,pady=10)

    def save(self):
        try:
            p = {k:float(e.get()) for k,e in self.entries.items()}
            if p["rsi_upper"] <= p["rsi_lower"]: raise ValueError("rsi_upper 必须 > rsi_lower")
            self.config_mgr.set_strategy_params(p)
            if self.on_save: self.on_save()
            self.win.destroy()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
```

## 25) kline_ocr_scraper.py
```python
# 简版占位：如需历史OCR抓取，可在此扩展

def scrape_historical_klines(state, data_mgr_ref, total=60, stop_event=None):
    return
```

## 26) simulate.py
```python
import threading, time
from datetime import datetime, timezone
import pandas as pd
import tkinter as tk
from main_gui import TradingApp, data_mgr, state
from queues import tick_queue

def load_sim_data(path="sim_data.csv"):
    df = pd.read_csv(path)
    if "timestamp" not in df.columns and "time" in df.columns:
        df["timestamp"] = pd.to_datetime(df["time"], errors="coerce")
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for _,r in df.dropna(subset=["timestamp"]).iterrows():
        data_mgr.add_candle({"timestamp":r["timestamp"].to_pydatetime().replace(tzinfo=timezone.utc),"open":r["open"],"high":r["high"],"low":r["low"],"close":r["close"],"volume":r.get("volume",0)})
    def feed():
        for _,r in df.tail(60).iterrows():
            p=float(r["close"]); state.update_price(p)
            tick_queue.put((p, datetime.now(timezone.utc)), timeout=0.2)
            time.sleep(0.8)
    threading.Thread(target=feed, daemon=True).start()

if __name__ == "__main__":
    load_sim_data()
    root = tk.Tk(); app = TradingApp(root); root.mainloop()
```

## 27) spike_filter.py
```python
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

## 运行步骤（先验证核心）
1. 先运行：`python main.py`
2. 再运行 GUI：`python main_gui.py`
3. 若 OCR 没反应，用 `simulate.py` 验证链路。
