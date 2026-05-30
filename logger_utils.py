"""
日志模块
"""

import logging
import os
from datetime import datetime


LOG_DIR = "logs"

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

log_file = os.path.join(
    LOG_DIR,
    f"{datetime.now().strftime('%Y-%m-%d')}.log"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("trading_system")


def log_info(msg):
    logger.info(msg)


def log_warning(msg):
    logger.warning(msg)


def log_error(msg):
    logger.error(msg)


def log_trade(side, entry, stop, take, reason):
    logger.info(
        f"[交易信号] "
        f"{side} | "
        f"入场:{entry} "
        f"止损:{stop} "
        f"止盈:{take} "
        f"原因:{reason}"
    )


def log_position_close(side, entry, exit_price, pnl, reason):
    logger.info(
        f"[平仓] "
        f"{side} | "
        f"开仓:{entry} "
        f"平仓:{exit_price} "
        f"盈亏:{pnl:.2f} "
        f"原因:{reason}"
    )