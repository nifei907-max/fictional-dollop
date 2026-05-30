"""
系统健康监控
"""

import threading
import time
import psutil
from logger_utils import log_warning, log_info


class HealthMonitor:

    def __init__(self):

        self.running = False

        self.cpu_limit = 85
        self.memory_limit = 85

        self.check_interval = 10

    def start(self):

        if self.running:
            return

        self.running = True

        threading.Thread(
            target=self._run,
            daemon=True
        ).start()

        log_info("系统健康监控启动")

    def stop(self):

        self.running = False

        log_info("系统健康监控停止")

    def _run(self):

        while self.running:

            try:

                cpu = psutil.cpu_percent(interval=1)

                memory = psutil.virtual_memory().percent

                if cpu >= self.cpu_limit:
                    log_warning(
                        f"CPU占用过高: {cpu}%"
                    )

                if memory >= self.memory_limit:
                    log_warning(
                        f"内存占用过高: {memory}%"
                    )

            except Exception as e:

                log_warning(
                    f"健康监控异常: {e}"
                )

            time.sleep(self.check_interval)