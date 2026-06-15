from __future__ import annotations

import json

from feedback_triage_agent.models import FeedbackRecord
from feedback_triage_agent.rules import ISSUE_CATEGORIES


SYSTEM_PROMPT = """你是 AI 产品反馈分诊助手。
你的任务是为单条用户反馈生成结构化初稿，只能基于用户原话判断。
不要判断 priority，不要判断是否需要人工复核，不要编造不存在的上下文。
输出必须是合法 JSON，不要输出 Markdown。
"""

TASK_PARSER_SYSTEM_PROMPT = """你是 Feedback Triage Agent 的任务解析器。
你只负责把用户的自然语言任务转换为受约束的执行参数，不执行文件操作，不读取 CSV 内容。
输出必须是合法 JSON，不要输出 Markdown，不要添加 output_schema 之外的字段。
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


def build_task_parser_prompt(task: str, uploaded_filename: str = "") -> str:
    payload = {
        "task": task,
        "uploaded_filename": uploaded_filename or None,
        "output_schema": {
            "input_path": "任务中的 CSV 本地路径；已上传文件或未提及时返回 null",
            "output_dir": "任务明确指定的输出目录；未提及时返回 null",
            "use_llm_for_triage": "只有用户要求用 LLM 或 DeepSeek 分析反馈内容时才为 true",
            "generate_html_report": "用户要求 HTML、网页或静态报告时为 true",
            "normalize_input": "用户要求转换、调整、修正或标准化 CSV 格式时为 true",
        },
        "constraints": [
            "只用规则、不要用 LLM、不使用 DeepSeek 表示 use_llm_for_triage=false",
            "不要因为你本身是 LLM 解析器就把 use_llm_for_triage 设为 true",
            "路径必须原样保留，不要编造不存在的路径",
            "不确定的布尔值使用 false",
            "已上传文件时 input_path 使用 null",
        ],
    }
    return json.dumps(payload, ensure_ascii=False)
