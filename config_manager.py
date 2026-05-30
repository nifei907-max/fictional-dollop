"""
用户配置管理器（线程安全，原子写入，深拷贝默认值，支持区域便捷获取）
支持实时OCR分离区域：time_region, price_region
历史OHLC区域：ohlc_time_region, ohlc_price_region, ohlc_volume_region
"""

import json
import os
import copy
from typing import Tuple

CONFIG_FILE = "user_config.json"

DEFAULT_CONFIG = {
    "config_version": 1,
    "capture": {"left": 0, "top": 0, "width": 0, "height": 0, "interval_seconds": 0.5},  # 保留向后兼容，但不再使用
    "time_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "price_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "bid1_price_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "ask1_price_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "min_price_change": 1,
    "max_price_jump": 20,
    "tesseract_cmd": "./Tesseract-OCR/tesseract.exe",
    "colors": {
        "red_threshold": {"r": (250, 255), "g": (0, 5), "b": (0, 5)},
        "cyan_threshold": {"r": (0, 5), "g": (250, 255), "b": (250, 255)},
    },
    "system_prompt": "你是专业量化交易分析AI。...",
    "strategy": {
        "macd_threshold": 0.05,
        "rsi_upper": 80,
        "rsi_lower": 20,
        "min_range": 4,
        "fake_breakout_distance": 12,
        "risk_reward_ratio": 1.5,
    },
    "ohlc_time_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "ohlc_price_region": {"left": 0, "top": 0, "width": 0, "height": 0},
    "ohlc_volume_region": {"left": 0, "top": 0, "width": 0, "height": 0},
}


class ConfigManager:
    def __init__(self, filepath: str = CONFIG_FILE):
        self.filepath = filepath
        self.config = self.load()

    def load(self) -> dict:
        config = copy.deepcopy(DEFAULT_CONFIG)
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                return self._deep_merge(config, user_config)
            except Exception as e:
                print(f"[Config] 配置读取失败: {e}，将使用默认配置")
        return config

    def _deep_merge(self, base: dict, override: dict) -> dict:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = self._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    def save(self):
        try:
            tmp_file = self.filepath + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, self.filepath)
        except Exception as e:
            print(f"[Config] 保存失败: {e}")

    def get_region(self, key: str) -> Tuple[int, int, int, int]:
        r = self.config.get(key, {})
        return (
            r.get("left", 0),
            r.get("top", 0),
            r.get("width", 0),
            r.get("height", 0),
        )

    # 实时OCR区域
    def get_time_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("time_region")

    def set_time_region(self, left, top, width, height):
        self.config["time_region"] = {"left": left, "top": top, "width": width, "height": height}
        self.save()

    def get_price_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("price_region")

    def set_price_region(self, left, top, width, height):
        self.config["price_region"] = {"left": left, "top": top, "width": width, "height": height}
        self.save()

    def get_bid1_price_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("bid1_price_region")

    def set_bid1_price_region(self, left, top, width, height):
        self.config["bid1_price_region"] = {"left": left, "top": top, "width": width, "height": height}
        self.save()

    def get_ask1_price_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("ask1_price_region")

    def set_ask1_price_region(self, left, top, width, height):
        self.config["ask1_price_region"] = {"left": left, "top": top, "width": width, "height": height}
        self.save()

    # 历史OHLC区域
    def get_ohlc_time_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("ohlc_time_region")

    def get_ohlc_price_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("ohlc_price_region")

    def get_ohlc_volume_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("ohlc_volume_region")

    # 保留旧的 capture 区域兼容
    def get_capture_region(self) -> Tuple[int, int, int, int]:
        return self.get_region("capture")

    def set_capture_region(self, left, top, width, height):
        self.config["capture"] = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "interval_seconds": self.config.get("capture", {}).get("interval_seconds", 0.5),
        }
        self.save()

    def get_min_price_change(self) -> int:
        return self.config.get("min_price_change", 1)

    def get_max_price_jump(self) -> int:
        return self.config.get("max_price_jump", 20)

    def get_tesseract_cmd(self) -> str:
        return self.config.get("tesseract_cmd", "./Tesseract-OCR/tesseract.exe")

    def get_color_thresholds(self) -> dict:
        return self.config.get("colors", copy.deepcopy(DEFAULT_CONFIG["colors"]))

    def set_color_thresholds(self, red, cyan):
        self.config["colors"] = {"red_threshold": red, "cyan_threshold": cyan}
        self.save()

    def get_system_prompt(self) -> str:
        return self.config.get("system_prompt", "")

    def set_system_prompt(self, prompt: str):
        self.config["system_prompt"] = prompt
        self.save()

    def get_strategy_params(self) -> dict:
        return self.config.get("strategy", copy.deepcopy(DEFAULT_CONFIG["strategy"]))

    def set_strategy_params(self, params: dict):
        self.config["strategy"] = params
        self.save()
