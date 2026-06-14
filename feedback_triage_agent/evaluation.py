from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd
from pydantic import ValidationError

from feedback_triage_agent.models import FeedbackRecord
from feedback_triage_agent.rules import (
    ISSUE_CATEGORIES,
    REQUIRED_FIELDS,
    classify_feedback_record,
    detect_human_review_reasons,
)


EVALUATION_LABEL_FIELDS = [
    "expected_issue_category",
    "expected_priority",
    "expected_human_review",
]

EVALUATION_RESULT_COLUMNS = [
    "id",
    "review_text",
    "expected_issue_category",
    "predicted_issue_category",
    "category_correct",
    "expected_priority",
    "predicted_priority",
    "priority_correct",
    "expected_human_review",
    "predicted_human_review",
    "human_review_correct",
    "predicted_human_review_reasons",
]


@dataclass(frozen=True)
class EvaluationSummary:
    total_samples: int
    category_accuracy: float
    priority_accuracy: float
    human_review_accuracy: float
    p0_precision: float
    p0_recall: float
    output_paths: Dict[str, Path]


def parse_expected_bool(value: object) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"expected_human_review 不是合法布尔值: {value}")


def safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def render_evaluation_report(summary: EvaluationSummary, results: pd.DataFrame) -> str:
    category_errors = results[~results["category_correct"]]
    priority_errors = results[~results["priority_correct"]]
    review_errors = results[~results["human_review_correct"]]

    lines = [
        "# Rule Evaluation Report",
        "",
        "## 指标总览",
        "",
        f"- 样本数: {summary.total_samples}",
        f"- 分类准确率: {summary.category_accuracy:.2%}",
        f"- 优先级准确率: {summary.priority_accuracy:.2%}",
        f"- 人工复核判断准确率: {summary.human_review_accuracy:.2%}",
        f"- P0 Precision: {summary.p0_precision:.2%}",
        f"- P0 Recall: {summary.p0_recall:.2%}",
        "",
        "## 误差数量",
        "",
        f"- 分类错误: {len(category_errors)}",
        f"- 优先级错误: {len(priority_errors)}",
        f"- 人工复核判断错误: {len(review_errors)}",
        "",
        "## 分类错误样本",
        "",
    ]
    if category_errors.empty:
        lines.append("- 无")
    else:
        for _, row in category_errors.iterrows():
            lines.append(
                f"- {row['id']}: expected={row['expected_issue_category']}, "
                f"predicted={row['predicted_issue_category']}"
            )

    lines.extend(["", "## 说明", ""])
    lines.extend(
        [
            "- 本报告只评估本地 rules.py，不调用 LLM。",
            "- expected_* 字段是人工标注基准，不应由规则运行结果自动回填。",
            "- 指标用于发现规则退化和高风险漏判，不代表可以跳过人工复核。",
            "",
        ]
    )
    return "\n".join(lines)


def evaluate_rules(input_path: Path, output_dir: Path) -> EvaluationSummary:
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    try:
        source = pd.read_csv(input_path).fillna("")
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"评测 CSV 无法读取: {exc}") from exc

    required = REQUIRED_FIELDS + EVALUATION_LABEL_FIELDS
    missing = [field for field in required if field not in source.columns]
    if missing:
        raise ValueError("评测 CSV 缺少字段: " + "，".join(missing))
    if source.empty:
        raise ValueError("评测 CSV 不能为空")

    rows: List[Dict[str, object]] = []
    for index, raw_row in source.iterrows():
        try:
            record = FeedbackRecord.model_validate(raw_row.to_dict())
        except ValidationError as exc:
            raise ValueError(f"第 {index + 2} 行输入无效: {exc.errors()[0]['msg']}") from exc

        expected_category = str(raw_row["expected_issue_category"]).strip()
        expected_priority = str(raw_row["expected_priority"]).strip()
        if expected_category not in ISSUE_CATEGORIES:
            raise ValueError(f"第 {index + 2} 行 expected_issue_category 无效: {expected_category}")
        if expected_priority not in {"P0", "P1", "P2"}:
            raise ValueError(f"第 {index + 2} 行 expected_priority 无效: {expected_priority}")
        expected_review = parse_expected_bool(raw_row["expected_human_review"])

        predicted = classify_feedback_record(record)
        review_reasons = detect_human_review_reasons(predicted)
        predicted_review = bool(review_reasons)
        rows.append(
            {
                "id": record.id,
                "review_text": record.review_text,
                "expected_issue_category": expected_category,
                "predicted_issue_category": predicted.issue_category,
                "category_correct": predicted.issue_category == expected_category,
                "expected_priority": expected_priority,
                "predicted_priority": predicted.priority,
                "priority_correct": predicted.priority == expected_priority,
                "expected_human_review": expected_review,
                "predicted_human_review": predicted_review,
                "human_review_correct": predicted_review == expected_review,
                "predicted_human_review_reasons": "；".join(review_reasons),
            }
        )

    results = pd.DataFrame(rows, columns=EVALUATION_RESULT_COLUMNS)
    expected_p0 = results["expected_priority"] == "P0"
    predicted_p0 = results["predicted_priority"] == "P0"
    true_positive_p0 = int((expected_p0 & predicted_p0).sum())

    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "evaluation_results.csv"
    report_path = output_dir / "evaluation_report.md"
    summary = EvaluationSummary(
        total_samples=len(results),
        category_accuracy=float(results["category_correct"].mean()),
        priority_accuracy=float(results["priority_correct"].mean()),
        human_review_accuracy=float(results["human_review_correct"].mean()),
        p0_precision=safe_ratio(true_positive_p0, int(predicted_p0.sum())),
        p0_recall=safe_ratio(true_positive_p0, int(expected_p0.sum())),
        output_paths={
            "evaluation_results": results_path,
            "evaluation_report": report_path,
        },
    )
    results.to_csv(results_path, index=False)
    report_path.write_text(render_evaluation_report(summary, results), encoding="utf-8")
    return summary
