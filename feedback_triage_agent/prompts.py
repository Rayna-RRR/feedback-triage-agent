from __future__ import annotations

import json

from feedback_triage_agent.models import FeedbackRecord
from feedback_triage_agent.rules import ISSUE_CATEGORIES


SYSTEM_PROMPT = """你是 AI 产品反馈分诊助手。
你的任务是为单条用户反馈生成结构化初稿，只能基于用户原话判断。
不要判断 priority，不要判断是否需要人工复核，不要编造不存在的上下文。
输出必须是合法 JSON，不要输出 Markdown。
"""


def build_feedback_triage_prompt(record: FeedbackRecord) -> str:
    payload = {
        "allowed_issue_categories": ISSUE_CATEGORIES,
        "feedback": {
            "id": record.id,
            "source": record.source,
            "app_name": record.app_name,
            "review_text": record.review_text,
            "rating": record.rating,
        },
        "output_schema": {
            "issue_category": "必须从 allowed_issue_categories 中选择一个",
            "summary": "用中文概括用户原话，保留关键风险和场景",
            "user_need": "提炼用户真实需求",
            "product_suggestion": "给出面向产品团队的初步建议",
        },
        "constraints": [
            "不要输出 priority",
            "不要输出人工复核结论",
            "不确定时 issue_category 使用 不明确/其他",
            "product_suggestion 需要具体，不能只写 优化体验 或 继续观察",
        ],
    }
    return json.dumps(payload, ensure_ascii=False)

