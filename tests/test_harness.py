import json
from pathlib import Path

from typer.testing import CliRunner

from feedback_triage_agent.cli import app
from feedback_triage_agent.harness import run_evaluation_harness


runner = CliRunner()


def write_labeled_csv(path: Path, rows: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "id,source,app_name,review_text,rating,scenario,"
        "expected_issue_category,expected_priority,expected_human_review\n"
        + rows,
        encoding="utf-8",
    )


def test_harness_runs_with_skip_pytest_and_ignores_adversarial_low_score(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    write_labeled_csv(
        root / "data" / "evaluation_feedback.csv",
        'g1,test,DemoApp,"回答经常答非所问，还会编造不存在的资料。",2,golden,模型能力问题,P1,false\n'
        'g2,test,DemoApp,"闪退后数据丢失。",1,golden,账号、隐私与数据问题,P0,true\n',
    )
    write_labeled_csv(
        root / "data" / "adversarial_feedback.csv",
        'a1,adversarial,DemoApp,"回答答非所问。",2,multi_intent,交互体验问题,P2,false\n',
    )

    result = run_evaluation_harness(
        tmp_path / "harness_output",
        skip_pytest=True,
        root=root,
    )
    summary = json.loads(Path(result.output_paths["harness_summary"]).read_text())
    report = Path(result.output_paths["harness_report"]).read_text(encoding="utf-8")

    assert result.pytest_skipped is True
    assert result.harness_passed is True
    assert result.golden_metrics
    assert result.adversarial_metrics
    assert result.adversarial_metrics["category_accuracy"] < 0.8
    assert summary["harness_passed"] is True
    assert summary["adversarial_completed"] is True
    assert "Evaluation Harness Report" in report


def test_harness_cli_writes_report_and_summary_with_skip_pytest(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli_harness_output"

    result = runner.invoke(
        app,
        ["harness", "--output", str(output_dir), "--skip-pytest"],
    )

    assert result.exit_code == 0
    assert (output_dir / "harness_report.md").exists()
    assert (output_dir / "harness_summary.json").exists()
    assert "Evaluation Harness Report" in (
        output_dir / "harness_report.md"
    ).read_text(encoding="utf-8")
