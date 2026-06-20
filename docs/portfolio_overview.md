# Feedback Triage Agent in 30 Seconds

## Business Problem

AI product teams receive messy feedback from app stores, support tickets, communities, and interviews. The hard part is not only summarizing what users said; it is turning that feedback into prioritized, reviewable product issues.

## Input Data

The Agent reads a CSV with five standard fields:

- `id`
- `source`
- `app_name`
- `review_text`
- `rating`

Ask mode can also normalize common external review exports into this format before the same workflow runs.

## Agent Workflow

The workflow is a fixed seven-step plan:

1. Load feedback.
2. Validate required fields.
3. Classify each item with local rules, or optional DeepSeek drafts when explicitly enabled.
4. Detect high-risk or uncertain samples.
5. Generate issue cards.
6. Run QA checks and summarize distributions.
7. Export product and audit artifacts.

The natural-language Ask entry only converts a request into constrained run parameters. It does not change the fixed workflow.

## Human Review Loop

The Agent does not auto-close risky cases. P0 issues, low-confidence classifications, multi-issue feedback, short or ambiguous text, and LLM/rule disagreements enter a human review queue.

Reviewers can edit `review_decisions.csv` to confirm, adjust, or keep items open. Reviewed results are written to separate files, so the original triage evidence remains traceable.

## Output Artifacts

- `triage_results.csv`: structured classifications, priorities, confidence, evidence keywords, review flags, and LLM fallback metadata.
- `issue_cards.md`: one readable issue card per feedback item.
- `weekly_summary.md`: product-facing summary of priority issues, user evidence, suggested follow-up, and review status.
- `qa_report.md`: run-level QA, fallback, token usage, distributions, and decision boundaries.
- `run_log.md`: seven tool steps with inputs, outputs, warnings, and next actions.
- `review_decisions.csv`: human review template.
- `report.html`: optional static report for portfolio review.

## What This Demonstrates

This project shows AI product and product operations judgment:

- turning unstructured user feedback into structured product work;
- designing an AI-assisted workflow with clear review boundaries;
- using LLMs as optional drafts rather than unchecked decision makers;
- preserving evidence, fallback behavior, and audit logs;
- shipping a small local demo that is easy to run, inspect, and explain.
