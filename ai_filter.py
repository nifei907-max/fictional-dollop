"""
AI 信号分析器（替代 AI 过滤器）

设计目标：
1. 不阻塞交易信号
2. AI 仅负责解释和辅助分析
3. AI 失败不影响系统运行
4. 适用于 1分钟超短线 + OCR 行情系统
"""

from deepseek_client import DeepSeekClient
from config import APIConfig


api_cfg = APIConfig()
ai_client = DeepSeekClient(api_cfg)


class AIFilter:
    """兼容旧接口：永远放行信号，AI 只负责生成解释。"""

    def __init__(self):
        self.enabled = True

    def check_signal(self, side, indicators, price):
        """兼容旧代码，永远放行，不参与交易拦截。"""
        return True

    def explain_signal(self, side, indicators, price):
        """返回 AI 辅助分析文本。"""
        if not self.enabled:
            return "AI分析已关闭"

        try:
            prompt = self._build_prompt(side, indicators, price)
            result = ai_client.analyze(prompt)
            return str(result).strip()
        except Exception as e:
            print(f"AI分析失败: {e}")
            return "AI分析失败"

    def _build_prompt(self, side, indicators, price):
        return f"""
你是一名专业短线交易分析师。

交易方向:
{side}

当前价格:
{price}

市场指标:
RSI: {round(indicators.get('rsi', 0), 2)}
ATR: {round(indicators.get('atr', 0), 2)}
趋势: {indicators.get('trend', '未知')}
MACD多头: {indicators.get('macd_bullish', False)}
MACD空头: {indicators.get('macd_bearish', False)}

请用简洁中文回答：
1. 当前市场状态
2. 为什么出现该信号
3. 风险点
4. 信号强度（1~10分）

控制在100字以内。
"""
