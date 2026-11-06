"""Public source provenance, lossless preparation, and human QA isolation."""

import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from scripts.prepare_ai_app_reviews import OUTPUT_FIELDS, prepare


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/ai_app_feedback"
HUMAN_QA = ROOT / "docs/ai_app_feedback/source/qa_report.md"
REVIEW_IDS = {
    "DB_009", "DB_010", "DS_004", "DS_005", "DS_008", "DS_009",
    "KIMI_002", "KIMI_005", "KIMI_010",
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def test_source_archive_hashes_and_full_annotation_contract():
    provenance = json.loads((DATA / "provenance.json").read_text())
    assert provenance["commit"] == "b537f7aa1a9080eeda8d1aaedd47f2e484b6613d"
    for entry in provenance["files"]:
        assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    raw = read_csv(DATA / "raw_reviews.csv")
    clean = read_csv(DATA / "clean_reviews.csv")
    assert len(raw) == len(clean) == 30
    assert len(clean[0]) == 14
    assert len(read_csv(DATA / "excluded_reviews.csv")) == 5
    fields = OUTPUT_FIELDS + ["review_date"]
    assert [{key: row[key] for key in fields} for row in raw] == [
        {key: row[key] for key in fields} for row in clean
    ]
    # Compare with the pre-existing five-field fixture, never relabel it as ground truth.
    assert [{key: row[key] for key in OUTPUT_FIELDS} for row in clean] == read_csv(ROOT / "data/ai_app_reviews.csv")


def test_preparation_runs_from_unrelated_cwd_and_preserves_existing_samples(tmp_path):
    output = tmp_path / "reviews.csv"
    manifest = tmp_path / "preparation.json"
    subprocess.run([
        sys.executable, str(ROOT / "scripts/prepare_ai_app_reviews.py"),
        "--output", str(output), "--manifest", str(manifest),
    ], cwd=tmp_path, check=True, capture_output=True)
    assert output.read_bytes() == (ROOT / "data/ai_app_reviews.csv").read_bytes()
    report = json.loads(manifest.read_text())
    assert report["rows"] == 30
    assert report["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert report["field_mapping"] == {key: key for key in OUTPUT_FIELDS}


@pytest.mark.parametrize("csv_text", [
    "id,source,app_name,rating\nx,store,app,1\n",  # missing text
    "id,source,app_name,review_text,rating\nx,store,app,,1\n",
    "id,source,app_name,review_text,rating\nx,store,app,text,1\nx,store,app,other,2\n",
    "id,source,app_name,review_text,rating\n,store,app,text,1\n",
    "id,source,app_name,review_text,rating\nx,store,app,text,6\n",
    "id,source,app_name,review_text,rating\nx,store,app,text,\n",
    "id,source,app_name,review_text,rating\nx,store,app,text,NaN\n",
    "id,source,app_name,review_text,rating\nx,store,app,text,1,extra\n",
    "id,source,app_name,review_text,rating\n",
    "id,id,source,app_name,review_text,rating\nx,x,store,app,text,1\n",
    "id,source,app_name,review_text,content,rating\nx,store,app,text,other,1\n",
])
def test_invalid_input_does_not_replace_existing_output(tmp_path, csv_text):
    source, output = tmp_path / "input.csv", tmp_path / "output.csv"
    source.write_text(csv_text)
    output.write_text("existing output")
    with pytest.raises(ValueError):
        prepare(source, output)
    assert output.read_text() == "existing output"


def test_explicit_alias_input_preserves_original_text_and_metadata(tmp_path):
    source = tmp_path / "external.csv"
    source.write_text('\ufeffreview_id,store,product,content,stars\nx,Store,App,"  原文,含逗号\\n换行  ",3\n'.replace('\\n', '\n'), encoding="utf-8")
    output = tmp_path / "output.csv"
    prepare(source, output)
    assert read_csv(output) == [{
        "id": "x", "source": "Store", "app_name": "App",
        "review_text": "  原文,含逗号\n换行  ", "rating": "3",
    }]
    with pytest.raises(ValueError, match="不同文件"):
        prepare(source, source)


def test_automatic_qa_retains_warnings_and_cannot_overwrite_human_review(tmp_path):
    original = HUMAN_QA.read_bytes()
    report = tmp_path / "qa.md"
    subprocess.run([
        sys.executable, str(ROOT / "scripts/label_quality_check.py"), "--output", str(report),
    ], cwd=tmp_path, check=True, capture_output=True)
    text = report.read_text()
    assert "需复核样本数：9" in text
    assert "文件结构/整体警告对象数：1" in text
    auto_ids = set(re.findall(r"^- `([^`]+)`", text, re.M)) - {"整体数据"}
    human_ids = set(re.findall(r"^\| `([^`]+)`", original.decode(), re.M))
    assert auto_ids == human_ids == REVIEW_IDS
    blocked = subprocess.run([
        sys.executable, str(ROOT / "scripts/label_quality_check.py"), "--output", str(HUMAN_QA),
    ], capture_output=True)
    assert blocked.returncode != 0
    assert HUMAN_QA.read_bytes() == original


def test_summary_counts_match_preserved_analysis_report(tmp_path):
    subprocess.run([
        sys.executable, str(ROOT / "scripts/summarize_reviews.py"), "--output-dir", str(tmp_path),
    ], cwd=tmp_path, check=True, capture_output=True)
    counts = {row["issue_category"]: int(row["count"]) for row in read_csv(tmp_path / "issue_category_distribution.csv")}
    assert sum(counts.values()) == 30
    assert counts["模型能力问题"] == 11
    assert counts["性能与稳定性问题"] == 6
    assert {row["priority"]: int(row["count"]) for row in read_csv(tmp_path / "priority_distribution.csv")} == {"P0": 4, "P1": 20, "P2": 6}


def test_comparison_joins_every_sample_and_rejects_changed_evidence(tmp_path):
    from scripts.compare_ai_app_labels import compare

    source = read_csv(DATA / "clean_reviews.csv")
    results = tmp_path / "results.csv"
    fields = OUTPUT_FIELDS + ["issue_category", "priority", "needs_human_review"]

    def write_results(rows):
        with results.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({**{key: row[key] for key in fields[:-1]}, "needs_human_review": False})

    write_results(list(reversed(source)))
    output = tmp_path / "comparison.csv"
    compared = compare(DATA / "clean_reviews.csv", results, output)
    assert [row["id"] for row in compared] == [row["id"] for row in source]
    write_results(source[:-1])
    with pytest.raises(ValueError, match="ID 集合不同"):
        compare(DATA / "clean_reviews.csv", results, output)
    changed = [dict(row) for row in source]
    changed[0]["review_text"] = "different evidence"
    write_results(changed)
    with pytest.raises(ValueError, match="review_text"):
        compare(DATA / "clean_reviews.csv", results, output)
