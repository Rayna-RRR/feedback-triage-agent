from feedback_triage_agent.models import FeedbackRecord
from feedback_triage_agent.rules import classify_feedback_record, detect_human_review_reasons


def make_record(text: str, rating: int = 3) -> FeedbackRecord:
    return FeedbackRecord(
        id="t001",
        source="test",
        app_name="ChatMate",
        review_text=text,
        rating=rating,
    )


def test_classifies_model_capability_issue() -> None:
    result = classify_feedback_record(make_record("回答答非所问，还会编造不存在的资料。", 2))

    assert result.issue_category == "模型能力问题"
    assert "模型能力问题" in result.matched_categories
    assert result.priority == "P1"


def test_detects_p0_priority_for_crash_and_data_loss() -> None:
    result = classify_feedback_record(make_record("生成到一半闪退，草稿内容丢失。", 1))
    reasons = detect_human_review_reasons(result)

    assert result.priority == "P0"
    assert "P0 样本" in reasons


def test_detects_p2_for_lightweight_suggestion() -> None:
    result = classify_feedback_record(make_record("挺好用，建议增加夜间模式。", 5))

    assert result.priority == "P2"
    assert result.issue_category == "交互体验问题"


def test_marks_multiple_issue_types_for_review() -> None:
    result = classify_feedback_record(make_record("回答不准确，而且页面经常卡住，复制按钮也失灵。", 2))
    reasons = detect_human_review_reasons(result)

    assert "模型能力问题" in result.matched_categories
    assert "性能与稳定性问题" in result.matched_categories
    assert "交互体验问题" in result.matched_categories
    assert "同时命中多个问题类型" in reasons


def test_low_confidence_when_no_keywords_match() -> None:
    result = classify_feedback_record(make_record("还行", 4))
    reasons = detect_human_review_reasons(result)

    assert result.issue_category == "不明确/其他"
    assert result.confidence < 0.6
    assert "分类低置信度" in reasons


def test_negated_or_resolved_risk_phrases_do_not_escalate_priority() -> None:
    stable = classify_feedback_record(make_record("从来没有崩溃，运行很稳定。", 5))
    refunded = classify_feedback_record(make_record("退款很快，客服处理得很好。", 5))
    responsive = classify_feedback_record(make_record("页面不卡，速度很快。", 5))

    assert stable.priority == "P2"
    assert refunded.priority == "P2"
    assert responsive.priority == "P2"


def test_positive_or_negated_context_does_not_create_false_issue_hits() -> None:
    loading = classify_feedback_record(make_record("页面不卡，加载也不慢，整体速度正常。", 5))
    payment = classify_feedback_record(make_record("没有扣费，也没有发生支付失败。", 5))

    assert loading.issue_category == "不明确/其他"
    assert payment.issue_category == "不明确/其他"
    assert payment.priority == "P2"


def test_domain_specific_category_wins_generic_failure_tie() -> None:
    payment = classify_feedback_record(make_record("支付失败还被重复扣费，我要投诉。", 1))
    mixed = classify_feedback_record(make_record("回答不准确而且页面经常卡住。", 2))

    assert payment.issue_category == "会员与商业化问题"
    assert mixed.issue_category == "模型能力问题"
