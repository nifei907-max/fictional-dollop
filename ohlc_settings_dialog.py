"""OHLC 多区域截图设置对话框（时间、价格、成交量）"""

import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui
from config_manager import ConfigManager


class OHLCSettingsDialog:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("📋 OHLC 三区域截图设置")
        self.win.geometry("520x400")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.grab_set()

        self.notebook = ttk.Notebook(self.win)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.time_frame = ttk.Frame(self.notebook)
        self.price_frame = ttk.Frame(self.notebook)
        self.volume_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.time_frame, text="时间")
        self.notebook.add(self.price_frame, text="OHLC价格")
        self.notebook.add(self.volume_frame, text="成交量")

        self.create_region_tab(self.time_frame, "ohlc_time_region")
        self.create_region_tab(self.price_frame, "ohlc_price_region")
        self.create_region_tab(self.volume_frame, "ohlc_volume_region")

        ttk.Button(self.win, text="💾 保存所有区域", command=self.save_all).pack(pady=10)

    def create_region_tab(self, parent, config_key):
        frame = ttk.LabelFrame(parent, text="截图区域坐标 (像素)", padding=10)
        frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(frame, text="X (左):").grid(row=0, column=0, padx=5, pady=2)
        entry_left = ttk.Entry(frame, width=8)
        entry_left.grid(row=0, column=1, padx=5)
        ttk.Label(frame, text="Y (上):").grid(row=0, column=2, padx=5)
        entry_top = ttk.Entry(frame, width=8)
        entry_top.grid(row=0, column=3, padx=5)
        ttk.Label(frame, text="宽度:").grid(row=1, column=0, padx=5, pady=2)
        entry_width = ttk.Entry(frame, width=8)
        entry_width.grid(row=1, column=1, padx=5)
        ttk.Label(frame, text="高度:").grid(row=1, column=2, padx=5)
        entry_height = ttk.Entry(frame, width=8)
        entry_height.grid(row=1, column=3, padx=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=4, pady=5)
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
        self.load_config_values(config_key)

    def load_config_values(self, config_key):
        cfg = self.config_mgr.config.get(config_key, {})
        getattr(self, f"entry_{config_key}_left").insert(0, str(cfg.get("left", 0)))
        getattr(self, f"entry_{config_key}_top").insert(0, str(cfg.get("top", 0)))
        getattr(self, f"entry_{config_key}_width").insert(0, str(cfg.get("width", 0)))
        getattr(self, f"entry_{config_key}_height").insert(0, str(cfg.get("height", 0)))

    def start_capture(self, entry_left, entry_top):
        self.win.after(3000, lambda: self.capture_pos(entry_left, entry_top))

    def capture_pos(self, entry_left, entry_top):
        x, y = pyautogui.position()
        entry_left.delete(0, tk.END)
        entry_left.insert(0, str(x))
        entry_top.delete(0, tk.END)
        entry_top.insert(0, str(y))

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
        for key in ["ohlc_time_region", "ohlc_price_region", "ohlc_volume_region"]:
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
        messagebox.showinfo("保存成功", "三个区域配置已保存")
        if self.on_save:
            self.on_save()
        self.win.destroy()
