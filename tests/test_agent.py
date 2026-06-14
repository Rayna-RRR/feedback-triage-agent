from pathlib import Path

from feedback_triage_agent.agent import FeedbackTriageAgent
from feedback_triage_agent.html_report import generate_html_report


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

    for filename in [
        "issue_cards.md",
        "qa_report.md",
        "run_log.md",
        "triage_results.csv",
        "review_decisions.csv",
    ]:
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


def test_empty_csv_exports_headers_and_generates_html(tmp_path: Path) -> None:
    input_path = tmp_path / "empty.csv"
    input_path.write_text("id,source,app_name,review_text,rating\n", encoding="utf-8")
    output_dir = tmp_path / "output"

    state = FeedbackTriageAgent(input_path=input_path, output_dir=output_dir).run()
    report_path = generate_html_report(output_dir)

    assert len(state.run_log) == 7
    results = (output_dir / "triage_results.csv").read_text(encoding="utf-8")
    assert results.startswith("record_key,id,source,app_name,review_text,rating")
    assert report_path.exists()
