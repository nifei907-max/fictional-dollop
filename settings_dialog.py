"""OCR 截图区域设置对话框（实时价格）"""
import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui
from config_manager import ConfigManager

class SettingsDialog:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("⚙️ OCR 截图区域配置")
        self.win.geometry("450x300")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.grab_set()
        self.create_widgets()
        self.load_current_config()

    def create_widgets(self):
        coord_frame = ttk.LabelFrame(self.win, text="截图区域坐标 (像素)", padding=10)
        coord_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(coord_frame, text="X (左):").grid(row=0, column=0, padx=5, pady=2)
        self.entry_left = ttk.Entry(coord_frame, width=8); self.entry_left.grid(row=0, column=1, padx=5)
        ttk.Label(coord_frame, text="Y (上):").grid(row=0, column=2, padx=5)
        self.entry_top = ttk.Entry(coord_frame, width=8); self.entry_top.grid(row=0, column=3, padx=5)
        ttk.Label(coord_frame, text="宽度:").grid(row=1, column=0, padx=5, pady=2)
        self.entry_width = ttk.Entry(coord_frame, width=8); self.entry_width.grid(row=1, column=1, padx=5)
        ttk.Label(coord_frame, text="高度:").grid(row=1, column=2, padx=5)
        self.entry_height = ttk.Entry(coord_frame, width=8); self.entry_height.grid(row=1, column=3, padx=5)

        btn_frame = ttk.Frame(coord_frame)
        btn_frame.grid(row=2, column=0, columnspan=4, pady=10)
        self.btn_capture = ttk.Button(btn_frame, text="🖱️ 鼠标拾取 (3秒)", command=self.start_capture)
        self.btn_capture.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📸 测试截图", command=self.test_screenshot).pack(side=tk.LEFT, padx=5)

        action_frame = ttk.Frame(self.win)
        action_frame.pack(pady=10)
        ttk.Button(action_frame, text="💾 保存配置", command=self.save_config).pack(side=tk.LEFT, padx=10)
        ttk.Button(action_frame, text="❌ 取消", command=self.win.destroy).pack(side=tk.LEFT, padx=10)

    def load_current_config(self):
        cfg = self.config_mgr.config["capture"]
        self.entry_left.insert(0, str(cfg["left"]))
        self.entry_top.insert(0, str(cfg["top"]))
        self.entry_width.insert(0, str(cfg["width"]))
        self.entry_height.insert(0, str(cfg["height"]))

    def start_capture(self):
        self.btn_capture.config(text="正在捕获...", state="disabled")
        self.win.after(3000, self.capture_pos)

    def capture_pos(self):
        x, y = pyautogui.position()
        self.entry_left.delete(0, tk.END); self.entry_left.insert(0, str(x))
        self.entry_top.delete(0, tk.END); self.entry_top.insert(0, str(y))
        self.btn_capture.config(text="🖱️ 鼠标拾取 (3秒)", state="normal")

    def test_screenshot(self):
        try:
            left = int(self.entry_left.get()); top = int(self.entry_top.get())
            width = int(self.entry_width.get()); height = int(self.entry_height.get())
            img = pyautogui.screenshot(region=(left, top, width, height))
            img.show()
        except Exception as e: messagebox.showerror("截图失败", str(e))

    def save_config(self):
        try:
            left = int(self.entry_left.get()); top = int(self.entry_top.get())
            width = int(self.entry_width.get()); height = int(self.entry_height.get())
            self.config_mgr.set_capture_region(left, top, width, height)
            if self.on_save: self.on_save()
            messagebox.showinfo("保存成功", "配置已保存")
            self.win.destroy()
        except ValueError: messagebox.showerror("输入错误", "请输入有效数字")