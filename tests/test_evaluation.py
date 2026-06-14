from pathlib import Path

from typer.testing import CliRunner

from feedback_triage_agent.cli import app
from feedback_triage_agent.evaluation import evaluate_rules


runner = CliRunner()


def test_evaluate_rules_writes_metrics_and_sample_details(tmp_path: Path) -> None:
    source = tmp_path / "evaluation.csv"
    source.write_text(
        "id,source,app_name,review_text,rating,"
        "expected_issue_category,expected_priority,expected_human_review\n"
        'e1,test,App,"回答答非所问。",2,模型能力问题,P1,false\n'
        'e2,test,App,"闪退后数据丢失。",1,账号、隐私与数据问题,P0,true\n',
        encoding="utf-8",
    )

    summary = evaluate_rules(source, tmp_path / "output")

    assert summary.total_samples == 2
    assert summary.category_accuracy == 1
    assert summary.priority_accuracy == 1
    assert summary.p0_recall == 1
    assert (tmp_path / "output" / "evaluation_results.csv").exists()
    assert (tmp_path / "output" / "evaluation_report.md").exists()


def test_evaluate_command_fails_when_quality_gate_is_not_met(tmp_path: Path) -> None:
    source = tmp_path / "evaluation.csv"
    source.write_text(
        "id,source,app_name,review_text,rating,"
        "expected_issue_category,expected_priority,expected_human_review\n"
        'e1,test,App,"回答答非所问。",2,交互体验问题,P2,false\n',
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "evaluate",
            "--input",
            str(source),
            "--output",
            str(tmp_path / "output"),
            "--min-category-accuracy",
            "1",
        ],
    )

    assert result.exit_code == 1
    assert "Quality gates failed" in result.output


def test_project_golden_set_meets_quality_gates(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]

    summary = evaluate_rules(
        project_root / "data" / "evaluation_feedback.csv",
        tmp_path / "evaluation_output",
    )

    assert summary.category_accuracy >= 0.9
    assert summary.priority_accuracy >= 0.9
    assert summary.human_review_accuracy >= 0.9
    assert summary.p0_precision >= 0.9
    assert summary.p0_recall >= 0.9
