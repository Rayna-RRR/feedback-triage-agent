from pathlib import Path
from typing import Dict, List, Optional
import csv


SOURCE_DIR = Path("data/source_ai_app_feedback")
OUTPUT_PATH = Path("data/ai_app_reviews.csv")
OUTPUT_FIELDS = ["id", "source", "app_name", "review_text", "rating"]

FIELD_CANDIDATES = {
    "id": ["id", "review_id"],
    "source": ["source", "platform", "store"],
    "app_name": ["app_name", "app", "product"],
    "review_text": ["review_text", "content", "comment", "text", "original_text"],
    "rating": ["rating", "score", "stars"],
}


def pick_source_file(source_dir: Path) -> Path:
    preferred_files = [
        source_dir / "clean_reviews.csv",
        source_dir / "raw_reviews.csv",
    ]
    for path in preferred_files:
        if path.exists():
            return path

    candidates = sorted(
        path
        for path in source_dir.glob("*.csv")
        if "review" in path.name.lower()
    )
    if candidates:
        return candidates[0]

    raise FileNotFoundError(f"找不到评论 CSV 文件: {source_dir}")


def normalize_header(name: str) -> str:
    return name.strip().lower()


def build_field_mapping(fieldnames: List[str]) -> Dict[str, Optional[str]]:
    normalized_to_original = {
        normalize_header(fieldname): fieldname
        for fieldname in fieldnames
    }
    mapping = {}
    for output_field, candidates in FIELD_CANDIDATES.items():
        mapping[output_field] = None
        for candidate in candidates:
            if candidate in normalized_to_original:
                mapping[output_field] = normalized_to_original[candidate]
                break
    return mapping


def value_from_row(row: Dict[str, str], field: Optional[str], default: str = "") -> str:
    if field is None:
        return default
    value = row.get(field, "")
    return "" if value is None else str(value).strip()


def transform_rows(rows: List[Dict[str, str]], mapping: Dict[str, Optional[str]]) -> List[Dict[str, str]]:
    output_rows = []
    for index, row in enumerate(rows, start=1):
        output_rows.append(
            {
                "id": value_from_row(row, mapping["id"]) or f"review{index:03d}",
                "source": value_from_row(row, mapping["source"]) or "unknown_source",
                "app_name": value_from_row(row, mapping["app_name"]) or "unknown_app",
                "review_text": value_from_row(row, mapping["review_text"]),
                "rating": value_from_row(row, mapping["rating"]),
            }
        )
    return output_rows


def format_mapping(mapping: Dict[str, Optional[str]]) -> str:
    parts = []
    for output_field in OUTPUT_FIELDS:
        source_field = mapping[output_field]
        if source_field is None:
            if output_field == "id":
                source_field = "auto_generated"
            elif output_field == "source":
                source_field = "unknown_source"
            elif output_field == "app_name":
                source_field = "unknown_app"
            elif output_field == "rating":
                source_field = "empty"
            else:
                source_field = "missing"
        parts.append(f"{output_field} <- {source_field}")
    return "; ".join(parts)


def main() -> None:
    source_file = pick_source_file(SOURCE_DIR)
    with source_file.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    mapping = build_field_mapping(fieldnames)
    output_rows = transform_rows(rows, mapping)
    empty_review_text_count = sum(1 for row in output_rows if not row["review_text"].strip())

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"使用源文件: {source_file}")
    print(f"字段映射: {format_mapping(mapping)}")
    print(f"原始行数: {len(rows)}")
    print(f"输出行数: {len(output_rows)}")
    print(f"输出字段: {', '.join(OUTPUT_FIELDS)}")
    print(f"空 review_text 数量: {empty_review_text_count}")
    print(f"输出文件路径: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
