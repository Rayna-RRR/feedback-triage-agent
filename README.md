# Feedback Triage Agent v0.6

## 本地 Web App

想实际操作分诊流程，可以启动本地 Web App：

```bash
python -m feedback_triage_agent.web_app
```

然后打开：

```text
http://127.0.0.1:8000
```

Web App 当前是本地原型：不接数据库、不做登录、不接生产系统。它支持自然语言 Ask、选择内置样例、上传 CSV、运行 Agent、查看结果页并下载输出文件。

## 展示入口

如果只是想了解项目，不需要先运行 CLI 或启动服务。可以直接在浏览器打开：

- `docs/index.html`: 项目展示首页，说明输入、Agent 步骤、人工复核原因、输出和复现命令。
- `docs/demo-report.html`: 基于 `data/output_ask` 真实导出结果生成的样例 HTML 报告。

作品集截图位于 `docs/assets/screenshots/`：

- `feedback_agent_01_home.png`: 项目首页与能力总览。
- `feedback_agent_02_ask.png`: 自然语言 Ask 上传入口。
- `feedback_agent_03_run_config.png`: 结构化运行配置。
- `feedback_agent_04_summary.png`: 运行总览与分布。
- `feedback_agent_05_review_queue.png`: 人工复核队列。
- `feedback_agent_06_issue_cards.png`: 问题卡片摘要。
- `feedback_agent_07_downloads.png`: 下载文件区。

Feedback Triage Agent 是一个轻量本地 Agent Demo，用于模拟 AI 产品或产品助理工作中的用户反馈分诊流程。它从 CSV 读取一批反馈，通过固定工具计划完成字段检查、问题分类、优先级判断、badcase 识别、问题卡片生成、QA 检查和报告导出。

v0.6 支持本地 FastAPI Web App、可选 DeepSeek API、自然语言 `ask`、静态 HTML 报告、规则质量评测和本地人工复核回写。规则模式是默认值；只有 CLI/Web 明确启用 LLM，或 Ask 任务明确写出“使用 LLM / 使用 DeepSeek”时，反馈文本才会发送给 DeepSeek。

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

不设置 `DEEPSEEK_API_KEY` 时，命令会使用规则版分诊。若明确启用 LLM 但 API key 缺失、配置无效或调用失败，本轮会在 `run_log.md` 和 `qa_report.md` 中记录 fallback 原因，并继续使用 `rules.py`。

## 运行命令

启动本地 Web App：

```bash
python -m feedback_triage_agent.web_app
```

运行内置 demo：

```bash
python -m feedback_triage_agent.cli demo
```

读取指定 CSV 并导出报告：

```bash
python -m feedback_triage_agent.cli run --input data/sample_feedback.csv --output data/output
```

明确启用 LLM：

```bash
python -m feedback_triage_agent.cli run --input data/sample_feedback.csv --output data/output --llm
```

显式关闭 LLM，仅使用规则：

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

`ask` 会从任务文本中识别 CSV 输入路径，支持带空格、中文和 Windows 盘符的路径；未指定输出目录时默认写入 `data/output_ask`。LLM 默认关闭，只有任务明确包含“使用 LLM”或“使用 DeepSeek”才会启用；如果包含“生成 HTML 报告”或“网页报告”，会在分诊完成后额外生成 `report.html`。

Web 首页也提供相同的自然语言 Ask 入口。可以先上传 CSV，再输入“只用规则，生成 HTML 报告”等要求；未上传时也可以在任务中直接写本地 CSV 路径。上传限制为 5 MB / 5000 行，启用 LLM 时单次最多处理 100 条。Web 版本复用上述意图解析和固定 Agent 计划，但为避免覆盖 CLI 输出，每次运行统一写入独立的 `data/web_runs/run_YYYYMMDD_HHMMSS_ask/`。

从已有输出目录生成静态 HTML 报告：

```bash
python -m feedback_triage_agent.cli report --output data/output_ask
```

运行测试：

```bash
python -m pytest
```

运行本地规则评测：

```bash
python -m feedback_triage_agent.cli evaluate \
  --input data/evaluation_feedback.csv \
  --output data/evaluation_output
```

评测输入包含人工维护的 `expected_issue_category`、`expected_priority` 和 `expected_human_review`。命令输出逐样本结果与 Markdown 报告，并对分类、优先级、人工复核判断、P0 precision 和 P0 recall 执行最低 90% 的回归门槛。当前 24 条 golden set 全部通过；这只是小规模回归集，不代表生产数据准确率。

应用人工复核决策：

```bash
python -m feedback_triage_agent.cli review-apply --output data/output
```

每次 Agent 运行都会生成 `review_decisions.csv`。人工可将 `decision` 填为：

- `confirm`: 确认原分类和优先级并关闭复核。
- `adjust`: 填写 `final_issue_category` 和 `final_priority` 后关闭复核。
- `keep_open`: 保持人工复核状态。
- `pending`: 尚未处理。

命令生成 `triage_results_reviewed.csv` 和 `review_summary.md`，不会覆盖原始 `triage_results.csv`。Web 结果页也支持下载、编辑并重新上传该 CSV。

## 输出文件说明

- `<output-dir>/issue_cards.md`: 每条反馈对应的问题卡片，包含标题、样本 ID、摘要、类型、优先级、用户需求、产品建议和人工复核原因。
- `<output-dir>/qa_report.md`: 总样本数、LLM 使用情况、fallback 原因、字段缺失、分类分布、优先级分布、人工复核列表和本轮判断边界。
- `<output-dir>/run_log.md`: 记录 Agent 每一步工具调用的输入摘要、输出摘要、warnings、fallback 情况和下一步动作。
- `<output-dir>/triage_results.csv`: 结构化分诊结果，分别记录最终分类、规则分类、规则置信度、规则关键词、LLM/规则分歧、`classification_source` 和 `llm_error`。
- `<output-dir>/review_decisions.csv`: 待人工填写的复核决策模板，使用唯一 `record_key` 区分重复 ID。
- `<output-dir>/triage_results_reviewed.csv`: 应用人工决策后的独立结果文件。
- `<output-dir>/review_summary.md`: 人工复核关闭、开放和待处理数量。
- `<output-dir>/report.html`: 可通过 `report` 命令额外生成的本地静态 HTML 报告，汇总运行总览、分布、人工复核样本、用户需求、问题卡片摘要、run log 和判断边界。

## v0.6 范围

- 使用 pandas 读取 CSV。
- 使用 pydantic 定义输入、输出、工具结果和 Agent 状态模型。
- 使用 FastAPI + Jinja2 提供本地 Web App 原型。
- Web App 支持自然语言 Ask、内置样例、AI 应用评论数据和用户上传 CSV。
- Web App 每次运行写入 `data/web_runs/run_YYYYMMDD_HHMMSS/`，不覆盖已有 CLI 输出。
- 使用关键词、否定语义和启发式规则完成优先级判断、fallback 和人工复核识别。
- 可选调用 DeepSeek API 生成分类、摘要、用户需求和产品建议初稿。
- LLM 与规则分类不一致时保留两套证据并强制进入人工复核。
- 所有 LLM 输出都必须经过 QA 检查和人工复核队列判断。
- 使用 Typer + Rich 提供本地 CLI 体验。
- 使用 `ask` 命令提供最小自然语言任务入口，但不改变固定 Agent 计划。
- 使用 `report` 命令生成不依赖 CDN 和远程资源的静态 HTML 报告。
- 使用 `evaluate` 命令对人工标注 golden set 生成逐样本误差和质量指标。
- 评测覆盖分类准确率、优先级准确率、人工复核判断准确率、P0 precision 和 P0 recall。
- 自动导出 `review_decisions.csv`，支持确认、调整和保持开放三种人工动作。
- CLI/Web 可应用复核决策，生成 reviewed 结果和复核摘要，保留原始分诊证据。
- 使用 pytest 覆盖规则、工具和完整 Agent 流程。

暂不做 Streamlit 的原因是当前阶段优先保证本地可运行、可复现、可离线展示。静态 HTML 报告已经能满足作品集展示、截图和离线查看，不引入额外服务进程和前端框架。

## 后续可扩展方向

- 增加多人复核冲突处理和决策版本历史，但仍保持本地轻量边界。
- 支持多文件输入、去重、聚类和趋势分析。
- 扩充真实业务标签体系和盲测数据，避免只针对当前 golden set 调整规则。
- 将 P0 样本推送到工单系统或告警渠道。
- 后续再考虑 RAG、向量数据库和文档检索，用于引入产品文档、FAQ 或历史工单上下文。

## 作品集价值

这个项目面向 AI 产品、产品助理和 AI 应用运营岗位，重点展示：

- 能把模糊反馈转成结构化产品问题。
- 理解 Agent 不只是脚本，而是目标、工具、状态、日志和复核边界的组合。
- 能区分 AI 自动化适合做什么，以及哪些高风险判断必须交给人。
- 能用最小工程闭环表达产品思考，而不是只写概念方案。
