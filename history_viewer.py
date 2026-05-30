"""历史K线数据查看器"""
import tkinter as tk
from tkinter import ttk
import pandas as pd

class HistoryViewerDialog:
    def __init__(self, root, data_mgr):
        self.data_mgr = data_mgr
        self.win = tk.Toplevel(root)
        self.win.title("📋 历史K线数据（最近60根）")
        self.win.geometry("700x400")
        self.win.resizable(True, True)
        self.win.transient(root)
        frame = ttk.Frame(self.win)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        columns = ("时间", "开", "高", "低", "收", "成交量")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor=tk.CENTER)
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky=tk.NSEW)
        vsb.grid(row=0, column=1, sticky=tk.NS)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        ttk.Button(self.win, text="关闭", command=self.win.destroy).pack(pady=5)
        self.load_data()

    def load_data(self):
        if self.data_mgr is None or self.data_mgr.candles.empty:
            return
        df = self.data_mgr.candles.tail(60).copy()
        if "timestamp" in df.columns:
            df["时间"] = pd.to_datetime(df["timestamp"]).dt.strftime("%m-%d %H:%M")
        else:
            df["时间"] = ""
        for col in ["开", "高", "低", "收", "成交量"]:
            col_map = {"开": "open", "高": "high", "低": "low", "收": "close", "成交量": "volume"}
            if col_map[col] not in df.columns:
                df[col] = 0
        for _, row in df.iterrows():
            self.tree.insert("", tk.END, values=(
                row["时间"], row.get("open", 0), row.get("high", 0),
                row.get("low", 0), row.get("close", 0), row.get("volume", 0)
            ))