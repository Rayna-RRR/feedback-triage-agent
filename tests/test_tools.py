from pathlib import Path

from feedback_triage_agent.models import AgentRunState
from feedback_triage_agent.models import LLMFeedbackDraft
from feedback_triage_agent.tools import (
    classify_feedback,
    detect_badcases,
    load_feedback,
    validate_schema,
)


def write_csv(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_load_feedback_reads_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"回答不准确。",2\n',
    )
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out", llm_requested=False)

    result = load_feedback(state)

    assert result.status == "success"
    assert len(state.raw_records) == 1
    assert state.columns == ["id", "source", "app_name", "review_text", "rating"]


def test_validate_schema_reports_missing_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "feedback.csv"
    write_csv(csv_path, "id,source,app_name,review_text\n" 'a001,app_store,ChatMate,"回答不准确。"\n')
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out", llm_requested=False)
    load_feedback(state)

    result = validate_schema(state)

    assert result.status == "warning"
    assert state.missing_columns == ["rating"]
    assert state.records == []


def test_validate_schema_reports_missing_values(tmp_path: Path) -> None:
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"",2\n',
    )
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out", llm_requested=False)
    load_feedback(state)

    result = validate_schema(state)

    assert result.status == "warning"
    assert state.missing_values == {"review_text": ["a001"]}
    assert state.records == []


def test_detect_badcases_builds_human_review_queue(tmp_path: Path) -> None:
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"闪退后内容丢失，想投诉。",1\n',
    )
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out")
    load_feedback(state)
    validate_schema(state)
    classify_feedback(state)

    result = detect_badcases(state)

    assert result.status == "warning"
    assert state.human_review_queue == ["a001"]
    assert "P0 样本" in state.classified_feedback[0].human_review_reasons


def test_classify_feedback_falls_back_to_rules_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"回答答非所问。",2\n',
    )
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out")
    load_feedback(state)
    validate_schema(state)

    result = classify_feedback(state)

    assert result.status == "warning"
    assert state.llm_used is False
    assert state.llm_fallback_used is True
    assert state.classified_feedback[0].classification_source == "rules"
    assert state.classified_feedback[0].issue_category == "模型能力问题"


def test_classify_feedback_uses_llm_draft_then_rules_qa(tmp_path: Path, monkeypatch) -> None:
    class FakeDeepSeekClient:
        model = "deepseek-chat"

        def draft_feedback(self, record):
            return LLMFeedbackDraft(
                issue_category="不明确/其他",
                summary="太差",
                user_need="需要明确具体问题",
                product_suggestion="继续观察",
            )

    monkeypatch.setattr("feedback_triage_agent.tools.DeepSeekClient", lambda: FakeDeepSeekClient())
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"差",1\n',
    )
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out")
    load_feedback(state)
    validate_schema(state)
    classify_feedback(state)

    result = detect_badcases(state)

    item = state.classified_feedback[0]
    assert item.classification_source == "llm"
    assert state.llm_used is True
    assert result.status == "warning"
    assert "文本过短" in item.human_review_reasons
    assert "product_suggestion 为空或过泛" in item.human_review_reasons
