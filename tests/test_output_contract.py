from pathlib import Path
from typing import get_args

import pandas as pd
import pytest
from pandas.api.types import is_bool_dtype

from feedback_triage_agent.agent import FeedbackTriageAgent
from feedback_triage_agent.exporters import TRIAGE_RESULT_COLUMNS
from feedback_triage_agent.models import ClassificationSource
from feedback_triage_agent.review import REVIEW_DECISIONS_COLUMNS
from feedback_triage_agent.rules import ISSUE_CATEGORIES


REQUIRED_OUTPUT_FILES = {
    "issue_cards.md",
    "qa_report.md",
    "run_log.md",
    "triage_results.csv",
    "review_decisions.csv",
}


@pytest.fixture()
def agent_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    input_path = tmp_path / "feedback.csv"
    input_path.write_text(
        "id,source,app_name,review_text,rating\n"
        'a001,test,ChatMate,"闪退后内容丢失。",1\n'
        'a002,test,ChatMate,"good app",5\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"

    FeedbackTriageAgent(
        input_path=input_path,
        output_dir=output_dir,
        llm_requested=False,
    ).run()

    return output_dir


def is_boolish_series(series: pd.Series) -> bool:
    if is_bool_dtype(series):
        return True
    values = set(series.dropna().astype(str).str.strip().str.lower())
    return values.issubset({"true", "false", "1", "0", "yes", "no", "y", "n"})


def test_agent_exports_required_files(agent_output_dir: Path) -> None:
    exported_files = {path.name for path in agent_output_dir.iterdir()}

    assert REQUIRED_OUTPUT_FILES.issubset(exported_files)


def test_triage_results_contract(agent_output_dir: Path) -> None:
    results = pd.read_csv(agent_output_dir / "triage_results.csv")

    assert list(results.columns) == TRIAGE_RESULT_COLUMNS
    assert set(results["priority"]).issubset({"P0", "P1", "P2"})
    assert set(results["issue_category"]).issubset(set(ISSUE_CATEGORIES))
    assert set(results["classification_source"]).issubset(
        set(get_args(ClassificationSource))
    )
    assert is_boolish_series(results["needs_human_review"])
    assert is_boolish_series(results["llm_rule_disagreement"])


def test_review_decisions_contract(agent_output_dir: Path) -> None:
    decisions = pd.read_csv(agent_output_dir / "review_decisions.csv")
    results = pd.read_csv(agent_output_dir / "triage_results.csv")

    assert list(decisions.columns) == REVIEW_DECISIONS_COLUMNS
    assert not decisions.empty
    assert "record_key" in decisions.columns
    assert not decisions["record_key"].isna().any()
    assert decisions["record_key"].astype(str).str.strip().ne("").all()
    assert decisions["record_key"].is_unique
    assert set(decisions["record_key"]).issubset(set(results["record_key"]))


def test_markdown_outputs_are_not_empty(agent_output_dir: Path) -> None:
    for filename in ["qa_report.md", "run_log.md", "issue_cards.md"]:
        content = (agent_output_dir / filename).read_text(encoding="utf-8").strip()

        assert content
