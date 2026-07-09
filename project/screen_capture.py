"""屏幕截图模块。"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import mss
import numpy as np

from config import CaptureConfig


@dataclass
class ScreenCapture:
    """负责按配置抓取指定屏幕区域。"""

    cfg: CaptureConfig

    def capture(self) -> np.ndarray:
        """抓取屏幕并返回 BGR 图像。"""
        monitor = {
            "left": self.cfg.left,
            "top": self.cfg.top,
            "width": self.cfg.width,
            "height": self.cfg.height,
            "mon": self.cfg.monitor_index,
        }
        with mss.mss() as sct:
            raw = sct.grab(monitor)
            img = np.array(raw)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
