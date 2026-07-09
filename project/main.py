"""主程序入口（第二阶段增强版）。"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from config import APIConfig, AppConfig, CandleConfig, CaptureConfig, NotifyConfig, OCRConfig, RuleConfig
from deepseek_client import DeepSeekClient
from indicators import MarketDataManager
from notifier import Notifier
from ocr_reader import OCRReader
from rule_engine import RuleEngine
from screen_capture import ScreenCapture
from strategy import StrategyBuilder


def setup_logger(log_file: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )


def main() -> None:
    app_cfg = AppConfig()
    app_cfg.data_dir.mkdir(parents=True, exist_ok=True)
    app_cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    setup_logger(str(app_cfg.log_file))

    capture = ScreenCapture(CaptureConfig())
    ocr = OCRReader(OCRConfig())
    data_mgr = MarketDataManager(CandleConfig(), app_cfg.tick_csv, app_cfg.candle_csv)
    deepseek = DeepSeekClient(APIConfig())
    strategy = StrategyBuilder()
    notifier = Notifier(NotifyConfig())
    rule_cfg = RuleConfig()
    fallback_rule = RuleEngine(rule_cfg.rsi_long_threshold, rule_cfg.rsi_short_threshold)

    logging.info("系统启动完成，开始循环采集。")

    while True:
        try:
            image = capture.capture()
            price = ocr.read_price(image)
            if price is None:
                logging.warning("OCR 未识别到价格，等待下一轮。")
                time.sleep(app_cfg.poll_seconds)
                continue

            now = datetime.now(timezone.utc)
            data_mgr.add_tick(now, price, volume=1.0)
            candles = data_mgr.build_candles()
            candles = data_mgr.compute_indicators()
            data_mgr.persist()

            if len(candles) < 60:
                logging.info("K线不足60根，继续积累数据。")
                time.sleep(app_cfg.poll_seconds)
                continue

            prompt = strategy.build_prompt(candles)
            try:
                result = deepseek.analyze(prompt)
                logging.info("DeepSeek 返回：%s", json.dumps(result, ensure_ascii=False))
            except Exception as api_exc:
                logging.exception("DeepSeek 调用失败，切换本地规则兜底：%s", api_exc)
                if rule_cfg.enabled:
                    result = fallback_rule.analyze(candles)
                else:
                    result = {"signal": "HOLD", "reason": "API失败且未启用兜底规则"}

            signal = result.get("signal", "HOLD")
            reason = result.get("reason", "无说明")
            if signal in {"LONG", "SHORT"}:
                notifier.notify(signal, reason)

        except Exception as exc:
            logging.exception("主循环异常：%s", exc)

        time.sleep(app_cfg.poll_seconds)


if __name__ == "__main__":
    main()
