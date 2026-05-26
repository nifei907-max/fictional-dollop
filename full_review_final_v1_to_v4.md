# 量化交易系统最终审查与优化落地版（第1~4批）

> 目标：给出可直接实施的“最终统一方案”，覆盖线程、队列、字段、风控、OCR、GUI、回测与配置。

## 一、最终结论（先看这个）

当前系统整体架构方向正确（事件驱动 + 多线程 + 状态中心），但若直接长时间运行，存在以下**高概率故障点**：

1. **队列竞争与阻塞**：`signal_queue` 被 GUI 和执行线程同时消费，消息会丢失；若 `put` 无超时，队列满会阻塞关键线程。
2. **字段不一致**：K线字段 `time`/`timestamp` 混用，导致指标、回测、图表、历史导入之间隐式错误。
3. **异常吞噬**：多个模块使用裸 `except`，线上故障难排查。
4. **跨平台问题**：`winsound`、`pyautogui` 等平台依赖没有降级分支。
5. **状态一致性风险**：同一持仓在 `execution_worker`/`risk_worker` 中并发读写，存在重复平仓/错账风险。

---

## 二、统一规范（必须落实）

### 1) 数据字段规范

- Candle dict/DataFrame 列统一：
  - `timestamp`, `open`, `high`, `low`, `close`, `volume`
- 禁止再写 `time`，如外部导入为 `time`，在入口层统一映射。

### 2) 队列规范

- 拆分信号队列：
  - `signal_queue_exec`（执行线程消费）
  - `signal_queue_ui`（GUI消费）
- 全部 `put/get` 使用超时 + 明确异常分支。

### 3) 异常规范

- 禁用裸 `except:`。
- 精确捕获：`queue.Empty`、`queue.Full`、`ValueError`、`requests.RequestException` 等。
- 统一 `logging`，禁止核心线程里长期 `print`。

### 4) 线程/状态规范

- `RuntimeState` 作为唯一共享状态中心，所有持仓更新都走其接口。
- 加“平仓幂等保护”（trade_id + closing flag + compare-and-set）。

---

## 三、逐模块最终优化建议（按文件）

## 1. `analysis_worker.py`

- 去除模块级全局 `data_mgr`，改依赖注入。
- candle 处理后调用 `task_done()`。
- 支持“手动触发分析”时不新增 candle（`None` 仅触发分析）。

## 2. `backtester.py`

- 开仓条件应为 `signal and pos is None`。
- 避免 `self.trades[-1]` 隐式引用，改 `current_trade_index`。
- 明确同一根K线止损/止盈优先级规则并文档化。

## 3. `candle_engine.py`

- 支持任意 `interval_seconds` 分桶（不止 1m）。
- 增加 `flush()`，停机时输出最后未封口K线。

## 4. `candle_worker.py`

- `queue.Empty` 精确捕获。
- `tick_queue.put/get` 采用超时策略，防阻塞。

## 5. `config_manager.py`

- `DEFAULT_CONFIG` 使用 `deepcopy`。
- 保存用临时文件 + `os.replace` 原子落盘。
- 增加 `version` + 迁移函数（schema migration）。

## 6. `config.py`

- `api_key` 默认空字符串，启动时强校验。
- 目录使用 `Path` 动态解析 + `mkdir(parents=True, exist_ok=True)`。

## 7. `deepseek_client.py`

- API key 空值时抛错。
- 只捕获网络与响应结构异常。
- 返回结构校验，避免 `choices[0]` 越界。

## 8. `execution_worker.py`

- 执行完成后，将信号副本广播到 `signal_queue_ui`（或 gui_queue）。
- 入场前检查当前是否空仓，避免重复开仓。

## 9. `history_viewer.py`

- 时间列解析做 `errors='coerce'`。
- Treeview 插入前清空旧行，避免重复展示。

## 10. `indicators.py`

- `add_candle` 同时兼容 `timestamp`/`time`，并在入口统一标准化。
- 减少频繁 `pd.concat`（可先缓存 list 批量转DF）。

## 11. `kline_chart.py`

- 刷新线程仅准备数据，绘图调用统一回到主线程（Tk线程安全）。
- 异常写日志并限频。

## 12. `kline_ocr_scraper.py`

- OCR解析异常精确捕获。
- 统一输出 `timestamp`。
- 抓取后排序去重（按 timestamp）。

## 13. `main_gui.py`

- 修复 `signal_queue` 双消费问题（最重要）。
- `sys.stdout` 重定向建议改 logger handler，避免第三方库输出异常。
- 线程启动加“已启动标记”，防止重复启动。

## 14. `main.py`

- 与 GUI 版本统一队列策略与异常策略。
- 输入线程避免裸异常吞错。

## 15. `notifier.py`

- 增加跨平台降级：非Windows改为 no-op + log。
- 增加最小间隔节流，避免高频蜂鸣。

## 16. `ocr_worker.py`

- OCR价格“偶数化”改可配置（tick_size/snap_to_even）。
- `TickFilter` 阈值改配置项。
- 截图区域非法时快速失败并日志提示。

## 17. `ohlc_settings_dialog.py`

- 校验 width/height > 0。
- 测试截图尽量内嵌预览，避免外部查看器泛滥。

## 18. `performance.py`

- `numpy` 未用可删。
- Sharpe 标记为“简化版”，避免误解为年化标准Sharpe。

## 19. `prompt_editor.py`

- 默认 prompt 应给完整模板（角色、输入、输出JSON约束、风险约束）。

## 20. `queues.py`

- 增加：
  - `signal_queue_exec = Queue(maxsize=50)`
  - `signal_queue_ui = Queue(maxsize=100)`
- 增设 `safe_put/safe_get` 工具函数。

## 21. `risk_worker.py`

- 平仓需幂等：`set_closing` 后二次检查 `position/trade_id`。
- `MAX_HOLD_SECONDS`、`TRAILING_STEPS` 配置化。

## 22. `runtime_state.py`

- 很好：已具备锁、浅拷贝、事件机制。
- 建议新增方法：
  - `try_open_position(pos) -> bool`
  - `try_close_position(trade_id) -> Optional[pos]`
  以消除并发竞态。

## 23. `settings_dialog.py`

- 与 OHLC 设置统一校验规则。
- 倒计时期间 UI 可显示剩余秒数。

## 24. `simulate.py`

- 导入 `time` 字段应立即映射为 `timestamp`。
- 推送 tick 建议可调速（x1/x5/x10）。

## 25. `spike_filter.py`

- 参数配置化并接入日志。
- 建议记录 block 原因到状态或日志文件。

## 26. `strategy_settings_dialog.py`

- 加参数范围校验（例如 rsi_upper > rsi_lower）。

## 27. `strategy.py`

- 与以上统一规范对齐：字段、队列、幂等与配置读取。

---

## 四、最终“最小可上线改造包”（按优先级）

### P0（本周必须）
1. 统一 `timestamp` 字段并做兼容映射层。
2. 拆分 `signal_queue_exec/signal_queue_ui`。
3. 去掉所有裸异常并接入 logging。
4. backtester 开仓条件修正（空仓开仓）。

### P1（下一步）
1. `RuntimeState` 增加 CAS 风格开平仓接口。
2. OCR/风控参数配置化。
3. 原子配置写入 + 版本迁移。

### P2（优化）
1. 图表刷新线程与主线程职责分离。
2. 回测成交模型参数化（滑点/手续费/触发优先级）。
3. 指标计算性能优化（减少 DataFrame 复制）。

---

## 五、回归测试清单（建议）

1. **线程稳定性**：连续运行 2~4 小时，检查队列积压、CPU占用、内存增长。
2. **信号一致性**：同一行情下 GUI 显示信号 == 执行线程接收信号。
3. **字段一致性**：全链路仅出现 `timestamp`（可用脚本扫描）。
4. **风控幂等性**：高波动时不会重复平同一单。
5. **回测一致性**：已知样本下交易笔数、净值结果可复现。
6. **OCR容错**：故意遮挡/噪声截图，系统可恢复且日志可定位问题。

---

## 六、交付说明

你已经把 1~4 批代码全部发完了。基于当前信息，以上文档就是“最终整合版设计说明”。

如果你下一步要我给“**真正可直接覆盖的最终代码版本**”，我建议按以下顺序输出（每次 4~6 个文件，避免过长）：
1. 核心线程与状态层（queues/runtime_state/analysis/candle/execution/risk）
2. 数据与回测层（indicators/backtester/performance/simulate）
3. OCR与抓取层（ocr_worker/kline_ocr_scraper/settings dialogs）
4. GUI层（main_gui/history_viewer/kline_chart/prompt/strategy settings）

