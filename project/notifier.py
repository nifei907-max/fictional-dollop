"""通知模块：负责弹窗提醒（带去抖动）。"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox

from config import NotifyConfig


class Notifier:
    def __init__(self, cfg: NotifyConfig) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.cfg = cfg
        self.last_signal = ""
        self.last_notify_ts = 0.0

    def should_notify(self, signal: str) -> bool:
        now = time.time()
        if signal != self.last_signal:
            return True
        return (now - self.last_notify_ts) >= self.cfg.cooldown_seconds

    def notify(self, signal: str, reason: str) -> None:
        if not self.should_notify(signal):
            return
        title = f"交易信号：{signal}"
        content = f"信号: {signal}\n\n原因:\n{reason}"
        messagebox.showinfo(title, content)
        self.last_signal = signal
        self.last_notify_ts = time.time()
