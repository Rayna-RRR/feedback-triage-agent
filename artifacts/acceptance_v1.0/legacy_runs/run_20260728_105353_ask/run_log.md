# Agent Run Log

## 1. load_feedback

- 状态: success
- 输入摘要: path=/Users/rayna/Documents/job/projects/AI_Release_Feedback_Risk_Radar/feedback-triage-agent/artifacts/acceptance_v1.0/data/baseline_48h.csv, ask_parser=rules
- 输出摘要: loaded 30 rows, 7 columns
- warnings: 无
- 下一步动作: validate_schema

## 2. validate_schema

- 状态: success
- 输入摘要: required_fields=id, source, app_name, review_text, rating
- 输出摘要: valid_records=30, missing_columns=0
- warnings: 无
- 下一步动作: classify_feedback

## 3. classify_feedback

- 状态: success
- 输入摘要: records=30, llm_requested=False
- 输出摘要: classified=30, llm_used=False, llm_attempted=0, llm_success=0, llm_failed=0, fallback=False, categories={'交互体验问题': 4, '账号、隐私与数据问题': 5, '模型能力问题': 6, '不明确/其他': 9, '正向反馈/无明确问题': 5, '用户预期与产品定位问题': 1}
- warnings: 无
- 下一步动作: detect_badcases

## 4. detect_badcases

- 状态: warning
- 输入摘要: classified=30
- 输出摘要: human_review_queue=11, reasons={'同时命中多个问题类型': 2, '分类低置信度': 9, '文本过短': 1}
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
- 输出摘要: total=30, review=11
- warnings: 存在人工复核队列
- 下一步动作: export_report

## 7. export_report

- 状态: success
- 输入摘要: output_dir=artifacts/acceptance_v1.0/legacy_runs/run_20260728_105353_ask
- 输出摘要: exported issue_cards.md, qa_report.md, run_log.md, triage_results.csv, review_decisions.csv
- warnings: 无
- 下一步动作: done
