"""
策略参数设置对话框（匹配新策略，分组显示，动态读取）
"""
import tkinter as tk
from tkinter import ttk, messagebox
from config_manager import ConfigManager

PARAMETER_GROUPS = {
    "EMA & 趋势强度": [
        ("EMA 短周期", "EMA_SHORT"),
        ("EMA 中周期", "EMA_MID"),
        ("EMA 长周期", "EMA_LONG"),
        ("趋势强度高阈值", "TREND_STRENGTH_HIGH"),
        ("趋势强度低阈值", "TREND_STRENGTH_LOW"),
    ],
    "RSI 阈值": [
        ("RSI 周期", "RSI_PERIOD"),
        ("做多 RSI 下限", "RSI_LONG_THRESHOLD"),
        ("做空 RSI 上限", "RSI_SHORT_THRESHOLD"),
        ("多头过热 RSI 上限", "RSI_LONG_MAX"),
        ("空头过冷 RSI 下限", "RSI_SHORT_MIN"),
        ("横盘做多 RSI 下限", "RSI_OS_LONG"),
        ("横盘做空 RSI 上限", "RSI_OB_SHORT"),
    ],
    "风控与冷却": [
        ("信号冷却(秒)", "SIGNAL_COOLDOWN"),
        ("方向锁(秒)", "DIRECTION_LOCK_TIME"),
        ("止损后冷却(秒)", "STOP_AFTER_LOSS"),
        ("连续止损熔断次数", "MAX_CONSECUTIVE_LOSS"),
        ("熔断暂停(秒)", "PAUSE_AFTER_MAX_LOSS"),
    ],
    "波动与距离": [
        ("最小波动", "MIN_RANGE"),
        ("最大波动", "MAX_RANGE"),
        ("追高限制(点)", "MAX_DISTANCE_FROM_LOW"),
        ("追低限制(点)", "MAX_DISTANCE_FROM_HIGH"),
    ],
    "止盈止损 & ATR": [
        ("趋势止损 ATR 倍数", "TREND_STOP_MULT"),
        ("趋势止盈 ATR 倍数", "TREND_TAKE_MULT"),
        ("震荡止损 ATR 倍数", "RANGE_STOP_MULT"),
        ("震荡止盈 ATR 倍数", "RANGE_TAKE_MULT"),
        ("ATR 斜率因子", "ATR_SLOPE_FACTOR"),
        ("ATR 突破因子", "ATR_BREAKOUT_FACTOR"),
    ],
    "成交量 & 其他": [
        ("成交量均线周期", "VOL_MA_PERIOD"),
        ("成交量比率", "VOL_RATIO"),
        ("连续K线衰竭数", "EXHAUSTION_COUNT"),
        ("回踩最大等待K线", "PULLBACK_MAX_BARS"),
    ],
}

class StrategySettingsDialog:
    def __init__(self, root, config_mgr: ConfigManager, on_save_callback=None):
        self.config_mgr = config_mgr
        self.on_save = on_save_callback

        self.win = tk.Toplevel(root)
        self.win.title("📈 策略参数配置")
        self.win.geometry("600x550")
        self.win.resizable(True, True)
        self.win.transient(root)
        self.win.grab_set()

        style = ttk.Style(self.win)
        style.theme_use('clam')
        style.configure('TNotebook.Tab', font=('微软雅黑', 10, 'bold'), padding=[10, 4])
        style.configure('TLabel', font=('微软雅黑', 10), background='#f5f6fa')

        self.notebook = ttk.Notebook(self.win)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.entries = {}

        for group_name, params in PARAMETER_GROUPS.items():
            frame = ttk.Frame(self.notebook, padding=15)
            self.notebook.add(frame, text=group_name)
            for row, (label, param_key) in enumerate(params):
                ttk.Label(frame, text=label + ":").grid(row=row, column=0, sticky=tk.W, padx=5, pady=3)
                entry = ttk.Entry(frame, width=12, font=('微软雅黑', 10))
                entry.grid(row=row, column=1, padx=5, pady=3, sticky=tk.W)
                self.entries[param_key] = entry

        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="💾 保存设置", command=self.save_params).pack(side=tk.LEFT, padx=20)
        ttk.Button(btn_frame, text="❌ 取消", command=self.win.destroy).pack(side=tk.LEFT, padx=20)

        self.load_current_params()

    def load_current_params(self):
        from strategy import DEFAULT_PARAMS as strategy_defaults
        user_params = self.config_mgr.get_strategy_params()
        for key, entry in self.entries.items():
            val = user_params.get(key, strategy_defaults.get(key, ""))
            entry.delete(0, tk.END)
            entry.insert(0, str(val))

    def save_params(self):
        new_params = {}
        for key, entry in self.entries.items():
            try:
                new_params[key] = float(entry.get())
            except ValueError:
                messagebox.showerror("输入错误", f"参数 {key} 必须为数字")
                return
        self.config_mgr.config["strategy"] = new_params
        self.config_mgr.save()
        messagebox.showinfo("保存成功", "策略参数已更新，下次分析生效")
        if self.on_save:
            self.on_save()
        self.win.destroy()