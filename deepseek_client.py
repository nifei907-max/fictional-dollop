"""DeepSeek API 封装"""
import requests
from config import APIConfig

class DeepSeekClient:
    def __init__(self, config: APIConfig):
        self.base_url = config.base_url
        self.endpoint = config.endpoint
        self.model = config.model
        self.api_key = config.api_key
        self.timeout = config.timeout_seconds

    def analyze(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a professional quantitative trading analyst."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 200,
            "temperature": 0.1
        }
        try:
            resp = requests.post(
                f"{self.base_url}{self.endpoint}",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"API Error: {e}"