"""安全追加 raw review rows 到 data/raw_reviews.csv。

从标准输入读取 CSV rows；发现重复 id 时停止，不写入任何新行。
"""

from __future__ import annotations

import csv
import sys
from io import StringIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "data" / "raw_reviews.csv"
FIELDNAMES = ["id", "source", "app_name", "review_date", "rating", "review_text", "notes"]


def ensure_target_exists(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()


def read_existing_ids(path: Path) -> set[str]:
    ensure_target_exists(path)
    with path.open("r", newline="", encoding="utf-8") as file:
        return {
            (row.get("id") or "").strip()
            for row in csv.DictReader(file)
            if (row.get("id") or "").strip()
        }


def read_input_rows(text: str) -> list[dict[str, str]]:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("未收到要追加的 CSV rows。")

    reader = csv.reader(StringIO(cleaned))
    rows = [row for row in reader if any(cell.strip() for cell in row)]

    if rows and rows[0] == FIELDNAMES:
        rows = rows[1:]

    parsed: list[dict[str, str]] = []
    for line_number, row in enumerate(rows, start=1):
        if len(row) != len(FIELDNAMES):
            raise ValueError(f"第 {line_number} 行字段数为 {len(row)}，应为 {len(FIELDNAMES)}。")
        parsed.append(dict(zip(FIELDNAMES, row)))
    return parsed


def append_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writerows(rows)


def main() -> None:
    input_text = sys.stdin.read()
    rows = read_input_rows(input_text)
    existing_ids = read_existing_ids(TARGET_PATH)
    new_ids = [(row.get("id") or "").strip() for row in rows]

    missing_ids = [index + 1 for index, row_id in enumerate(new_ids) if not row_id]
    if missing_ids:
        raise ValueError(f"以下输入行缺少 id：{missing_ids}")

    duplicate_in_input = sorted({row_id for row_id in new_ids if new_ids.count(row_id) > 1})
    if duplicate_in_input:
        raise ValueError(f"输入中存在重复 id，已停止追加：{', '.join(duplicate_in_input)}")

    duplicate_existing = sorted(set(new_ids) & existing_ids)
    if duplicate_existing:
        raise ValueError(f"目标文件中已存在这些 id，已停止追加：{', '.join(duplicate_existing)}")

    append_rows(TARGET_PATH, rows)
    print(f"已追加 {len(rows)} 行到 {TARGET_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"追加失败：{exc}", file=sys.stderr)
        sys.exit(1)
