# Agent Run Log

## 1. load_feedback

- 状态: success
- 输入摘要: path=data/ai_app_reviews.csv
- 输出摘要: loaded 30 rows, 5 columns
- warnings: 无
- 下一步动作: validate_schema

## 2. validate_schema

- 状态: success
- 输入摘要: required_fields=id, source, app_name, review_text, rating
- 输出摘要: valid_records=30, missing_columns=0
- warnings: 无
- 下一步动作: classify_feedback

## 3. classify_feedback

- 状态: warning
- 输入摘要: records=30, llm_requested=True
- 输出摘要: classified=30, llm_used=False, llm_attempted=0, llm_success=0, llm_failed=0, fallback=True, categories={'用户预期与产品定位问题': 6, '交互体验问题': 2, '不明确/其他': 13, '性能与稳定性问题': 3, '账号、隐私与数据问题': 1, '内容安全与合规问题': 1, '模型能力问题': 4}
- warnings: LLM 不可用或调用失败，已 fallback 到 rules.py
- 下一步动作: detect_badcases

## 4. detect_badcases

- 状态: warning
- 输入摘要: classified=30
- 输出摘要: human_review_queue=21, reasons={'同时命中多个问题类型': 6, 'P0 样本': 2, '分类低置信度': 17, '文本过短': 1}
- warnings: 存在需要人工复核的样本
- 下一步动作: generate_issue_cards

## 5. generate_issue_cards

- 状态: success
- 输入摘要: classified=30
- 输出摘要: issue_cards=30
- warnings: 无
- 下一步动作: qa_check

## 6. qa_check

- 状态: warning
- 输入摘要: cards=30, classified=30
- 输出摘要: total=30, review=21
- warnings: 存在人工复核队列
- 下一步动作: export_report

## 7. export_report

- 状态: success
- 输入摘要: output_dir=data/output_ask
- 输出摘要: exported issue_cards.md, qa_report.md, run_log.md, triage_results.csv
- warnings: 无
- 下一步动作: done
