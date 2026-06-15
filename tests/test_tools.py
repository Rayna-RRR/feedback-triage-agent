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


def test_load_feedback_normalizes_google_play_review_export(tmp_path: Path) -> None:
    csv_path = tmp_path / "chatgpt_reviews_latest_5000.csv"
    write_csv(
        csv_path,
        "reviewId,userName,content,score,thumbsUpCount\n"
        'r001,Alice,"page is slow",2,3\n',
    )
    state = AgentRunState(
        input_path=csv_path,
        input_name=csv_path.name,
        output_dir=tmp_path / "out",
        normalize_input=True,
    )

    load_result = load_feedback(state)
    validation_result = validate_schema(state)

    assert load_result.status == "success"
    assert validation_result.status == "success"
    assert state.normalization_applied is True
    assert state.normalization_column_mapping == {
        "id": "reviewId",
        "review_text": "content",
        "rating": "score",
    }
    assert state.normalization_defaults == {
        "source": "google_play",
        "app_name": "ChatGPT",
    }
    assert state.columns == [
        "id",
        "source",
        "app_name",
        "review_text",
        "rating",
        "userName",
        "thumbsUpCount",
    ]
    assert state.records[0].id == "r001"
    assert state.records[0].source == "google_play"
    assert state.records[0].app_name == "ChatGPT"
    assert (tmp_path / "out" / "normalized_feedback.csv").exists()


def test_load_feedback_normalization_rejects_unrecognized_semantic_fields(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "unknown.csv"
    write_csv(csv_path, "reviewId,userName\nr001,Alice\n")
    state = AgentRunState(
        input_path=csv_path,
        output_dir=tmp_path / "out",
        normalize_input=True,
    )

    result = load_feedback(state)

    assert result.status == "error"
    assert "review_text" in result.warnings[0]
    assert "rating" in result.warnings[0]


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
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out", llm_requested=False)
    load_feedback(state)
    validate_schema(state)
    classify_feedback(state)

    result = detect_badcases(state)

    assert result.status == "warning"
    assert state.human_review_queue == ["a001"]
    assert "P0 样本" in state.classified_feedback[0].human_review_reasons


def test_detect_badcases_does_not_queue_short_positive_feedback(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,google_play,ChatGPT,"good",5\n',
    )
    state = AgentRunState(
        input_path=csv_path,
        output_dir=tmp_path / "out",
        llm_requested=False,
    )
    load_feedback(state)
    validate_schema(state)
    classify_feedback(state)

    result = detect_badcases(state)

    assert result.status == "success"
    assert state.human_review_queue == []
    assert state.classified_feedback[0].issue_category == "正向反馈/无明确问题"


def test_classify_feedback_falls_back_to_rules_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"回答答非所问。",2\n',
    )
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out", llm_requested=True)
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
        last_usage = {
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "total_tokens": 100,
        }

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
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out", llm_requested=True)
    load_feedback(state)
    validate_schema(state)
    classify_feedback(state)

    result = detect_badcases(state)

    item = state.classified_feedback[0]
    assert item.classification_source == "llm"
    assert state.llm_used is True
    assert state.llm_total_tokens == 100
    assert result.status == "warning"
    assert "文本过短" in item.human_review_reasons
    assert "product_suggestion 为空或过泛" in item.human_review_reasons


def test_validate_schema_keeps_valid_row_when_duplicate_id_has_missing_value(tmp_path: Path) -> None:
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"",2\n'
        'a001,app_store,ChatMate,"回答不准确。",2\n',
    )
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out")
    load_feedback(state)

    result = validate_schema(state)

    assert result.status == "warning"
    assert [record.review_text for record in state.records] == ["回答不准确。"]


def test_validate_schema_reports_duplicate_valid_ids(tmp_path: Path) -> None:
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"回答不准确。",2\n'
        'a001,app_store,ChatMate,"页面卡住。",2\n',
    )
    state = AgentRunState(input_path=csv_path, output_dir=tmp_path / "out")
    load_feedback(state)

    result = validate_schema(state)

    assert result.status == "warning"
    assert state.duplicate_ids == ["a001"]
    assert len(state.records) == 2

    classify_feedback(state)
    detect_badcases(state)
    assert all("重复 ID" in item.human_review_reasons for item in state.classified_feedback)


def test_llm_rule_disagreement_is_traceable_and_requires_review(tmp_path: Path, monkeypatch) -> None:
    class FakeDeepSeekClient:
        model = "deepseek-chat"

        def draft_feedback(self, record):
            return LLMFeedbackDraft(
                issue_category="会员与商业化问题",
                summary="订阅问题",
                user_need="明确扣费",
                product_suggestion="核查扣费链路和退款说明",
            )

    monkeypatch.setattr("feedback_triage_agent.tools.DeepSeekClient", lambda: FakeDeepSeekClient())
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"回答不准确，还会编造事实。",3\n',
    )
    state = AgentRunState(
        input_path=csv_path,
        output_dir=tmp_path / "out",
        llm_requested=True,
    )
    load_feedback(state)
    validate_schema(state)
    classify_feedback(state)
    detect_badcases(state)

    item = state.classified_feedback[0]
    assert item.issue_category == "会员与商业化问题"
    assert item.rule_issue_category == "模型能力问题"
    assert item.llm_rule_disagreement is True
    assert "LLM 与规则分类不一致" in item.human_review_reasons


def test_llm_can_override_moderate_rule_without_forcing_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeDeepSeekClient:
        model = "deepseek-chat"

        def draft_feedback(self, record):
            return LLMFeedbackDraft(
                issue_category="会员与商业化问题",
                summary="用户遇到付费权益问题",
                user_need="确认付费权益和使用限制",
                product_suggestion="核查付费权益展示和限制说明，减少误解。",
            )

    monkeypatch.setattr("feedback_triage_agent.tools.DeepSeekClient", lambda: FakeDeepSeekClient())
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"回答不准确。",3\n',
    )
    state = AgentRunState(
        input_path=csv_path,
        output_dir=tmp_path / "out",
        llm_requested=True,
    )
    load_feedback(state)
    validate_schema(state)
    classify_feedback(state)
    detect_badcases(state)

    item = state.classified_feedback[0]
    assert item.rule_issue_category == "模型能力问题"
    assert item.rule_confidence < 0.8
    assert item.issue_category == "会员与商业化问题"
    assert item.llm_rule_disagreement is False
    assert "LLM 与规则分类不一致" not in item.human_review_reasons


def test_unclear_llm_draft_keeps_actionable_rule_classification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeDeepSeekClient:
        model = "deepseek-chat"

        def draft_feedback(self, record):
            return LLMFeedbackDraft(
                issue_category="不明确/其他",
                summary="用户反馈回答质量问题",
                user_need="需要进一步确认具体场景",
                product_suggestion="继续观察",
            )

    monkeypatch.setattr("feedback_triage_agent.tools.DeepSeekClient", lambda: FakeDeepSeekClient())
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"回答不准确。",3\n',
    )
    state = AgentRunState(
        input_path=csv_path,
        output_dir=tmp_path / "out",
        llm_requested=True,
    )
    load_feedback(state)
    validate_schema(state)
    classify_feedback(state)
    detect_badcases(state)

    item = state.classified_feedback[0]
    assert item.classification_source == "llm"
    assert item.issue_category == "模型能力问题"
    assert item.llm_rule_disagreement is False
    assert "分类低置信度" not in item.human_review_reasons
    assert "product_suggestion 为空或过泛" not in item.human_review_reasons


def test_llm_resolves_low_confidence_rule_without_forcing_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeDeepSeekClient:
        model = "deepseek-chat"
        last_usage = {
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "total_tokens": 100,
        }

        def draft_feedback(self, record):
            return LLMFeedbackDraft(
                issue_category="模型能力问题",
                summary="用户认为回答不看事实对错",
                user_need="获得基于事实的回答",
                product_suggestion="补充事实性校验样本，优化模型拒绝顺从错误前提的能力。",
            )

    monkeypatch.setattr("feedback_triage_agent.tools.DeepSeekClient", lambda: FakeDeepSeekClient())
    csv_path = tmp_path / "feedback.csv"
    write_csv(
        csv_path,
        "id,source,app_name,review_text,rating\n"
        'a001,app_store,ChatMate,"这个输出完全不像我要的方向，整体体验让我很困惑。",2\n',
    )
    state = AgentRunState(
        input_path=csv_path,
        output_dir=tmp_path / "out",
        llm_requested=True,
    )
    load_feedback(state)
    validate_schema(state)
    classify_feedback(state)
    detect_badcases(state)

    item = state.classified_feedback[0]
    assert item.rule_issue_category == "不明确/其他"
    assert item.issue_category == "模型能力问题"
    assert item.llm_rule_disagreement is False
    assert item.confidence >= 0.6
    assert "分类低置信度" not in item.human_review_reasons
    assert "LLM 与规则分类不一致" not in item.human_review_reasons
