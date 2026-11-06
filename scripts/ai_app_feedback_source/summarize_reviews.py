"""读取 clean_reviews.csv 并输出基础计数。

本脚本只做简单汇总，不生成分析结论，不采集数据，也不依赖第三方库。
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLEAN_REVIEWS_PATH = PROJECT_ROOT / "data" / "clean_reviews.csv"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "charts"


def read_clean_reviews(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"未找到文件：{path}")

    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def normalize_value(value: str | None) -> str:
    value = (value or "").strip()
    return value if value else "未填写"


def count_by_field(rows: list[dict[str, str]], field: str) -> Counter[str]:
    return Counter(normalize_value(row.get(field)) for row in rows)


def print_counter(title: str, counter: Counter[str]) -> None:
    print(f"\n{title}")
    if not counter:
        print("- 暂无数据")
        return

    for value, count in counter.most_common():
        print(f"- {value}: {count}")


def save_counter_csv(counter: Counter[str], output_path: Path, value_name: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([value_name, "count"])
        for value, count in counter.most_common():
            writer.writerow([value, count])


def main() -> None:
    rows = read_clean_reviews(CLEAN_REVIEWS_PATH)

    app_counts = count_by_field(rows, "app_name")
    issue_category_counts = count_by_field(rows, "issue_category")
    ai_issue_type_counts = count_by_field(rows, "ai_issue_type")
    priority_counts = count_by_field(rows, "priority")
    top_ai_issue_types = Counter(dict(ai_issue_type_counts.most_common(5)))

    print("AI 应用评论基础统计")
    print("注意：以下仅为计数输出，不代表最终分析结论。")
    print(f"\n总样本数: {len(rows)}")

    print_counter("按 app_name 统计", app_counts)
    print_counter("issue_category 分布", issue_category_counts)
    print_counter("ai_issue_type 分布", ai_issue_type_counts)
    print_counter("priority 分布", priority_counts)
    print_counter("Top 5 ai_issue_type", top_ai_issue_types)

    save_counter_csv(app_counts, OUTPUT_DIR / "samples_by_app_name.csv", "app_name")
    save_counter_csv(
        issue_category_counts,
        OUTPUT_DIR / "issue_category_distribution.csv",
        "issue_category",
    )
    save_counter_csv(
        ai_issue_type_counts,
        OUTPUT_DIR / "ai_issue_type_distribution.csv",
        "ai_issue_type",
    )
    save_counter_csv(priority_counts, OUTPUT_DIR / "priority_distribution.csv", "priority")
    save_counter_csv(top_ai_issue_types, OUTPUT_DIR / "top5_ai_issue_type.csv", "ai_issue_type")

    print(f"\n汇总 CSV 已保存到：{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
