from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from feedback_triage_agent.agent import FeedbackTriageAgent
from feedback_triage_agent.cli import app, infer_input_path
from feedback_triage_agent.llm_client import LLMCallError
from feedback_triage_agent.models import LLMTaskIntent
from feedback_triage_agent.task_parser import (
    infer_output_dir,
    parse_ask_task,
    should_normalize_input,
)


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


def test_ask_command_detects_format_normalization_intent() -> None:
    assert should_normalize_input("把 CSV 转换为符合格式并输出") is True
    assert should_normalize_input("只用规则，生成 HTML 报告") is False


def test_ask_task_uses_deepseek_for_structured_intent_and_keeps_rule_safeguards(
    monkeypatch,
) -> None:
    class FakeDeepSeekClient:
        model = "deepseek-v4-pro"
        last_usage = {
            "prompt_tokens": 90,
            "completion_tokens": 30,
            "total_tokens": 120,
        }

        def parse_task(self, task: str, uploaded_filename: str = "") -> LLMTaskIntent:
            return LLMTaskIntent(
                input_path="data/from-model.csv",
                output_dir="data/model-output",
                use_llm_for_triage=True,
                generate_html_report=True,
                normalize_input=False,
            )

    monkeypatch.setattr(
        "feedback_triage_agent.task_parser.DeepSeekClient", FakeDeepSeekClient
    )

    parsed = parse_ask_task("请把格式不符合的数据整理好，只用规则")

    assert parsed.parser_source == "deepseek"
    assert parsed.parser_model == "deepseek-v4-pro"
    assert parsed.parser_total_tokens == 120
    assert parsed.input_path == Path("data/from-model.csv")
    assert parsed.output_dir == Path("data/model-output")
    assert parsed.llm_requested is False
    assert parsed.html_requested is True
    assert parsed.normalize_input is True


def test_ask_task_can_force_original_rule_parser(monkeypatch) -> None:
    class UnexpectedDeepSeekClient:
        def __init__(self):
            raise AssertionError("DeepSeek should not be called")

    monkeypatch.setattr(
        "feedback_triage_agent.task_parser.DeepSeekClient",
        UnexpectedDeepSeekClient,
    )

    parsed = parse_ask_task(
        "分析 data/ai_app_reviews.csv，只用规则，生成 HTML 报告",
        use_deepseek=False,
    )

    assert parsed.parser_source == "rules"
    assert parsed.input_path == Path("data/ai_app_reviews.csv")
    assert parsed.html_requested is True
    assert parsed.llm_requested is False


def test_ask_task_falls_back_to_rules_when_deepseek_fails(monkeypatch) -> None:
    class FailingDeepSeekClient:
        model = "deepseek-chat"

        def parse_task(self, task: str, uploaded_filename: str = "") -> LLMTaskIntent:
            raise LLMCallError("temporary failure")

    monkeypatch.setattr(
        "feedback_triage_agent.task_parser.DeepSeekClient",
        FailingDeepSeekClient,
    )

    parsed = parse_ask_task(
        "分析 data/ai_app_reviews.csv，只用规则，生成 HTML 报告"
    )

    assert parsed.parser_source == "rules"
    assert parsed.parser_fallback_reason == "temporary failure"
    assert parsed.input_path == Path("data/ai_app_reviews.csv")
    assert parsed.html_requested is True


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


def test_ask_command_uses_deepseek_task_parser(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "feedback.csv"
    output_dir = tmp_path / "model_output"
    write_csv(input_path)

    class FakeDeepSeekClient:
        model = "deepseek-chat"

        def parse_task(self, task: str, uploaded_filename: str = "") -> LLMTaskIntent:
            return LLMTaskIntent(
                input_path=str(input_path),
                output_dir=str(output_dir),
                use_llm_for_triage=False,
                generate_html_report=False,
                normalize_input=False,
            )

    monkeypatch.setattr(
        "feedback_triage_agent.task_parser.DeepSeekClient", FakeDeepSeekClient
    )

    result = runner.invoke(app, ["ask", "把这批反馈按我们刚才说的方式处理"])

    assert result.exit_code == 0
    assert "task_parser=deepseek" in result.output
    assert (output_dir / "triage_results.csv").exists()
    qa_report = (output_dir / "qa_report.md").read_text(encoding="utf-8")
    assert "解析来源: deepseek" in qa_report


def test_ask_command_normalizes_nonstandard_csv_and_runs_agent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    input_path = tmp_path / "chatgpt_reviews_latest_5000.csv"
    input_path.write_text(
        "reviewId,userName,content,score\n"
        'r001,Alice,"page is slow",2\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "normalized_output"

    result = runner.invoke(
        app,
        [
            "ask",
            f"分析 {input_path} 输出到 {output_dir}，转换为符合格式，只用规则",
        ],
    )

    assert result.exit_code == 0
    normalized = pd.read_csv(output_dir / "normalized_feedback.csv").fillna("")
    assert normalized.loc[0, "id"] == "r001"
    assert normalized.loc[0, "source"] == "google_play"
    assert normalized.loc[0, "app_name"] == "ChatGPT"
    assert normalized.loc[0, "review_text"] == "page is slow"
    assert normalized.loc[0, "rating"] == 2
    assert (output_dir / "triage_results.csv").exists()
    assert "normalize_input=True" in result.output


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
