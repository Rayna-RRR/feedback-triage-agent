"""Join archived annotations with rule output by ID; differences are not accuracy scores."""

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/ai_app_feedback"
OUTPUT_FIELDS = [
    "id", "source", "app_name", "source_issue_category", "source_ai_issue_type",
    "source_priority", "system_issue_category", "system_priority",
    "system_needs_human_review", "category_matches", "priority_matches", "source_notes",
]


def read_by_id(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    by_id = {row["id"]: row for row in rows}
    if not rows or len(by_id) != len(rows) or "" in by_id:
        raise ValueError(f"ID 必须非空且唯一，输入不能为空: {path}")
    return by_id


def compare(annotations, results, output):
    source = read_by_id(annotations)
    system = read_by_id(results)
    if source.keys() != system.keys():
        raise ValueError("标注与系统输出的 ID 集合不同")
    compared = []
    for record_id, row in source.items():
        predicted = system[record_id]
        for field in ("source", "app_name", "review_text", "rating"):
            if row[field] != predicted[field]:
                raise ValueError(f"{record_id} 的 {field} 与来源样本不同")
        compared.append({
            "id": record_id, "source": row["source"], "app_name": row["app_name"],
            "source_issue_category": row["issue_category"],
            "source_ai_issue_type": row["ai_issue_type"], "source_priority": row["priority"],
            "system_issue_category": predicted["issue_category"],
            "system_priority": predicted["priority"],
            "system_needs_human_review": predicted["needs_human_review"],
            "category_matches": row["issue_category"] == predicted["issue_category"],
            "priority_matches": row["priority"] == predicted["priority"],
            "source_notes": row["notes"],
        })
    if output.resolve() in {annotations.resolve(), results.resolve()}:
        raise ValueError("对照表不能覆盖标注或系统结果")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(compared)
    return compared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=DATA / "clean_reviews.csv")
    parser.add_argument("--results", type=Path, default=DATA / "generated/triage/triage_results.csv")
    parser.add_argument("--output", type=Path, default=DATA / "generated/label_comparison.csv")
    args = parser.parse_args()
    try:
        rows = compare(args.annotations, args.results, args.output)
    except (OSError, UnicodeError, ValueError, KeyError, csv.Error) as exc:
        parser.error(str(exc))
    print(f"对照 {len(rows)} 条：分类差异 {sum(not r['category_matches'] for r in rows)}，"
          f"优先级差异 {sum(not r['priority_matches'] for r in rows)}。这不是准确率评测。")


if __name__ == "__main__":
    main()
