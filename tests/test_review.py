from pathlib import Path

import pandas as pd
import pytest

from feedback_triage_agent.agent import FeedbackTriageAgent
from feedback_triage_agent.review import apply_review_decisions


def run_sample_agent(tmp_path: Path) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    output_dir = tmp_path / "output"
    FeedbackTriageAgent(
        input_path=project_root / "data" / "sample_feedback.csv",
        output_dir=output_dir,
        llm_requested=False,
    ).run()
    return output_dir


def test_agent_exports_review_decision_template_with_stable_keys(tmp_path: Path) -> None:
    source = tmp_path / "duplicate_ids.csv"
    source.write_text(
        "id,source,app_name,review_text,rating\n"
        'same,test,App,"闪退后内容丢失。",1\n'
        'same,test,App,"自动扣费后无法退款。",1\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    FeedbackTriageAgent(source, output_dir, llm_requested=False).run()

    decisions = pd.read_csv(output_dir / "review_decisions.csv").fillna("")

    assert len(decisions) == 2
    assert decisions["record_key"].is_unique
    assert set(decisions["decision"]) == {"pending"}
    assert set(decisions["record_key"]).issubset(
        set(pd.read_csv(output_dir / "triage_results.csv")["record_key"])
    )


def test_apply_review_decisions_closes_and_adjusts_without_overwriting_raw_results(
    tmp_path: Path,
) -> None:
    output_dir = run_sample_agent(tmp_path)
    raw_path = output_dir / "triage_results.csv"
    raw_before = raw_path.read_bytes()
    decisions_path = output_dir / "review_decisions.csv"
    decisions = pd.read_csv(decisions_path).fillna("")

    decisions.loc[0, "decision"] = "confirm"
    decisions.loc[0, "reviewer_note"] = "确认原判断"
    decisions.loc[1, "decision"] = "adjust"
    decisions.loc[1, "final_issue_category"] = "交互体验问题"
    decisions.loc[1, "final_priority"] = "P2"
    decisions.to_csv(decisions_path, index=False)

    summary = apply_review_decisions(raw_path, decisions_path, output_dir)
    reviewed = pd.read_csv(output_dir / "triage_results_reviewed.csv").fillna("")

    assert raw_path.read_bytes() == raw_before
    assert summary.reviewed_count == 2
    assert (output_dir / "review_summary.md").exists()

    confirmed_key = decisions.loc[0, "record_key"]
    confirmed = reviewed[reviewed["record_key"] == confirmed_key].iloc[0]
    assert str(confirmed["needs_human_review"]).lower() == "false"
    assert confirmed["review_status"] == "reviewed"

    adjusted_key = decisions.loc[1, "record_key"]
    adjusted = reviewed[reviewed["record_key"] == adjusted_key].iloc[0]
    assert adjusted["issue_category"] == "交互体验问题"
    assert adjusted["priority"] == "P2"


def test_adjust_decision_requires_final_category_and_priority(tmp_path: Path) -> None:
    output_dir = run_sample_agent(tmp_path)
    decisions_path = output_dir / "review_decisions.csv"
    decisions = pd.read_csv(decisions_path).fillna("")
    decisions.loc[0, "decision"] = "adjust"
    decisions.to_csv(decisions_path, index=False)

    with pytest.raises(ValueError, match="final_issue_category"):
        apply_review_decisions(
            output_dir / "triage_results.csv",
            decisions_path,
            output_dir,
        )
