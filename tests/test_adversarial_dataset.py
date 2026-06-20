from pathlib import Path

import pandas as pd

from feedback_triage_agent.evaluation import parse_expected_bool
from feedback_triage_agent.rules import ISSUE_CATEGORIES


ADVERSARIAL_COLUMNS = [
    "id",
    "source",
    "app_name",
    "review_text",
    "rating",
    "expected_issue_category",
    "expected_priority",
    "expected_human_review",
]


def test_adversarial_feedback_dataset_contract() -> None:
    project_root = Path(__file__).resolve().parents[1]
    dataset_path = project_root / "data" / "adversarial_feedback.csv"

    assert dataset_path.exists()

    dataset = pd.read_csv(dataset_path)

    assert list(dataset.columns) == ADVERSARIAL_COLUMNS
    assert len(dataset) >= 12
    assert dataset["id"].is_unique
    assert set(dataset["expected_issue_category"]).issubset(set(ISSUE_CATEGORIES))
    assert set(dataset["expected_priority"]).issubset({"P0", "P1", "P2"})
    assert dataset["expected_human_review"].map(parse_expected_bool).notna().all()
