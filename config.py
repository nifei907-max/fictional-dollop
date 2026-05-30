"""全局配置模块（API Key 从环境变量读取）"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class CaptureConfig:
    monitor_index: int = 1
    left: int = 1722
    top: int = 283
    width: int = 61
    height: int = 26
    interval_seconds: float = 1.0

@dataclass
class OCRConfig:
    languages: list[str] = field(default_factory=lambda: ["en"])
    gpu: bool = False
    retry_times: int = 3
    retry_interval_seconds: float = 0.4
    min_confidence: float = 0.35
    tesseract_cmd: str = field(
        default_factory=lambda: os.getenv("TESSERACT_CMD", r"./Tesseract-OCR/tesseract.exe")
    )

@dataclass
class CandleConfig:
    interval_seconds: int = 60
    max_rows: int = 2000

@dataclass
class APIConfig:
    base_url: str = "https://api.deepseek.com"
    endpoint: str = "/chat/completions"
    model: str = "deepseek-chat"
    timeout_seconds: int = 20
    retry_times: int = 3
    retry_interval_seconds: float = 1.0
    api_key: str = field(
    default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "sk-your-api-key-here")
)

@dataclass
class AppConfig:
    symbol: str = "DEMO_SYMBOL"
    timezone: str = "UTC"
    poll_seconds: float = 1.0
    analyze_every_n_candles: int = 1
    data_dir: Path = Path("project/data")
    logs_dir: Path = Path("project/logs")
    tick_csv: Path = Path("project/data/ticks.csv")
    candle_csv: Path = Path("project/data/candles_1m.csv")
    log_file: Path = Path("project/logs/app.log")

@dataclass
class RuleConfig:
    enabled: bool = True
    rsi_long_threshold: float = 55.0
    rsi_short_threshold: float = 45.0

@dataclass
class NotifyConfig:
    cooldown_seconds: int = 120