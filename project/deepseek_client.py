"""DeepSeek API 客户端。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests

from config import APIConfig, DEEPSEEK_SYSTEM_PROMPT


@dataclass
class DeepSeekClient:
    cfg: APIConfig

    def _build_url(self) -> str:
        return f"{self.cfg.base_url.rstrip('/')}{self.cfg.endpoint}"

    def analyze(self, user_prompt: str) -> dict[str, Any]:
        if not self.cfg.api_key:
            raise ValueError("未配置 DEEPSEEK_API_KEY")

        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        }

        for i in range(self.cfg.retry_times):
            try:
                resp = requests.post(self._build_url(), headers=headers, json=payload, timeout=self.cfg.timeout_seconds)
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
                return json.loads(text)
            except Exception:
                if i == self.cfg.retry_times - 1:
                    raise
                time.sleep(self.cfg.retry_interval_seconds)
        raise RuntimeError("DeepSeek 请求重试后仍失败")
