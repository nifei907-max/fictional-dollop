"""通知模块：负责弹窗提醒。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox


class Notifier:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()

    def notify(self, signal: str, reason: str) -> None:
        title = f"交易信号：{signal}"
        content = f"信号: {signal}\n\n原因:\n{reason}"
        messagebox.showinfo(title, content)
