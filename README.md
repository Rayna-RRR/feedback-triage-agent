# Feedback Triage Agent v0.9.0

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

Web 运行输出默认写入本地 `data/web_runs/`。部署到 Vercel 时会自动改用 `/tmp/feedback-triage-runs`，也可以用 `FEEDBACK_TRIAGE_WEB_RUNS_DIR` 指定可写目录。公开 Demo 的上传 CSV 和输出文件只适合临时保存，默认约 24 小时后清理，平台重启或实例回收后也可能丢失。

## Vercel 公开 Demo 部署

当前仓库包含 Vercel 入口：

- `app.py`: 导出 FastAPI `app`，供 Vercel FastAPI 预设识别。
- `.vercelignore`: 排除 `.venv`、缓存、本地输出和历史 Web run。

生产部署命令：

```bash
vercel --prod
```

Vercel 环境变量建议：

```bash
FEEDBACK_TRIAGE_RUN_RETENTION_HOURS=24
FEEDBACK_TRIAGE_MAX_WEB_RUNS=50
```

如果要在线上开放 DeepSeek，必须同时设置：

```bash
DEEPSEEK_API_KEY=your_deepseek_api_key
FEEDBACK_TRIAGE_WEB_LLM_ENABLED=true
```

可以在 Vercel Dashboard 的 Project Settings -> Environment Variables 中添加，也可以用 CLI 分别添加到 Production：

```bash
vercel env add DEEPSEEK_API_KEY production
vercel env add FEEDBACK_TRIAGE_WEB_LLM_ENABLED production
```

`FEEDBACK_TRIAGE_WEB_LLM_ENABLED` 的值填写 `true`。环境变量变更后需要重新生产部署一次，新的 Serverless Function 才会读取到配置。本地变量模板见 `.env.example`，不要把真实 key 写入这个文件。

不设置 `FEEDBACK_TRIAGE_WEB_LLM_ENABLED=true` 时，Web 端不会调用 DeepSeek：Ask 使用本地规则解析，反馈分诊也只用 `rules.py`。CLI 的 `--llm` 行为不受这个 Web 开关影响。

公开 Demo 请不要上传真实用户隐私、商业保密或生产反馈原文。Vercel 可以先用于快速上线和分享链接；如果后续需要更稳定的中国大陆访问，应迁移到大陆云服务器并按要求完成 ICP 备案。

## 展示入口

如果只是想了解项目，不需要先运行 CLI 或启动服务。可以直接在浏览器打开：

- `docs/index.html`: 项目展示首页，说明输入、Agent 步骤、人工复核原因、输出和复现命令。
- `docs/portfolio_overview.md`: 给非工程评审看的 30 秒项目说明。
- `docs/demo-report.html`: 基于一次 `data/output_ask` 导出快照生成的样例 HTML 报告。

作品集截图位于 `docs/assets/screenshots/`：

- `feedback_agent_01_home.png`: 项目首页与能力总览。
- `feedback_agent_02_ask.png`: 自然语言 Ask 上传入口。
- `feedback_agent_03_run_config.png`: 结构化运行配置。
- `feedback_agent_04_summary.png`: 运行总览与分布。
- `feedback_agent_05_review_queue.png`: 人工复核队列。
- `feedback_agent_06_issue_cards.png`: 问题卡片摘要。
- `feedback_agent_07_downloads.png`: 下载文件区。

Feedback Triage Agent 是一个轻量本地 Agent Demo，用于模拟 AI 产品或产品助理工作中的用户反馈分诊流程。它从 CSV 读取一批反馈，通过固定工具计划完成字段检查、问题分类、优先级判断、badcase 识别、问题卡片生成、QA 检查和报告导出。

v0.9.0 支持本地 FastAPI Web App、DeepSeek V4 Pro Ask 任务解析、规则解析 fallback、可选 DeepSeek 反馈初稿、外部 CSV 格式标准化、中英文规则分类、API token 用量记录、静态 HTML 报告、产品周报摘要、规则质量评测、本地人工复核回写、Output Contract Test、adversarial evaluation set、scenario metrics、Evaluation Harness Lite 和 GitHub Actions CI。

本项目不接数据库、不做 Streamlit、不做复杂 Web UI、不做爬虫、不做复杂 RAG。RAG、向量数据库和文档检索暂不实现。

## 解决的问题

AI 产品团队经常面对来自应用商店、社区、客服工单、访谈记录的非结构化反馈。普通汇总容易停留在“用户说了什么”，而产品工作更需要把反馈转成可复核的问题类型、优先级、用户需求和产品建议。

这个项目展示一条最小闭环：

用户反馈 CSV -> Agent 固定计划 -> 工具调用 -> 状态记录 -> 人工复核队列 -> 问题卡片 -> QA 报告

当前项目不是开放式聊天机器人，而是一个反馈分诊工作流 Agent：DeepSeek 或本地规则把自然语言任务解析成受约束参数，实际分诊仍由固定工具计划执行，确保结果可复现、可审计。

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

不要把 API key 写入代码或提交到 Git。需要使用 DeepSeek Ask 解析或反馈初稿时，在本地 shell 设置环境变量：

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
```

可选环境变量：

```bash
export DEEPSEEK_MODEL="deepseek-v4-pro"
export DEEPSEEK_API_BASE="https://api.deepseek.com"
export DEEPSEEK_TIMEOUT_SECONDS="20"
```

DeepSeek 在项目中有两个独立用途：

1. **Ask 任务解析**：配置 API key 后默认启用，只发送任务文本和上传文件名，不发送 CSV 内容。模型返回受 Pydantic 校验的输入路径、输出目录、格式转换、HTML 报告和反馈分诊方式参数。不可用或响应无效时回退到原有关键词与正则解析。
2. **反馈初稿**：只有用户明确要求“使用 LLM / 使用 DeepSeek”时，才会发送反馈文本并生成分类、摘要、用户需求和产品建议初稿。“只用规则”会关闭这一层。

默认模型为 `deepseek-v4-pro`。结构化 JSON 任务使用非思考模式，减少额外推理文本对解析的干扰。两个用途的来源、模型、API 返回的输入/输出/总 token 数和 fallback 都会记录在 `qa_report.md`；模型与 fallback 也会进入 `run_log.md`。不设置 `DEEPSEEK_API_KEY` 时，Ask 使用本地规则解析，反馈分诊也使用 `rules.py`。

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

配置 `DEEPSEEK_API_KEY` 后，Ask 默认先由 DeepSeek 理解自然语言。需要完全使用原有本地拆解方式时：

```bash
python -m feedback_triage_agent.cli ask \
  "分析 data/ai_app_reviews.csv，只用规则，生成 HTML 报告" \
  --rule-parser
```

当外部 CSV 列名不符合 Agent 的五个标准字段时，可以明确要求格式转换：

```bash
python -m feedback_triage_agent.cli ask \
  "分析 /path/to/chatgpt_reviews_latest_5000.csv，转换为符合格式，输出到 data/output_ask，只用规则"
```

`ask` 会把任务解析为结构化执行参数。DeepSeek 解析成功时使用模型结果，同时保留明确否定词和已知路径规则作为约束；失败时使用原有关键词与正则结果。未指定输出目录时默认写入 `data/output_ask`。要求转换格式时会先生成 `normalized_feedback.csv`，再执行原有七步分诊；要求 HTML 报告时额外生成 `report.html`。

标准化使用本地确定性规则，不调用 LLM：

- `reviewId`、`review_id`、`feedback_id` 等映射到 `id`。
- `content`、`review`、`text`、`comment`、`feedback` 等映射到 `review_text`。
- `score`、`stars`、`rate` 等映射到 `rating`。
- `platform`、`channel`、`store` 等映射到 `source`。
- `app`、`product_name` 等映射到 `app_name`。
- Google Play 常见导出结构会补 `source=google_play`；缺少 `app_name` 时从原文件名推断。
- 缺少 ID 时生成稳定的行 ID；无法识别评论正文或评分字段时拒绝转换，不会猜测语义值。
- 未参与映射的原始元数据列会保留在 `normalized_feedback.csv` 中。

Web 首页提供相同入口，并可勾选“仅用本地规则解析 Ask”。普通“配置运行”上传仍要求五个标准字段，不会静默转换。上传限制为 5 MB / 5000 行；启用反馈初稿 LLM 时单次最多处理 100 条。每次 Web 运行写入独立的 `run_YYYYMMDD_HHMMSS_ask/` 目录；本地默认在 `data/web_runs/`，Vercel 默认在 `/tmp/feedback-triage-runs/`。

从已有输出目录生成静态 HTML 报告：

```bash
python -m feedback_triage_agent.cli report --output data/output_ask
```

运行测试：

```bash
python -m pytest
```

Output Contract Test 会验证 Agent 完整运行后的输出结构，包括必需导出文件、`triage_results.csv` 列顺序与合法值、`review_decisions.csv` 的 `record_key` 关联，以及 Markdown 输出非空。这个测试用于避免后续规则或 LLM 改动破坏下游交付物结构。

运行本地规则评测：

```bash
python -m feedback_triage_agent.cli evaluate \
  --input data/evaluation_feedback.csv \
  --output data/evaluation_output
```

评测输入包含人工维护的 `expected_issue_category`、`expected_priority` 和 `expected_human_review`。命令输出逐样本结果与 Markdown 报告，并对分类准确率执行最低 80%、对优先级、人工复核判断、P0 precision 和 P0 recall 执行最低 90% 的默认回归门槛。当前 24 条 golden set 全部通过；这只是小规模回归集，不代表生产数据准确率。

探索性对抗评测集位于 `data/adversarial_feedback.csv`，用于暴露 `rules.py` 在否定语义、多意图反馈、正向评价夹杂问题、关键词误伤和高风险混合场景下的边界和失败模式。它不作为默认回归门槛；运行时可以把 min gate 设为 0，只用于观察错误分布。

如果评测 CSV 包含可选的 `scenario` 字段，`evaluation_results.csv` 会保留该字段，`evaluation_report.md` 会输出 `Scenario Breakdown`，按 scenario 展示分类、优先级、人工复核和 P0 指标。Scenario metrics 用于观察不同失败类型下的表现，例如否定语义、多意图反馈和高风险混合场景；scenario breakdown 只用于分析，不作为默认质量门槛。

```bash
python -m feedback_triage_agent.cli evaluate \
  --input data/adversarial_feedback.csv \
  --output data/adversarial_output \
  --min-category-accuracy 0 \
  --min-priority-accuracy 0 \
  --min-human-review-accuracy 0 \
  --min-p0-precision 0 \
  --min-p0-recall 0
```

Evaluation Harness Lite 可以用一个命令串起 pytest、golden set evaluation 和 adversarial evaluation，并生成统一的 `harness_report.md` 与 `harness_summary.json`。其中 golden set 用作回归 gate，adversarial set 用作探索性失败模式分析，scenario breakdown 用于观察不同场景表现。

```bash
./.venv/bin/python -m feedback_triage_agent.cli harness --output data/harness_output
```

GitHub Actions CI 会在 push 和 pull request 时自动运行：

```bash
python -m pytest
python -m feedback_triage_agent.cli harness --output data/harness_output_ci --skip-pytest
```

CI 中 golden set 仍作为回归 gate；adversarial set 继续用于探索性失败模式分析，不作为失败 gate。Harness 输出会尽量作为 `harness-output` artifact 上传，便于查看 scenario breakdown 和评测报告。

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

- `<output-dir>/normalized_feedback.csv`: 仅在 Ask 明确要求格式标准化时生成；标准字段排在前五列，未消费的原始元数据继续保留。
- `<output-dir>/issue_cards.md`: 每条反馈对应的问题卡片，包含标题、样本 ID、摘要、类型、优先级、用户需求、产品建议和人工复核原因。
- `<output-dir>/qa_report.md`: 总样本数、LLM 使用情况、fallback 原因、字段缺失、分类分布、优先级分布、人工复核列表和本轮判断边界。
- `<output-dir>/run_log.md`: 记录 Agent 每一步工具调用的输入摘要、输出摘要、warnings、fallback 情况和下一步动作。
- `<output-dir>/triage_results.csv`: 结构化分诊结果，分别记录最终分类、规则分类、规则置信度、规则关键词、LLM/规则分歧、`classification_source` 和 `llm_error`。
- `<output-dir>/weekly_summary.md`: 从 `triage_results.csv` 生成的轻量产品周报，汇总优先级问题、用户证据、建议跟进动作和复核状态。
- `<output-dir>/review_decisions.csv`: 待人工填写的复核决策模板，使用唯一 `record_key` 区分重复 ID。
- `<output-dir>/triage_results_reviewed.csv`: 应用人工决策后的独立结果文件。
- `<output-dir>/review_summary.md`: 人工复核关闭、开放和待处理数量。
- `<output-dir>/report.html`: 可通过 `report` 命令额外生成的本地静态 HTML 报告，汇总运行总览、分布、人工复核样本、用户需求、问题卡片摘要、run log 和判断边界。

## v0.9.0 范围

- 使用 pandas 读取 CSV。
- 使用 pydantic 定义输入、输出、工具结果和 Agent 状态模型。
- 使用 FastAPI + Jinja2 提供本地 Web App 原型。
- Web App 支持自然语言 Ask、内置样例、AI 应用评论数据和用户上传 CSV。
- Web 上传入口使用自定义文件选择控件，避免系统默认文案显示为繁体。
- Ask 默认使用 DeepSeek 解析受约束任务参数，失败时自动 fallback 到本地关键词和正则解析。
- DeepSeek 默认使用 `deepseek-v4-pro`，并记录 API 返回的 token 用量。
- 本地规则同时覆盖常见中英文反馈关键词和否定语义；明确正向且没有问题信号的高评分样本归为“正向反馈/无明确问题”，未命中或低置信度样本仍进入人工复核。
- CLI `--rule-parser` 和 Web 复选框可强制使用原有本地 Ask 解析。
- Ask 可把常见第三方评论导出列映射到标准字段并输出 `normalized_feedback.csv`。
- 格式转换、字段补值和输出路径会记录在 `run_log.md` 与 `qa_report.md`，保持可追踪。
- Web App 每次运行写入 `data/web_runs/run_YYYYMMDD_HHMMSS/`，不覆盖已有 CLI 输出。
- 使用关键词、否定语义和启发式规则完成优先级判断、fallback 和人工复核识别。
- 可选调用 DeepSeek API 生成分类、摘要、用户需求和产品建议初稿。
- 规则已有明确高置信结论但 LLM 给出不同分类时保留两套证据并进入人工复核；规则不明确时允许 LLM 补强分类。
- 所有 LLM 输出都必须经过 QA 检查和人工复核队列判断。
- 使用 Typer + Rich 提供本地 CLI 体验。
- 使用 `ask` 命令提供模型增强的自然语言任务入口，但不改变固定 Agent 计划。
- 使用 `report` 命令生成不依赖 CDN 和远程资源的静态 HTML 报告。
- 自动导出 `weekly_summary.md`，把分诊结果转成面向产品周会和作品集讲解的轻量摘要。
- 使用 `evaluate` 命令对人工标注 golden set 生成逐样本误差和质量指标。
- 评测覆盖分类准确率、优先级准确率、人工复核判断准确率、P0 precision 和 P0 recall。
- 自动导出 `review_decisions.csv`，支持确认、调整和保持开放三种人工动作。
- CLI/Web 可应用复核决策，生成 reviewed 结果和复核摘要，保留原始分诊证据。
- 使用 pytest 覆盖规则、工具和完整 Agent 流程。
- 增加 Output Contract Test，验证 Agent 导出的 CSV、Markdown 和人工复核文件结构稳定，避免后续规则或 LLM 改动破坏下游交付物。
- 增加 adversarial evaluation set，覆盖否定语义、多意图反馈、正向评价夹杂问题、关键词误伤和高风险混合场景。
- 增加 scenario metrics，在评测报告中按可选 `scenario` 字段拆分指标，用于分析不同失败类型下的规则表现。
- 增加 Evaluation Harness Lite，用统一命令生成 pytest、golden set 和 adversarial set 的汇总报告。
- 增加 GitHub Actions CI，在 push / PR 时自动运行 pytest 与 Evaluation Harness Lite。
- 保留 external review assisted maintainability findings 作为历史审查材料，当前版本聚焦作品集说明和输出物可读性。

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
