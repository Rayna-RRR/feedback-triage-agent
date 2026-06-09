# AGENTS.md

## 项目目的

Feedback Triage Agent 是一个本地 CLI Agent Demo，用于模拟 AI 产品团队处理用户反馈的分诊流程。项目重点不是模型能力，而是展示工具调用、状态记录、LLM 初稿、规则 fallback、人工复核队列和报告导出的完整链路。

## 运行命令

```bash
python -m feedback_triage_agent.cli demo
python -m feedback_triage_agent.cli run --input data/sample_feedback.csv --output data/output
python -m feedback_triage_agent.cli run --input data/sample_feedback.csv --output data/output --no-llm
python -m feedback_triage_agent.cli inspect --output data/output
```

## 测试命令

```bash
pytest
```

## 不要做的事情

- 不接真实外部 API。
- 不接数据库。
- 不做 Web UI。
- 不做爬虫。
- 不做复杂 RAG。
- 不接向量数据库。
- 不做文档检索。
- 不把 `DEEPSEEK_API_KEY` 写入代码、文档示例真实值或测试数据。
- 不把 P0、低置信度、多问题命中样本视为可自动闭环。

## 完成标准

- CLI 可以跑通 sample feedback 的完整流程。
- 输出 `issue_cards.md`、`qa_report.md`、`run_log.md` 和 `triage_results.csv`。
- `run_log.md` 包含 7 个固定工具步骤。
- `run_log.md` 和 `qa_report.md` 记录 LLM 是否使用、fallback 情况和人工复核原因。
- pytest 全部通过。
- README 清楚说明 v0.2 支持 DeepSeek API，RAG 暂不实现，并保留人工复核边界。

## 修改规则

- 新增分类或优先级规则时，优先修改 `feedback_triage_agent/rules.py`。
- 修改 LLM 请求或解析时，优先修改 `feedback_triage_agent/llm_client.py` 和 `feedback_triage_agent/prompts.py`。
- 新增工具步骤时，必须返回 `ToolResult`，并在 Agent runner 的固定计划中登记。
- 修改输出字段时，同步更新 exporters、README 和测试。
- 高风险样本识别规则必须能在 `qa_report.md` 和 `triage_results.csv` 中被追踪。
