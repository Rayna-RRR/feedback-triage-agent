# Agent Run Log

## 1. load_feedback

- 状态: success
- 输入摘要: path=data/sample_feedback.csv
- 输出摘要: loaded 12 rows, 5 columns
- warnings: 无
- 下一步动作: validate_schema

## 2. validate_schema

- 状态: success
- 输入摘要: required_fields=id, source, app_name, review_text, rating
- 输出摘要: valid_records=12, missing_columns=0
- warnings: 无
- 下一步动作: classify_feedback

## 3. classify_feedback

- 状态: warning
- 输入摘要: records=12, llm_requested=True
- 输出摘要: classified=12, llm_used=False, llm_attempted=0, llm_success=0, llm_failed=0, fallback=True, categories={'模型能力问题': 1, '交互体验问题': 3, '性能与稳定性问题': 1, '会员与商业化问题': 2, '内容安全与合规问题': 1, '账号、隐私与数据问题': 1, '用户预期与产品定位问题': 2, '不明确/其他': 1}
- warnings: LLM 不可用或调用失败，已 fallback 到 rules.py
- 下一步动作: detect_badcases

## 4. detect_badcases

- 状态: warning
- 输入摘要: classified=12
- 输出摘要: human_review_queue=7, reasons={'P0 样本': 3, '同时命中多个问题类型': 3, '文本过短': 1, '分类低置信度': 1}
- warnings: 存在需要人工复核的样本
- 下一步动作: generate_issue_cards

## 5. generate_issue_cards

- 状态: success
- 输入摘要: classified=12
- 输出摘要: issue_cards=12
- warnings: 无
- 下一步动作: qa_check

## 6. qa_check

- 状态: warning
- 输入摘要: cards=12, classified=12
- 输出摘要: total=12, review=7
- warnings: 存在人工复核队列
- 下一步动作: export_report

## 7. export_report

- 状态: success
- 输入摘要: output_dir=data/output
- 输出摘要: exported issue_cards.md, qa_report.md, run_log.md, triage_results.csv
- warnings: 无
- 下一步动作: done
