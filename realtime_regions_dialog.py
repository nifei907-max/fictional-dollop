"""
实时区域设置对话框：一次性标定时间、价格、买一价、卖一价四个区域
"""

import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui
from config_manager import ConfigManager


class RealTimeRegionsDialog:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("⚙ 实时区域设置（时间/价格/买一/卖一）")
        self.win.geometry("500x450")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.grab_set()
        self.create_widgets()
        self.load_current_config()

    def create_widgets(self):
        notebook = ttk.Notebook(self.win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 时间区域
        self.time_frame = ttk.Frame(notebook)
        notebook.add(self.time_frame, text="时间")
        self.create_region_tab(self.time_frame, "time_region", "时间 (HH:MM:SS)")

        # 价格区域
        self.price_frame = ttk.Frame(notebook)
        notebook.add(self.price_frame, text="价格")
        self.create_region_tab(self.price_frame, "price_region", "最新成交价 (数字)")

        # 买一价区域
        self.bid_frame = ttk.Frame(notebook)
        notebook.add(self.bid_frame, text="买一价")
        self.create_region_tab(self.bid_frame, "bid1_price_region", "买一价 (数字)")

        # 卖一价区域
        self.ask_frame = ttk.Frame(notebook)
        notebook.add(self.ask_frame, text="卖一价")
        self.create_region_tab(self.ask_frame, "ask1_price_region", "卖一价 (数字)")

        ttk.Button(self.win, text="💾 保存所有区域", command=self.save_all).pack(pady=10)

    def create_region_tab(self, parent, config_key, description):
        frame = ttk.LabelFrame(parent, text="截图区域坐标 (像素)", padding=10)
        frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(frame, text=description).pack(anchor=tk.W, pady=2)

        # 坐标输入行
        row1 = ttk.Frame(frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="X:").pack(side=tk.LEFT, padx=2)
        entry_left = ttk.Entry(row1, width=8)
        entry_left.pack(side=tk.LEFT, padx=2)
        ttk.Label(row1, text="Y:").pack(side=tk.LEFT, padx=2)
        entry_top = ttk.Entry(row1, width=8)
        entry_top.pack(side=tk.LEFT, padx=2)
        ttk.Label(row1, text="宽度:").pack(side=tk.LEFT, padx=2)
        entry_width = ttk.Entry(row1, width=8)
        entry_width.pack(side=tk.LEFT, padx=2)
        ttk.Label(row1, text="高度:").pack(side=tk.LEFT, padx=2)
        entry_height = ttk.Entry(row1, width=8)
        entry_height.pack(side=tk.LEFT, padx=2)

        # 按钮行
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="🖱️ 鼠标拾取 (3秒)", command=lambda: self.start_capture(entry_left, entry_top)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            btn_frame,
            text="📸 测试截图",
            command=lambda: self.test_screenshot(entry_left, entry_top, entry_width, entry_height),
        ).pack(side=tk.LEFT, padx=2)

        setattr(self, f"entry_{config_key}_left", entry_left)
        setattr(self, f"entry_{config_key}_top", entry_top)
        setattr(self, f"entry_{config_key}_width", entry_width)
        setattr(self, f"entry_{config_key}_height", entry_height)

    def load_current_config(self):
        for key in ["time_region", "price_region", "bid1_price_region", "ask1_price_region"]:
            cfg = self.config_mgr.config.get(key, {})
            getattr(self, f"entry_{key}_left").insert(0, str(cfg.get("left", 0)))
            getattr(self, f"entry_{key}_top").insert(0, str(cfg.get("top", 0)))
            getattr(self, f"entry_{key}_width").insert(0, str(cfg.get("width", 0)))
            getattr(self, f"entry_{key}_height").insert(0, str(cfg.get("height", 0)))

    def start_capture(self, entry_left, entry_top):
        # 禁用当前按钮避免重复
        btn = self.win.focus_get()
        if btn and isinstance(btn, ttk.Button):
            btn.config(state="disabled")
        self.win.after(3000, lambda: self.capture_pos(entry_left, entry_top))

    def capture_pos(self, entry_left, entry_top):
        x, y = pyautogui.position()
        entry_left.delete(0, tk.END)
        entry_left.insert(0, str(x))
        entry_top.delete(0, tk.END)
        entry_top.insert(0, str(y))
        # 恢复按钮状态
        for child in self.win.winfo_children():
            if isinstance(child, ttk.Button):
                child.config(state="normal")

    def test_screenshot(self, entry_left, entry_top, entry_width, entry_height):
        try:
            left = int(entry_left.get())
            top = int(entry_top.get())
            width = int(entry_width.get())
            height = int(entry_height.get())
            img = pyautogui.screenshot(region=(left, top, width, height))
            img.show()
        except Exception as e:
            messagebox.showerror("截图失败", str(e))

    def save_all(self):
        for key in ["time_region", "price_region", "bid1_price_region", "ask1_price_region"]:
            try:
                left = int(getattr(self, f"entry_{key}_left").get())
                top = int(getattr(self, f"entry_{key}_top").get())
                width = int(getattr(self, f"entry_{key}_width").get())
                height = int(getattr(self, f"entry_{key}_height").get())
                self.config_mgr.config[key] = {"left": left, "top": top, "width": width, "height": height}
            except ValueError:
                messagebox.showerror("输入错误", f"{key} 请输入有效整数")
                return
        self.config_mgr.save()
        messagebox.showinfo("保存成功", "实时区域配置已保存")
        if self.on_save:
            self.on_save()
        self.win.destroy()
