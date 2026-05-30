"""AI 提示词编辑器"""
import tkinter as tk
from tkinter import ttk, messagebox
from config_manager import ConfigManager

DEFAULT_PROMPT = """你是专业量化交易分析AI。..."""

class PromptEditor:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback
        self.win = tk.Toplevel(root)
        self.win.title("🧠 AI 提示词编辑器")
        self.win.geometry("650x550")
        self.win.resizable(True, True)
        self.win.transient(root)
        self.win.grab_set()
        ttk.Label(self.win, text="修改 DeepSeek AI 系统提示词", font=("微软雅黑", 10)).pack(pady=5)
        text_frame = ttk.Frame(self.win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.text_widget = tk.Text(text_frame, wrap=tk.WORD, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(text_frame, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scrollbar.set)
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="💾 保存", command=self.save_prompt).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 恢复默认", command=self.reset_default).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="❌ 取消", command=self.win.destroy).pack(side=tk.LEFT, padx=5)
        self.load_current_prompt()

    def load_current_prompt(self):
        prompt = self.config_mgr.get_system_prompt()
        if not prompt: prompt = DEFAULT_PROMPT
        self.text_widget.delete(1.0, tk.END)
        self.text_widget.insert(tk.END, prompt)

    def save_prompt(self):
        new_prompt = self.text_widget.get(1.0, tk.END).strip()
        if not new_prompt: messagebox.showerror("错误", "提示词不能为空"); return
        self.config_mgr.set_system_prompt(new_prompt)
        messagebox.showinfo("成功", "AI 提示词已更新")
        if self.on_save: self.on_save()
        self.win.destroy()

    def reset_default(self):
        self.text_widget.delete(1.0, tk.END)
        self.text_widget.insert(tk.END, DEFAULT_PROMPT)