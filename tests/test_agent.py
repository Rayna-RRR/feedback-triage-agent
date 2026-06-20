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
        "weekly_summary.md",
        "review_decisions.csv",
    ]:
        assert (output_dir / filename).exists()

    weekly_summary = (output_dir / "weekly_summary.md").read_text(encoding="utf-8")
    assert "Priority Issues" in weekly_summary
    assert "Evidence quote" in weekly_summary
    assert "Suggested product follow-up" in weekly_summary
    assert "Review status" in weekly_summary

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


def test_agent_exports_normalized_input_and_keeps_seven_tool_steps(tmp_path: Path) -> None:
    input_path = tmp_path / "chatgpt_reviews_latest_5000.csv"
    input_path.write_text(
        "reviewId,content,score\n"
        'r001,"wrong answer",1\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"

    state = FeedbackTriageAgent(
        input_path=input_path,
        output_dir=output_dir,
        normalize_input=True,
        input_name=input_path.name,
    ).run()

    assert len(state.run_log) == 7
    assert (output_dir / "normalized_feedback.csv").exists()
    assert "normalized_feedback" in state.output_paths
    qa_report = (output_dir / "qa_report.md").read_text(encoding="utf-8")
    assert "reviewId -> id" in qa_report
    assert "source=google_play" in qa_report
