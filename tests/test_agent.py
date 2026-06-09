from pathlib import Path

from feedback_triage_agent.agent import FeedbackTriageAgent


def test_agent_runs_full_flow_and_exports_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    project_root = Path(__file__).resolve().parents[1]
    input_path = project_root / "data" / "sample_feedback.csv"
    output_dir = tmp_path / "output"

    state = FeedbackTriageAgent(input_path=input_path, output_dir=output_dir).run()

    assert len(state.raw_records) == 12
    assert len(state.classified_feedback) == 12
    assert len(state.issue_cards) == 12
    assert state.human_review_queue

    for filename in ["issue_cards.md", "qa_report.md", "run_log.md", "triage_results.csv"]:
        assert (output_dir / filename).exists()

    run_log = (output_dir / "run_log.md").read_text(encoding="utf-8")
    for step_name in [
        "load_feedback",
        "validate_schema",
        "classify_feedback",
        "detect_badcases",
        "generate_issue_cards",
        "qa_check",
        "export_report",
    ]:
        assert step_name in run_log
