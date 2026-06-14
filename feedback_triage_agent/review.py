from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd

from feedback_triage_agent.models import ClassifiedFeedback
from feedback_triage_agent.rules import ISSUE_CATEGORIES


REVIEW_DECISIONS_COLUMNS = [
    "record_key",
    "id",
    "decision",
    "original_issue_category",
    "original_priority",
    "final_issue_category",
    "final_priority",
    "human_review_reasons",
    "reviewer_note",
    "reviewed_at",
]

VALID_DECISIONS = {"pending", "confirm", "adjust", "keep_open"}


@dataclass(frozen=True)
class ReviewApplySummary:
    total_decisions: int
    reviewed_count: int
    open_count: int
    pending_count: int
    output_paths: Dict[str, Path]


def boolish(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def decisions_frame(items: List[ClassifiedFeedback]) -> pd.DataFrame:
    rows = []
    for item in items:
        if not item.needs_human_review:
            continue
        rows.append(
            {
                "record_key": item.record_key,
                "id": item.id,
                "decision": "pending",
                "original_issue_category": item.issue_category,
                "original_priority": item.priority,
                "final_issue_category": "",
                "final_priority": "",
                "human_review_reasons": "；".join(item.human_review_reasons),
                "reviewer_note": "",
                "reviewed_at": "",
            }
        )
    return pd.DataFrame(rows, columns=REVIEW_DECISIONS_COLUMNS)


def write_review_decisions(items: List[ClassifiedFeedback], path: Path) -> Path:
    decisions_frame(items).to_csv(path, index=False)
    return path


def render_review_summary(summary: ReviewApplySummary, decisions: pd.DataFrame) -> str:
    counts = decisions["decision"].value_counts().to_dict() if len(decisions) else {}
    lines = [
        "# Human Review Summary",
        "",
        "## 总览",
        "",
        f"- 决策记录数: {summary.total_decisions}",
        f"- 已关闭复核: {summary.reviewed_count}",
        f"- 保持开放: {summary.open_count}",
        f"- 待处理: {summary.pending_count}",
        "",
        "## 决策分布",
        "",
    ]
    if counts:
        for decision, count in counts.items():
            lines.append(f"- {decision}: {count}")
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- confirm 表示人工确认原分类和优先级。",
            "- adjust 必须填写 final_issue_category 和 final_priority。",
            "- keep_open 保留人工复核状态，不自动闭环。",
            "- 原始 triage_results.csv 不会被覆盖。",
            "",
        ]
    )
    return "\n".join(lines)


def _normalize_decisions(decisions: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REVIEW_DECISIONS_COLUMNS if column not in decisions.columns]
    if missing:
        raise ValueError("review_decisions.csv 缺少字段: " + "，".join(missing))

    decisions = decisions.fillna("").copy()
    decisions["record_key"] = decisions["record_key"].astype(str).str.strip()
    decisions["decision"] = decisions["decision"].astype(str).str.strip().str.lower()
    if decisions["record_key"].eq("").any():
        raise ValueError("review_decisions.csv 存在空 record_key")
    duplicate_keys = decisions.loc[decisions["record_key"].duplicated(), "record_key"].tolist()
    if duplicate_keys:
        raise ValueError("review_decisions.csv 存在重复 record_key: " + "，".join(duplicate_keys))

    invalid_decisions = sorted(set(decisions["decision"]) - VALID_DECISIONS)
    if invalid_decisions:
        raise ValueError("不支持的 review decision: " + "，".join(invalid_decisions))

    for index, row in decisions.iterrows():
        if row["decision"] != "adjust":
            continue
        category = str(row["final_issue_category"]).strip()
        priority = str(row["final_priority"]).strip()
        if category not in ISSUE_CATEGORIES:
            raise ValueError(f"{row['record_key']} 的 final_issue_category 无效")
        if priority not in {"P0", "P1", "P2"}:
            raise ValueError(f"{row['record_key']} 的 final_priority 无效")
        decisions.at[index, "final_issue_category"] = category
        decisions.at[index, "final_priority"] = priority
    return decisions


def apply_review_decisions(
    results_path: Path,
    decisions_path: Path,
    output_dir: Path,
) -> ReviewApplySummary:
    try:
        results = pd.read_csv(results_path).fillna("")
        decisions = pd.read_csv(decisions_path).fillna("")
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"复核输入无法读取: {exc}") from exc

    required_result_columns = [
        "record_key",
        "issue_category",
        "priority",
        "needs_human_review",
    ]
    missing_result_columns = [
        column for column in required_result_columns if column not in results.columns
    ]
    if missing_result_columns:
        raise ValueError(
            "triage_results.csv 缺少字段: " + "，".join(missing_result_columns)
        )
    decisions = _normalize_decisions(decisions)

    result_keys = set(results["record_key"].astype(str))
    unknown_keys = sorted(set(decisions["record_key"]) - result_keys)
    if unknown_keys:
        raise ValueError("复核文件包含未知 record_key: " + "，".join(unknown_keys))
    reviewable_keys = set(
        results.loc[
            results["needs_human_review"].map(boolish),
            "record_key",
        ].astype(str)
    )
    non_reviewable_keys = sorted(set(decisions["record_key"]) - reviewable_keys)
    if non_reviewable_keys:
        raise ValueError(
            "复核文件包含无需人工复核的 record_key: " + "，".join(non_reviewable_keys)
        )

    reviewed = results.copy()
    reviewed["original_issue_category"] = reviewed["issue_category"]
    reviewed["original_priority"] = reviewed["priority"]
    reviewed["review_decision"] = ""
    reviewed["review_status"] = ""
    reviewed["reviewer_note"] = ""
    reviewed["reviewed_at"] = ""

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for _, decision_row in decisions.iterrows():
        record_key = decision_row["record_key"]
        decision = decision_row["decision"]
        mask = reviewed["record_key"].astype(str) == record_key
        reviewed.loc[mask, "review_decision"] = decision
        reviewed.loc[mask, "reviewer_note"] = str(decision_row["reviewer_note"]).strip()

        if decision == "adjust":
            reviewed.loc[mask, "issue_category"] = decision_row["final_issue_category"]
            reviewed.loc[mask, "priority"] = decision_row["final_priority"]
        if decision in {"confirm", "adjust"}:
            reviewed.loc[mask, "needs_human_review"] = False
            reviewed.loc[mask, "review_status"] = "reviewed"
            reviewed.loc[mask, "reviewed_at"] = str(decision_row["reviewed_at"]).strip() or now
        elif decision == "keep_open":
            reviewed.loc[mask, "needs_human_review"] = True
            reviewed.loc[mask, "review_status"] = "open"
        else:
            reviewed.loc[mask, "review_status"] = "pending"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reviewed_path = output_dir / "triage_results_reviewed.csv"
    summary_path = output_dir / "review_summary.md"

    reviewed_count = int(decisions["decision"].isin({"confirm", "adjust"}).sum())
    open_count = int(decisions["decision"].eq("keep_open").sum())
    pending_count = int(decisions["decision"].eq("pending").sum())
    summary = ReviewApplySummary(
        total_decisions=len(decisions),
        reviewed_count=reviewed_count,
        open_count=open_count,
        pending_count=pending_count,
        output_paths={
            "triage_results_reviewed": reviewed_path,
            "review_summary": summary_path,
        },
    )
    reviewed.to_csv(reviewed_path, index=False)
    summary_path.write_text(render_review_summary(summary, decisions), encoding="utf-8")
    return summary
