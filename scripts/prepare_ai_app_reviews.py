"""Project a review CSV into the legacy five-field input without changing samples."""

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = PROJECT_ROOT / "data/ai_app_feedback/clean_reviews.csv"
OUTPUT_PATH = PROJECT_ROOT / "data/ai_app_reviews.csv"
MANIFEST_PATH = PROJECT_ROOT / "data/ai_app_feedback/generated/preparation.json"
OUTPUT_FIELDS = ["id", "source", "app_name", "review_text", "rating"]
FIELD_CANDIDATES = {
    "id": ["id", "review_id"],
    "source": ["source", "platform", "store"],
    "app_name": ["app_name", "app", "product"],
    "review_text": ["review_text", "content", "comment", "text", "original_text"],
    "rating": ["rating", "score", "stars"],
}


def build_field_mapping(fieldnames: List[str]) -> Dict[str, str]:
    normalized = [name.strip().lower() for name in fieldnames]
    if len(set(normalized)) != len(normalized):
        raise ValueError("CSV 包含重复列名")
    headers = dict(zip(normalized, fieldnames))
    mapping = {}
    for field, candidates in FIELD_CANDIDATES.items():
        matches = [headers[name] for name in candidates if name in headers]
        if len(matches) != 1:
            raise ValueError(f"字段 {field} 必须有唯一来源列，实际匹配: {matches}")
        mapping[field] = matches[0]
    return mapping


def transform_rows(rows: List[Dict[str, str]], mapping: Dict[str, str]) -> List[Dict[str, str]]:
    if not rows:
        raise ValueError("评论 CSV 不能为空")
    output_rows = []
    seen = set()
    for line, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"第 {line} 行列数与表头不一致")
        output = {field: row[column] for field, column in mapping.items()}
        for field in OUTPUT_FIELDS:
            if not output[field].strip():
                raise ValueError(f"第 {line} 行 {field} 为空；不会自动补造标识或正文")
        record_id = output["id"]
        if record_id != record_id.strip() or record_id in seen:
            raise ValueError(f"第 {line} 行 id 重复或包含首尾空格: {record_id!r}")
        seen.add(record_id)
        if output["rating"].strip():
            try:
                rating = Decimal(output["rating"])
                if not rating.is_finite() or rating != rating.to_integral_value() or not 1 <= rating <= 5:
                    raise InvalidOperation
            except InvalidOperation as exc:
                raise ValueError(f"第 {line} 行 rating 必须是 1–5 的整数") from exc
        # Preserve text and metadata verbatim; labels stay in the full source CSV.
        output_rows.append(output)
    return output_rows


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def prepare(source: Path, output: Path, manifest: Optional[Path] = None) -> Dict[str, object]:
    paths = [source.resolve(), output.resolve()]
    if manifest is not None:
        paths.append(manifest.resolve())
    if len(set(paths)) != len(paths):
        raise ValueError("输入、输出和转换记录必须是不同文件")
    source_bytes = source.read_bytes()
    reader = csv.DictReader(io.StringIO(source_bytes.decode("utf-8-sig"), newline=""))
    mapping = build_field_mapping(list(reader.fieldnames or []))
    rows = transform_rows(list(reader), mapping)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    output_bytes = buffer.getvalue().encode("utf-8")
    report = {
        "source": display_path(source),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "output": display_path(output),
        "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "rows": len(rows),
        "field_mapping": mapping,
        "ids": [row["id"] for row in rows],
        "note": "Projection only; full annotations and human QA are preserved separately.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)
    if manifest is not None:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PATH, help="显式来源 CSV，默认使用仓库内完整标注集")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH, help="转换路径、哈希与字段映射记录")
    args = parser.parse_args()
    try:
        report = prepare(args.source, args.output, args.manifest)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
