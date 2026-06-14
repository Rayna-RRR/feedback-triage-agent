from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from feedback_triage_agent.agent import FeedbackTriageAgent
from feedback_triage_agent.cli import app, infer_input_path
from feedback_triage_agent.task_parser import infer_output_dir


runner = CliRunner()


def write_csv(path: Path) -> None:
    path.write_text(
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"回答不准确，而且页面卡住。",2\n',
        encoding="utf-8",
    )


def test_ask_command_can_infer_input_path() -> None:
    path = infer_input_path("分析 data/ai_app_reviews.csv，输出问题卡片和人工复核队列")

    assert path == Path("data/ai_app_reviews.csv")


def test_ask_command_parses_paths_with_spaces_and_windows_drive() -> None:
    task = r"分析 C:\My Data\reviews.csv，输出到 C:\My Reports"

    assert infer_input_path(task) == Path(r"C:\My Data\reviews.csv")
    assert infer_output_dir(task) == Path(r"C:\My Reports")


def test_ask_command_runs_agent_and_generates_html_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    input_path = tmp_path / "feedback.csv"
    output_dir = tmp_path / "ask_output"
    write_csv(input_path)

    result = runner.invoke(
        app,
        [
            "ask",
            f"分析 {input_path} 输出到 {output_dir}，只用规则，生成 HTML 报告",
        ],
    )

    assert result.exit_code == 0
    assert (output_dir / "triage_results.csv").exists()
    assert (output_dir / "issue_cards.md").exists()
    assert (output_dir / "report.html").exists()
    assert "HTML report generated" in result.output


def test_ask_command_shows_clear_error_without_input_path() -> None:
    result = runner.invoke(app, ["ask", "分析评论并输出问题卡片"])

    assert result.exit_code == 1
    assert "无法识别输入文件" in result.output
    assert "traceback" not in result.output.lower()


def test_report_command_generates_html_from_existing_outputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    input_path = tmp_path / "feedback.csv"
    output_dir = tmp_path / "output"
    write_csv(input_path)
    FeedbackTriageAgent(input_path=input_path, output_dir=output_dir, llm_requested=False).run()

    result = runner.invoke(app, ["report", "--output", str(output_dir)])

    assert result.exit_code == 0
    report_path = output_dir / "report.html"
    assert report_path.exists()
    assert "Feedback Triage Agent Report" in report_path.read_text(encoding="utf-8")


def test_report_command_shows_clear_error_when_outputs_are_missing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["report", "--output", str(tmp_path / "missing")])

    assert result.exit_code == 1
    assert "请先运行 run 命令" in result.output


def test_review_apply_command_creates_reviewed_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "feedback.csv"
    output_dir = tmp_path / "output"
    write_csv(input_path)
    FeedbackTriageAgent(input_path=input_path, output_dir=output_dir, llm_requested=False).run()
    decisions_path = output_dir / "review_decisions.csv"
    decisions = pd.read_csv(decisions_path).fillna("")
    decisions.loc[0, "decision"] = "confirm"
    decisions.to_csv(decisions_path, index=False)

    result = runner.invoke(app, ["review-apply", "--output", str(output_dir)])

    assert result.exit_code == 0
    assert (output_dir / "triage_results_reviewed.csv").exists()
    assert (output_dir / "review_summary.md").exists()
    assert "Reviewed" in result.output
