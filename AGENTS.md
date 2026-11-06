# AGENTS.md

## 项目身份与范围

v1.0 Release Feedback Risk Workbench 是发版后反馈风险工作台。Feedback Triage Agent 提供分类、规则 fallback、QA、人工复核与审计引擎，Version Feedback Risk Radar 提供版本窗口比较、问题簇和负责人跟进界面。当前事实以 README 和 PROJECT_BRIEF 为准。

核心流程为创建观察任务 → 导入基线/当前窗口 → 聚合问题簇 → 比较数量与占比 → 人工决定 → 后续窗口验证。反馈级优先级、问题簇风险、变化状态、复核状态和处理状态不可混用。时间相关性不能写成因果关系。

## 运行与验收

```bash
python -m pip install -e ".[dev]"
python scripts/prepare_ai_app_reviews.py
python scripts/label_quality_check.py
python scripts/summarize_reviews.py
python -m feedback_triage_agent.cli run --input data/ai_app_reviews.csv --output data/ai_app_feedback/generated/triage --no-llm
python scripts/compare_ai_app_labels.py
python -m pytest
python -m feedback_triage_agent.cli harness --output data/harness_output --skip-pytest
python -m feedback_triage_agent.web_app
```

上述准备、QA、测试和规则评测不调用外部模型。harness 的 `--skip-pytest` 仅在 pytest 已单独执行时使用。只报告实际执行结果，不把历史通过数或跳过测试写成新的验证。

## 公开数据与人工 QA

- 来源与字段映射见 `docs/ai_app_feedback/README.md`；文件哈希和固定来源提交见 `data/ai_app_feedback/provenance.json`。
- `data/ai_app_feedback/{raw_reviews,clean_reviews,excluded_reviews}.csv` 保存完整公开来源；五字段 `data/ai_app_reviews.csv` 只是投影，不能替代 14 字段标注。
- `docs/ai_app_feedback/source/` 和 `scripts/ai_app_feedback_source/` 是来源快照。原脚本不直接运行；使用顶层已适配脚本。快照内相对路径属于原项目。
- 人工 QA 在 `docs/ai_app_feedback/source/qa_report.md`，自动 QA 在 `data/ai_app_feedback/generated/qa_report.md`。保留 9 个复核 ID 的理由和既有裁决，不能把保留标签改写成“无问题”。
- 修改准备逻辑须验证原有 30 个 ID、原文、来源、App 和评分一致，禁止静默换样本、伪造 ID 或填补未知版本。
- 来源标签与系统结果并列保留，差异不当成新 golden set 的准确率。公开样本缺少完整版本窗口，不用于发版前后或因果验证。
- 不删除、归档或修改旧分析仓库来代替整合验收。

## 可选模型与兼容范围

- 工作台的聚合、窗口比较、审计和人工状态使用本地规则，不依赖付费模型。
- 旧 Ask 解析和单条初稿可选 DeepSeek；无 key、Web 模型未开启或调用失败时回退到本地规则。`run --no-llm` 和 Ask `--rule-parser` 明确禁用真实请求。
- 测试使用模拟客户端；不以真实 API、在线 Demo 或 API key 作为测试前提。不写入或输出密钥。
- 旧 CLI demo/run/ask/inspect/report 和七步接口保持兼容，五个列名及必填值均须存在。缺评分的数据应使用新版观察任务导入，不伪造评分。
- 七步接口为 load_feedback → validate_schema → classify_feedback → detect_badcases → generate_issue_cards → qa_check → export_report。
- 保留 triage_results.csv、issue_cards.md、qa_report.md、run_log.md、weekly_summary.md 和人工复核文件；日志需记录模型、fallback 和复核原因。

## 修改与边界

- 分类和优先级规则优先改 `feedback_triage_agent/rules.py`；LLM 请求与解析优先改 `llm_client.py` / `prompts.py`。
- 新增工具步骤须返回 ToolResult 并登记固定计划；修改输出字段须同步 exporters、文档和必要回归。
- 高风险、P0、低置信度、多意图或判断冲突不能自动闭环；人工决定追加留痕，不覆盖证据和初始判断。
- 本地使用 JSON / 文件持久化；Vercel 的 /tmp 为临时存储。不扩展数据库、登录、权限、多租户、爬虫、复杂 RAG、向量数据库或外部平台写入。
- 保留用户已有修改，使用独立分支隔离工作，不 reset --hard 或清理用户文件。
