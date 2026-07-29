from typing import Optional

import pytest
from pydantic import ValidationError

from feedback_triage_agent.models import FeedbackRecord
from feedback_triage_agent.rules import (
    REQUIRED_FIELDS,
    classify_feedback_record,
    detect_human_review_reasons,
)


def make_record(text: str, rating: Optional[int] = 3) -> FeedbackRecord:
    return FeedbackRecord(
        id="t001",
        source="test",
        app_name="ChatMate",
        review_text=text,
        rating=rating,
    )


def test_rating_can_be_omitted_without_changing_legacy_csv_contract() -> None:
    record = FeedbackRecord(
        id="t001",
        source="test",
        app_name="ChatMate",
        review_text="页面经常卡住。",
    )

    assert record.rating is None
    assert "rating" in REQUIRED_FIELDS


@pytest.mark.parametrize("rating", [0, 6, 2.5])
def test_non_empty_rating_still_requires_an_integer_from_one_to_five(
    rating: float,
) -> None:
    with pytest.raises(ValidationError):
        make_record("页面经常卡住。", rating)  # type: ignore[arg-type]


def test_missing_rating_uses_text_only_for_priority_and_positive_feedback() -> None:
    p0_result = classify_feedback_record(make_record("生成到一半闪退，草稿内容丢失。", None))
    p1_result = classify_feedback_record(make_record("回答不准确，结果完全不可用。", None))
    positive_result = classify_feedback_record(make_record("很好用，真的很喜欢。", None))

    assert p0_result.priority == "P0"
    assert p1_result.priority == "P1"
    assert positive_result.priority == "P2"
    assert positive_result.issue_category == "正向反馈/无明确问题"
    assert p0_result.rating is None


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


@pytest.mark.parametrize(
    ("text", "expected_category"),
    [
        ("It keeps giving the wrong answer and makes up facts.", "模型能力问题"),
        ("It gives wrong information and ignores instructions.", "模型能力问题"),
        (
            "The interface is confusing and I cannot find the history button.",
            "交互体验问题",
        ),
        ("The app keeps crashing and freezing.", "性能与稳定性问题"),
        ("The app hangs and keeps asking me to try again.", "性能与稳定性问题"),
        (
            "The subscription is too expensive and the image limit is frustrating.",
            "会员与商业化问题",
        ),
        ("The free version has too many limits and asks me to upgrade.", "会员与商业化问题"),
        ("This AI is promoting war and harmful content.", "内容安全与合规问题"),
        ("I cannot log in and my chat history is gone.", "账号、隐私与数据问题"),
        ("Sign up fails and the app shares data.", "账号、隐私与数据问题"),
        ("Please add a permanent memory feature for work.", "用户预期与产品定位问题"),
    ],
)
def test_classifies_common_english_feedback(
    text: str,
    expected_category: str,
) -> None:
    result = classify_feedback_record(make_record(text, 2))

    assert result.issue_category == expected_category
    assert result.confidence >= 0.6


def test_english_negation_does_not_create_false_issue_or_priority() -> None:
    result = classify_feedback_record(
        make_record("The app never crashes, is not slow, and I was not charged.", 5)
    )

    assert result.issue_category == "不明确/其他"
    assert result.priority == "P2"


def test_whenever_does_not_negate_a_real_crash() -> None:
    result = classify_feedback_record(
        make_record("Whenever it crashes, I lose the response.", 2)
    )

    assert result.issue_category == "性能与稳定性问题"
    assert result.priority == "P0"


def test_short_positive_feedback_does_not_enter_human_review() -> None:
    result = classify_feedback_record(make_record("good app", 5))
    reasons = detect_human_review_reasons(result)

    assert result.issue_category == "正向反馈/无明确问题"
    assert result.confidence >= 0.6
    assert reasons == []


def test_positive_prefix_does_not_hide_an_actionable_problem() -> None:
    result = classify_feedback_record(
        make_record("Good app, but it keeps crashing.", 5)
    )
    reasons = detect_human_review_reasons(result)

    assert result.issue_category == "性能与稳定性问题"
    assert result.priority == "P0"
    assert "P0 样本" in reasons


def test_low_rating_praise_stays_uncertain() -> None:
    result = classify_feedback_record(make_record("good", 1))
    reasons = detect_human_review_reasons(result)

    assert result.issue_category == "不明确/其他"
    assert "分类低置信度" in reasons


@pytest.mark.parametrize(
    ("text", "expected_category"),
    [
        ("这破 AI 天天瞎编骗人，事实对错完全不管。", "模型能力问题"),
        ("语音识别没一句对，很多字都识别错误。", "模型能力问题"),
        ("今天一直转圈没反应，还提示算力不足。", "性能与稳定性问题"),
        ("聊了一会儿消息数量就被限制，对话也被限制。", "会员与商业化问题"),
        ("希望官方能增加关闭数据反馈的功能。", "用户预期与产品定位问题"),
    ],
)
def test_classifies_common_chinese_feedback(
    text: str,
    expected_category: str,
) -> None:
    result = classify_feedback_record(make_record(text, 2))

    assert result.issue_category == expected_category
    assert result.confidence >= 0.6


def test_chinese_positive_feedback_does_not_enter_human_review() -> None:
    result = classify_feedback_record(
        make_record("很聪明哦，而且很会提供情绪价值，超赞。", 5)
    )
    reasons = detect_human_review_reasons(result)

    assert result.issue_category == "正向反馈/无明确问题"
    assert reasons == []
