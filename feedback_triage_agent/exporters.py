from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from feedback_triage_agent.models import AgentRunState, ClassifiedFeedback, IssueCard, RunStepLog
from feedback_triage_agent.review import write_review_decisions


TRIAGE_RESULT_COLUMNS = [
    "record_key",
    "id",
    "source",
    "app_name",
    "review_text",
    "rating",
    "issue_category",
    "rule_issue_category",
    "priority",
    "confidence",
    "rule_confidence",
    "matched_categories",
    "matched_keywords",
    "summary",
    "user_need",
    "product_suggestion",
    "needs_human_review",
    "human_review_reasons",
    "classification_source",
    "llm_rule_disagreement",
    "llm_error",
]


def render_issue_cards(cards: List[IssueCard]) -> str:
    lines = ["# Issue Cards", ""]
    if not cards:
        lines.extend(["暂无问题卡片。", ""])
        return "\n".join(lines)

    for index, card in enumerate(cards, start=1):
        review_reasons = "；".join(card.human_review_reasons) if card.human_review_reasons else "无"
        lines.extend(
            [
                f"## {index}. {card.title}",
                "",
                f"- 代表样本 ID: {card.representative_id}",
                f"- 用户原话摘要: {card.user_summary}",
                f"- 问题类型: {card.issue_category}",
                f"- 优先级: {card.priority}",
                f"- 用户需求: {card.user_need}",
                f"- 产品建议: {card.product_suggestion}",
                f"- 需要人工复核的原因: {review_reasons}",
                "",
            ]
        )
    return "\n".join(lines)


def render_count_map(title: str, values: Dict[str, int]) -> List[str]:
    lines = [f"## {title}", ""]
    if not values:
        lines.extend(["- 无", ""])
        return lines
    for key, value in values.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return lines


def render_qa_report(state: AgentRunState) -> str:
    summary = state.qa_summary
    lines = [
        "# QA Report",
        "",
        "## 总览",
        "",
        f"- 总样本数: {summary.get('total_samples', 0)}",
        f"- 有效样本数: {summary.get('valid_samples', 0)}",
        f"- 需要人工复核样本数: {summary.get('human_review_count', 0)}",
        "",
        "## LLM 使用情况",
        "",
        f"- 是否使用 LLM: {summary.get('llm_used', False)}",
        f"- LLM 模型: {summary.get('llm_model') or '未使用'}",
        f"- 是否 fallback 到 rules.py: {summary.get('llm_fallback_used', False)}",
    ]
    fallback_reasons = summary.get("llm_fallback_reasons", [])
    if fallback_reasons:
        for reason in fallback_reasons:
            lines.append(f"- fallback 原因: {reason}")
    else:
        lines.append("- fallback 原因: 无")
    lines.extend(
        [
            "",
        "## 字段缺失情况",
        "",
        ]
    )

    missing_columns = summary.get("missing_columns", [])
    lines.append(f"- 缺失字段: {'、'.join(missing_columns) if missing_columns else '无'}")
    missing_values = summary.get("missing_values", {})
    if missing_values:
        for field, ids in missing_values.items():
            lines.append(f"- {field} 缺失样本: {', '.join(ids)}")
    else:
        lines.append("- 缺失值: 无")
    duplicate_ids = summary.get("duplicate_ids", [])
    lines.append(f"- 重复 ID: {'、'.join(duplicate_ids) if duplicate_ids else '无'}")
    lines.append("")

    lines.extend(render_count_map("各问题类型分布", summary.get("category_distribution", {})))
    lines.extend(render_count_map("各优先级数量", summary.get("priority_distribution", {})))

    lines.extend(["## 需要人工复核的样本列表", ""])
    if state.classified_feedback:
        review_items = [item for item in state.classified_feedback if item.needs_human_review]
        if review_items:
            for item in review_items:
                reasons = "；".join(item.human_review_reasons)
                lines.append(f"- {item.id}: {item.priority} / {item.issue_category} / {reasons}")
        else:
            lines.append("- 无")
    else:
        lines.append("- 无")
    lines.append("")
    disagreement_ids = summary.get("llm_rule_disagreement_ids", [])
    lines.extend(
        [
            "## LLM 与规则分类分歧",
            "",
            f"- 分歧样本: {', '.join(disagreement_ids) if disagreement_ids else '无'}",
            "",
        ]
    )

    lines.extend(
        [
            "## Agent 本轮判断边界",
            "",
            "- v0.6 默认使用规则模式；用户明确启用后可由 DeepSeek 生成分类、摘要、用户需求和产品建议初稿。",
            "- 明确启用 LLM 但没有 API key 或调用失败时自动 fallback 到 rules.py。",
            "- 优先级、规则证据、QA 检查和人工复核队列仍由本地规则执行。",
            "- LLM 与规则分类不一致时保留两套结论并强制进入人工复核。",
            "- LLM 和规则输出都只作为初筛草稿，P0 和低置信样本必须人工复核。",
            "- 未接入真实用户画像、日志、支付系统或客服工单上下文。",
            "- 多问题反馈不会自动拆分为多个独立需求，只保留多命中标记。",
            "- rules.py 可通过本地人工标注 golden set 持续评测，但小样本指标不代表生产准确率。",
            "- 人工复核通过 review_decisions.csv 回写到独立 reviewed 结果，不覆盖原始分诊文件。",
            "- 暂不实现 RAG、向量数据库或文档检索。",
            "",
        ]
    )
    return "\n".join(lines)


def render_run_log(logs: List[RunStepLog]) -> str:
    lines = ["# Agent Run Log", ""]
    for index, log in enumerate(logs, start=1):
        warnings = "；".join(log.warnings) if log.warnings else "无"
        lines.extend(
            [
                f"## {index}. {log.step_name}",
                "",
                f"- 状态: {log.status}",
                f"- 输入摘要: {log.input_summary}",
                f"- 输出摘要: {log.output_summary}",
                f"- warnings: {warnings}",
                f"- 下一步动作: {log.next_action}",
                "",
            ]
        )
    return "\n".join(lines)


def classified_feedback_to_frame(items: List[ClassifiedFeedback]) -> pd.DataFrame:
    rows = []
    for item in items:
        rows.append(
            {
                "record_key": item.record_key,
                "id": item.id,
                "source": item.source,
                "app_name": item.app_name,
                "review_text": item.review_text,
                "rating": item.rating,
                "issue_category": item.issue_category,
                "rule_issue_category": item.rule_issue_category,
                "priority": item.priority,
                "confidence": item.confidence,
                "rule_confidence": item.rule_confidence,
                "matched_categories": "；".join(item.matched_categories),
                "matched_keywords": "；".join(
                    f"{category}:{','.join(keywords)}"
                    for category, keywords in item.matched_keywords.items()
                ),
                "summary": item.summary,
                "user_need": item.user_need,
                "product_suggestion": item.product_suggestion,
                "needs_human_review": item.needs_human_review,
                "human_review_reasons": "；".join(item.human_review_reasons),
                "classification_source": item.classification_source,
                "llm_rule_disagreement": item.llm_rule_disagreement,
                "llm_error": item.llm_error or "",
            }
        )
    return pd.DataFrame(rows, columns=TRIAGE_RESULT_COLUMNS)


def write_outputs(state: AgentRunState, final_logs: List[RunStepLog]) -> Dict[str, Path]:
    state.output_dir.mkdir(parents=True, exist_ok=True)

    issue_cards_path = state.output_dir / "issue_cards.md"
    qa_report_path = state.output_dir / "qa_report.md"
    run_log_path = state.output_dir / "run_log.md"
    results_csv_path = state.output_dir / "triage_results.csv"
    review_decisions_path = state.output_dir / "review_decisions.csv"

    issue_cards_path.write_text(render_issue_cards(state.issue_cards), encoding="utf-8")
    qa_report_path.write_text(render_qa_report(state), encoding="utf-8")
    run_log_path.write_text(render_run_log(final_logs), encoding="utf-8")
    classified_feedback_to_frame(state.classified_feedback).to_csv(results_csv_path, index=False)
    write_review_decisions(state.classified_feedback, review_decisions_path)

    return {
        "issue_cards": issue_cards_path,
        "qa_report": qa_report_path,
        "run_log": run_log_path,
        "triage_results": results_csv_path,
        "review_decisions": review_decisions_path,
    }
