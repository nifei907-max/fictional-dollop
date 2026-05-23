# 半自动交易分析系统（截图 + OCR + 指标 + DeepSeek）

## 1. 项目架构设计

```text
project/
├── main.py               # 主循环：截图→OCR→K线→指标→API→通知
├── config.py             # 全部配置与System Prompt
├── screen_capture.py     # mss 实时截图
├── ocr_reader.py         # OpenCV预处理 + EasyOCR识别 + 重试
├── indicators.py         # tick存储、1分钟K线聚合、技术指标计算
├── deepseek_client.py    # DeepSeek API 调用 + 重试 + JSON解析
├── strategy.py           # 构造 DeepSeek USER PROMPT
├── notifier.py           # tkinter 弹窗
├── data/                 # ticks.csv / candles_1m.csv
└── logs/                 # app.log
```

### 模块职责
- `main.py`：负责调度各模块，控制循环频率，统一异常捕获与日志。
- `config.py`：集中管理截图区域、OCR阈值、API重试次数、文件路径等参数。
- `ocr_reader.py`：OCR失败自动重试，返回 `float` 价格。
- `deepseek_client.py`：API失败自动重试，并强制按 JSON 解析。

---

## 2. 安装教程

### 2.1 创建虚拟环境
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2.2 安装依赖
```bash
pip install -r requirements.txt
```

### 2.3 EasyOCR 模型说明
首次运行 EasyOCR 会自动下载模型，请保证网络可访问。

---

## 3. 运行教程

```bash
python project/main.py
```

运行后程序会：
1. 按 `config.py` 的截图坐标抓取屏幕。
2. OCR识别价格。
3. 追加到 `project/data/ticks.csv`。
4. 自动聚合为 1 分钟 K 线到 `project/data/candles_1m.csv`。
5. 计算 EMA20 / EMA50 / RSI / MACD / ATR。
6. 调用 DeepSeek，拿到 JSON 信号。
7. LONG/SHORT 时用 tkinter 弹窗提醒。

---

## 4. DeepSeek API 配置方法

### 4.1 设置环境变量
```bash
export DEEPSEEK_API_KEY="你的Key"      # Windows PowerShell: $env:DEEPSEEK_API_KEY="你的Key"
```

### 4.2 可选调整（`project/config.py`）
- `APIConfig.base_url` 默认：`https://api.deepseek.com`
- `APIConfig.endpoint` 默认：`/chat/completions`
- `APIConfig.model` 默认：`deepseek-chat`
- `retry_times` / `timeout_seconds` 可按网络情况调整。

---

## 5. 配置要点（上线前必须改）

1. **截图区域**：修改 `CaptureConfig` 的 `left/top/width/height`，确保只包含价格区域。
2. **OCR阈值**：`OCRConfig.min_confidence` 可在 0.3~0.7 间测试。
3. **行情量能**：当前示例 `volume=0.0`，建议后续接入真实成交量来源。
4. **风险控制**：收到 LONG/SHORT 后仍应人工二次确认，系统定位为半自动分析。

---

## 6. JSON返回格式约束
DeepSeek 必须仅返回：

```json
{
  "signal": "LONG/SHORT/HOLD",
  "confidence": 0,
  "entry": 0,
  "stop_loss": 0,
  "take_profit": 0,
  "risk_level": "LOW/MEDIUM/HIGH",
  "reason": ""
}
```

如返回非 JSON，`deepseek_client.py` 会抛错并触发重试。
