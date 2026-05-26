# 最终替换顺序清单（按依赖顺序，降低踩坑）

> 目标：把你已拿到的三份代码包按安全顺序落地，确保一次替换可启动。

## 你现在已有的三份包

1. `FULL_27_FILES_COPYABLE.md`（核心 1~15）
2. `FULL_27_REMAINING_UI_OCR.md`（UI/OCR 12 文件）
3. `FULL_COPYABLE_VERSION.md`（单文件联调版，可做对照）

---

## A. 替换顺序（必须按这个顺序）

### 第 1 组：基础与共享层（先替）
1. `queues.py`
2. `config.py`
3. `config_manager.py`
4. `runtime_state.py`

**检查点 A：**
- `queues.py` 必须有：`signal_queue_exec` 和 `signal_queue_ui`。
- `runtime_state.py` 的 `get_position()` 返回拷贝对象。

### 第 2 组：数据与策略层
5. `indicators.py`
6. `strategy.py`
7. `candle_engine.py`
8. `performance.py`
9. `backtester.py`

**检查点 B：**
- Candle 字段统一为 `timestamp/open/high/low/close/volume`。
- `backtester.py` 开仓条件是 `signal and pos is None`。

### 第 3 组：核心线程层
10. `analysis_worker.py`
11. `candle_worker.py`
12. `execution_worker.py`
13. `risk_worker.py`
14. `notifier.py`
15. `ocr_worker.py`

**检查点 C：**
- `analysis_worker.py` 同时投递：
  - `signal_queue_exec`
  - `signal_queue_ui`
- `main_gui.py` 不能再消费 `signal_queue_exec`。

### 第 4 组：GUI 展示与设置层
16. `main_gui.py`
17. `kline_chart.py`
18. `history_viewer.py`
19. `settings_dialog.py`
20. `ohlc_settings_dialog.py`
21. `prompt_editor.py`
22. `strategy_settings_dialog.py`

**检查点 D：**
- GUI 只从 `signal_queue_ui` 读取信号。
- 设置对话框保存后，`config_manager.save()` 正常落盘。

### 第 5 组：工具与模拟层
23. `deepseek_client.py`
24. `kline_ocr_scraper.py`
25. `simulate.py`
26. `spike_filter.py`
27. `main.py`

**检查点 E：**
- `simulate.py` 导入数据时将 `time` 映射到 `timestamp`。
- `main.py` 与 GUI 线程模型一致（不再使用旧队列语义）。

---

## B. 替换后 10 分钟自检（直接复制执行）

```bash
# 1) 语法快速检查
python -m py_compile *.py

# 2) 扫描是否还混用 time 字段（允许在兼容映射处出现）
rg '"time"|\btime\b' *.py

# 3) 确认 signal 队列拆分已落地
rg 'signal_queue_exec|signal_queue_ui' *.py

# 4) 确认没有裸 except
rg '^\s*except\s*:\s*$' *.py
```

---

## C. 运行顺序建议

### 先跑命令行
```bash
python main.py
```
- 观察 1~2 分钟：是否有价格更新、是否有卡死。

### 再跑 GUI
```bash
python main_gui.py
```
- 检查：价格刷新、信号刷新、历史窗口、K线图窗口。

### 最后跑模拟
```bash
python simulate.py
```
- 检查：是否能喂数据、是否触发信号、是否可回测。

---

## D. 常见报错与快速修复

1. **`ImportError: signal_queue`**
   - 原因：旧代码仍在 import 单队列名。
   - 修复：改为 `signal_queue_exec` 或 `signal_queue_ui`。

2. **`KeyError: 'timestamp'`**
   - 原因：某处仍在生成 `time` 未映射。
   - 修复：入口层统一 `ts = candle.get("timestamp", candle.get("time"))`。

3. **GUI 不显示信号**
   - 原因：信号只进了 exec 队列。
   - 修复：`analysis_worker` 同步 put 到 `signal_queue_ui`。

4. **OCR 无输出**
   - 原因：截图区域宽高无效或 tesseract 路径错误。
   - 修复：先在 `settings_dialog` 里重设区域，再检查 `tesseract_cmd`。

---

## E. 建议你现在立刻做的事

1. 按 A 顺序覆盖全部文件。
2. 跑 B 四条检查命令。
3. 跑 C 三个入口（main / GUI / simulate）。
4. 把报错原文贴给我，我会按报错逐条给你热修补丁。

