"""全局配置模块。

集中管理所有可调参数，避免散落在业务代码中，便于部署和维护。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CaptureConfig:
    """截图区域配置（单位：像素）。"""

    monitor_index: int = 1
    left: int = 100
    top: int = 100
    width: int = 500
    height: int = 120
    interval_seconds: float = 1.0


@dataclass
class OCRConfig:
    """OCR 识别配置。"""

    languages: list[str] = field(default_factory=lambda: ["en"])
    gpu: bool = False
    retry_times: int = 3
    retry_interval_seconds: float = 0.4
    min_confidence: float = 0.35


@dataclass
class CandleConfig:
    """K线聚合与数据缓冲配置。"""

    interval_seconds: int = 60
    max_rows: int = 2000


@dataclass
class APIConfig:
    """DeepSeek API 配置。"""

    base_url: str = "https://api.deepseek.com"
    endpoint: str = "/chat/completions"
    model: str = "deepseek-chat"
    timeout_seconds: int = 20
    retry_times: int = 3
    retry_interval_seconds: float = 1.0
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))


@dataclass
class AppConfig:
    """应用主配置。"""

    symbol: str = "DEMO_SYMBOL"
    timezone: str = "UTC"
    poll_seconds: float = 1.0
    analyze_every_n_candles: int = 1
    data_dir: Path = Path("project/data")
    logs_dir: Path = Path("project/logs")
    tick_csv: Path = Path("project/data/ticks.csv")
    candle_csv: Path = Path("project/data/candles_1m.csv")
    log_file: Path = Path("project/logs/app.log")


# DeepSeek System Prompt（可按策略继续扩展）
DEEPSEEK_SYSTEM_PROMPT = """你是专业量化交易分析AI。

你的任务：
根据输入的结构化行情数据，判断当前市场是否适合：LONG、SHORT、HOLD。

你必须严格依据：趋势方向、EMA均线、RSI、MACD、成交量、波动率、支撑阻力、K线结构。

规则：
1. 禁止猜测
2. 禁止模糊表达
3. 信号不明确必须返回 HOLD
4. 不允许输出JSON以外内容
5. 必须给出明确理由
6. 必须控制风险
7. 如果趋势不清晰必须观望

最终只能返回JSON，格式如下：
{
  "signal": "LONG/SHORT/HOLD",
  "confidence": 0,
  "entry": 0,
  "stop_loss": 0,
  "take_profit": 0,
  "risk_level": "LOW/MEDIUM/HIGH",
  "reason": ""
}
"""
