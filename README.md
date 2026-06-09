# Feedback Triage Agent v0.3

## 展示入口

如果只是想了解项目，不需要先运行 CLI。可以直接在浏览器打开：

- `docs/index.html`: 项目展示首页，说明输入、Agent 步骤、人工复核原因、输出和复现命令。
- `docs/demo-report.html`: 基于 `data/output_ask` 真实导出结果生成的样例 HTML 报告。

Feedback Triage Agent 是一个轻量本地 Agent Demo，用于模拟 AI 产品或产品助理工作中的用户反馈分诊流程。它从 CSV 读取一批反馈，通过固定工具计划完成字段检查、问题分类、优先级判断、badcase 识别、问题卡片生成、QA 检查和报告导出。

v0.3 支持可选 DeepSeek API、自然语言 `ask` 命令和静态 HTML 报告。设置 `DEEPSEEK_API_KEY` 后，LLM 只生成分类、摘要、用户需求和产品建议初稿；优先级、QA 检查、fallback 和人工复核队列仍由本地规则负责。没有 API key 或 API 调用失败时，项目会自动使用规则版流程。

本项目不接数据库、不做 Streamlit、不做复杂 Web UI、不做爬虫、不做复杂 RAG。RAG、向量数据库和文档检索暂不实现。

## 解决的问题

AI 产品团队经常面对来自应用商店、社区、客服工单、访谈记录的非结构化反馈。普通汇总容易停留在“用户说了什么”，而产品工作更需要把反馈转成可复核的问题类型、优先级、用户需求和产品建议。

这个项目展示一条最小闭环：

用户反馈 CSV -> Agent 固定计划 -> 工具调用 -> 状态记录 -> 人工复核队列 -> 问题卡片 -> QA 报告

当前项目不是开放式聊天机器人，而是一个反馈分诊工作流 Agent：自然语言入口只负责解析本地任务意图，实际分诊仍由固定工具计划执行，确保结果可复现、可审计。

## Agent 工作流

load_feedback -> validate_schema -> classify_feedback -> detect_badcases -> generate_issue_cards -> qa_check -> export_report

每一步都是独立 tool，返回结构化 `ToolResult`。Agent runner 按固定计划依次调用工具，并维护 run state、run log 和人工复核队列。`classify_feedback` 会在可用时调用 DeepSeek 生成初稿，否则 fallback 到 `rules.py`。

## 本地安装

项目已在 Python 3.9.6 下验证通过，推荐 Python 3.9+。

```bash
cd feedback-triage-agent
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

如果系统默认 `python` 低于 3.9，请显式使用 Python 3.9+ 创建虚拟环境。

## DeepSeek API 可选配置

不要把 API key 写入代码或提交到 Git。需要使用 LLM 初稿时，在本地 shell 设置环境变量：

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
```

可选环境变量：

```bash
export DEEPSEEK_MODEL="deepseek-chat"
export DEEPSEEK_API_BASE="https://api.deepseek.com"
export DEEPSEEK_TIMEOUT_SECONDS="20"
```

不设置 `DEEPSEEK_API_KEY` 时，命令会自动使用规则版分诊。若 API 调用失败，本轮会在 `run_log.md` 和 `qa_report.md` 中记录 fallback 原因，并继续使用 `rules.py`。

## 运行命令

运行内置 demo：

```bash
python -m feedback_triage_agent.cli demo
```

读取指定 CSV 并导出报告：

```bash
python -m feedback_triage_agent.cli run --input data/sample_feedback.csv --output data/output
```

强制关闭 LLM，仅使用规则：

```bash
python -m feedback_triage_agent.cli run --input data/sample_feedback.csv --output data/output --no-llm
```

查看最近一次结构化分诊结果：

```bash
python -m feedback_triage_agent.cli inspect --output data/output
```

使用自然语言入口运行分诊：

```bash
python -m feedback_triage_agent.cli ask "分析 data/ai_app_reviews.csv，输出问题卡片、人工复核队列和 HTML 报告"
```

`ask` 会从任务文本中识别 CSV 输入路径；未指定输出目录时默认写入 `data/output_ask`。如果任务中包含“不要用 LLM”或“只用规则”，会关闭 LLM；如果包含“生成 HTML 报告”或“网页报告”，会在分诊完成后额外生成 `report.html`。

从已有输出目录生成静态 HTML 报告：

```bash
python -m feedback_triage_agent.cli report --output data/output_ask
```

运行测试：

```bash
python -m pytest
```

## 输出文件说明

- `data/output/issue_cards.md`: 每条反馈对应的问题卡片，包含标题、样本 ID、摘要、类型、优先级、用户需求、产品建议和人工复核原因。
- `data/output/qa_report.md`: 总样本数、LLM 使用情况、fallback 原因、字段缺失、分类分布、优先级分布、人工复核列表和本轮判断边界。
- `data/output/run_log.md`: 记录 Agent 每一步工具调用的输入摘要、输出摘要、warnings、fallback 情况和下一步动作。
- `data/output/triage_results.csv`: 结构化分诊结果，包含 `classification_source` 和 `llm_error`，可用于后续分析或页面展示。
- `data/output/report.html`: 本地静态 HTML 报告，汇总运行总览、分布、人工复核样本、问题卡片摘要、run log 和判断边界。

## v0.3 范围

- 使用 pandas 读取 CSV。
- 使用 pydantic 定义输入、输出、工具结果和 Agent 状态模型。
- 使用关键词和启发式规则完成优先级判断、fallback 和人工复核识别。
- 可选调用 DeepSeek API 生成分类、摘要、用户需求和产品建议初稿。
- 所有 LLM 输出都必须经过 QA 检查和人工复核队列判断。
- 使用 Typer + Rich 提供本地 CLI 体验。
- 使用 `ask` 命令提供最小自然语言任务入口，但不改变固定 Agent 计划。
- 使用 `report` 命令生成不依赖 CDN 和远程资源的静态 HTML 报告。
- 使用 pytest 覆盖规则、工具和完整 Agent 流程。

暂不做 Streamlit 的原因是当前阶段优先保证本地可运行、可复现、可离线展示。静态 HTML 报告已经能满足作品集展示、截图和离线查看，不引入额外服务进程和前端框架。

## 后续可扩展方向

- 增加更完整的复核台或轻量 Web UI 展示问题卡片和复核队列。
- 支持多文件输入、去重、聚类和趋势分析。
- 引入真实业务标签体系和人工标注结果，评估分类准确率。
- 将 P0 样本推送到工单系统或告警渠道。
- 后续再考虑 RAG、向量数据库和文档检索，用于引入产品文档、FAQ 或历史工单上下文。

## 作品集价值

这个项目面向 AI 产品、产品助理和 AI 应用运营岗位，重点展示：

- 能把模糊反馈转成结构化产品问题。
- 理解 Agent 不只是脚本，而是目标、工具、状态、日志和复核边界的组合。
- 能区分 AI 自动化适合做什么，以及哪些高风险判断必须交给人。
- 能用最小工程闭环表达产品思考，而不是只写概念方案。
