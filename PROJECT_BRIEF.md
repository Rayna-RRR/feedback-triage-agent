# Project Brief

## 目标用户

- AI 产品实习生、产品助理、AI 应用运营。
- 需要处理应用商店评论、客服工单、社区反馈、用户访谈记录的产品团队成员。

## 业务问题

用户反馈通常是非结构化文本，来源分散，质量不一。产品团队需要快速判断：

- 反馈是否字段齐全。
- 反馈主要属于哪类问题。
- 是否存在 P0 风险。
- 哪些样本不能直接自动判断，需要人工复核。
- 如何把用户原话转成可讨论的问题卡片和产品建议。

## 当前范围

v0.8.1 实现一个本地 CLI + FastAPI Web App Demo：

- 读取 `sample_feedback.csv`。
- 校验必填字段。
- 默认使用 DeepSeek V4 Pro，可选调用 API 生成分类、摘要、用户需求和产品建议初稿。
- 默认使用规则模式，只有用户明确启用时才向 DeepSeek 发送反馈文本。
- 没有 API key 或 API 调用失败时，自动 fallback 到规则版分类。
- 使用规则判断优先级。
- 识别人工复核样本。
- 生成问题卡片、QA 报告和运行日志。
- CLI 和 Web App 都支持自然语言 `ask` 入口，并可生成静态 HTML 报告。
- Ask 默认使用 DeepSeek 将任务解析为受约束参数，失败或未配置时 fallback 到原有规则解析。
- QA 报告记录 DeepSeek API 返回的输入、输出和总 token 数。
- CLI/Web 均可强制只使用本地规则解析 Ask。
- 自然语言 `ask` 可将常见第三方评论列名标准化并导出 `normalized_feedback.csv`。
- 支持在本地 Web App 中选择内置数据、上传 CSV、查看结果并下载输出。
- 支持对本地人工标注 golden set 运行规则质量评测和回归门槛。
- 自动生成 `review_decisions.csv`，并通过 CLI/Web 应用人工确认、调整或保持开放的决策。
- 人工复核结果写入独立文件，不覆盖原始分诊证据。
- 暂不实现 RAG、向量数据库和文档检索。

## 输入数据

CSV 至少包含：

- `id`
- `source`
- `app_name`
- `review_text`
- `rating`

## 输出物

- `issue_cards.md`: 面向产品讨论的问题卡片。
- `qa_report.md`: 面向流程 QA 的统计、LLM 使用情况、fallback 和边界说明。
- `run_log.md`: 面向 Agent 可解释性的工具调用、LLM/fallback 和下一步动作记录。
- `triage_results.csv`: 面向后续分析的结构化结果。
- `review_decisions.csv`: 人工复核决策模板。
- `triage_results_reviewed.csv`: 应用人工决策后的独立结果。
- `review_summary.md`: 人工复核状态摘要。

## 人工复核边界

以下样本进入人工复核：

- 文本过短。
- 分类低置信度。
- 同时命中多个问题类型。
- 产品建议为空或过泛。
- P0 样本。
- LLM 与规则分类不一致。

LLM 输出不能绕过人工复核边界。即使分类、摘要、用户需求和产品建议来自 DeepSeek，也必须经过本地 QA 和 badcase 识别。

## 建议评估指标

- 字段校验覆盖率。
- 分类命中率和人工标注一致率。
- P0 召回率。
- 人工复核队列准确率。
- 从反馈输入到问题卡片产出的处理时间。
- 产品建议被采纳或进入需求池的比例。

当前 `data/evaluation_feedback.csv` 是 24 条小规模回归集，只用于发现规则退化，不代表生产准确率。
