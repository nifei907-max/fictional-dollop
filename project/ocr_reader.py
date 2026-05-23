"""OCR识别模块，包含图像预处理与重试机制。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import easyocr
import numpy as np

from config import OCRConfig


@dataclass
class OCRReader:
    cfg: OCRConfig

    def __post_init__(self) -> None:
        self.reader = easyocr.Reader(self.cfg.languages, gpu=self.cfg.gpu)

    @staticmethod
    def _preprocess(image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return th

    @staticmethod
    def _extract_price(text: str) -> Optional[float]:
        cleaned = text.replace(",", "")
        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        return float(match.group())

    def read_price(self, image: np.ndarray) -> Optional[float]:
        """读取价格；失败时自动重试。"""
        preprocessed = self._preprocess(image)
        for i in range(self.cfg.retry_times):
            results = self.reader.readtext(preprocessed, detail=1)
            best_price: Optional[float] = None
            best_conf = 0.0
            for _, text, conf in results:
                price = self._extract_price(text)
                if price is not None and conf >= self.cfg.min_confidence and conf > best_conf:
                    best_price = price
                    best_conf = conf
            if best_price is not None:
                return best_price
            if i < self.cfg.retry_times - 1:
                time.sleep(self.cfg.retry_interval_seconds)
        return None
