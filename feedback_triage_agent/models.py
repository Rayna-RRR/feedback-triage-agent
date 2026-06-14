from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


IssueCategory = Literal[
    "模型能力问题",
    "交互体验问题",
    "性能与稳定性问题",
    "会员与商业化问题",
    "内容安全与合规问题",
    "账号、隐私与数据问题",
    "用户预期与产品定位问题",
    "不明确/其他",
]

Priority = Literal["P0", "P1", "P2"]
ToolStatus = Literal["success", "warning", "error"]
ClassificationSource = Literal["rules", "llm", "llm_fallback"]


class FeedbackRecord(BaseModel):
    """A validated user feedback row."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    app_name: str = Field(min_length=1)
    review_text: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)

    @field_validator("id", "source", "app_name", "review_text", mode="before")
    @classmethod
    def normalize_text_field(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("rating", mode="before")
    @classmethod
    def normalize_rating(cls, value: Any) -> int:
        if value is None or str(value).strip() == "":
            raise ValueError("rating is required")
        return int(float(value))


class ClassifiedFeedback(BaseModel):
    """A feedback row after triage."""

    id: str
    record_key: str
    source: str
    app_name: str
    review_text: str
    rating: int
    issue_category: IssueCategory
    rule_issue_category: IssueCategory
    priority: Priority
    confidence: float = Field(ge=0, le=1)
    rule_confidence: float = Field(ge=0, le=1)
    matched_categories: List[str] = Field(default_factory=list)
    matched_keywords: Dict[str, List[str]] = Field(default_factory=dict)
    summary: str
    user_need: str
    product_suggestion: str
    needs_human_review: bool = False
    human_review_reasons: List[str] = Field(default_factory=list)
    classification_source: ClassificationSource = "rules"
    llm_rule_disagreement: bool = False
    llm_error: Optional[str] = None


class LLMFeedbackDraft(BaseModel):
    """LLM-generated first draft. Rules still perform QA and review detection."""

    issue_category: IssueCategory
    summary: str = Field(min_length=1)
    user_need: str = Field(min_length=1)
    product_suggestion: str = Field(min_length=1)


class IssueCard(BaseModel):
    """A markdown-ready issue card."""

    title: str
    representative_id: str
    user_summary: str
    issue_category: IssueCategory
    priority: Priority
    user_need: str
    product_suggestion: str
    human_review_reasons: List[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    """Structured result returned by every agent tool."""

    step_name: str
    status: ToolStatus
    input_summary: str
    output_summary: str
    warnings: List[str] = Field(default_factory=list)
    next_action: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class RunStepLog(BaseModel):
    """Compact run log entry derived from a tool result."""

    step_name: str
    status: ToolStatus
    input_summary: str
    output_summary: str
    warnings: List[str] = Field(default_factory=list)
    next_action: str

    @classmethod
    def from_tool_result(cls, result: ToolResult) -> "RunStepLog":
        return cls(
            step_name=result.step_name,
            status=result.status,
            input_summary=result.input_summary,
            output_summary=result.output_summary,
            warnings=result.warnings,
            next_action=result.next_action,
        )


class AgentRunState(BaseModel):
    """State shared across tools during one fixed-plan agent run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    input_path: Path
    output_dir: Path
    required_fields: List[str] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    raw_records: List[Dict[str, Any]] = Field(default_factory=list)
    records: List[FeedbackRecord] = Field(default_factory=list)
    classified_feedback: List[ClassifiedFeedback] = Field(default_factory=list)
    issue_cards: List[IssueCard] = Field(default_factory=list)
    missing_columns: List[str] = Field(default_factory=list)
    missing_values: Dict[str, List[str]] = Field(default_factory=dict)
    invalid_records: List[str] = Field(default_factory=list)
    duplicate_ids: List[str] = Field(default_factory=list)
    human_review_queue: List[str] = Field(default_factory=list)
    qa_summary: Dict[str, Any] = Field(default_factory=dict)
    run_log: List[RunStepLog] = Field(default_factory=list)
    output_paths: Dict[str, Path] = Field(default_factory=dict)
    llm_requested: bool = False
    llm_available: bool = False
    llm_used: bool = False
    llm_provider: str = "deepseek"
    llm_model: str = ""
    llm_attempted_count: int = 0
    llm_success_count: int = 0
    llm_failed_count: int = 0
    llm_fallback_used: bool = False
    llm_fallback_reasons: List[str] = Field(default_factory=list)
