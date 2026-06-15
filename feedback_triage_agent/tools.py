from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import ValidationError

from feedback_triage_agent.exporters import write_outputs
from feedback_triage_agent.llm_client import DeepSeekClient, LLMCallError, LLMUnavailableError
from feedback_triage_agent.models import AgentRunState, FeedbackRecord, IssueCard, RunStepLog, ToolResult
from feedback_triage_agent.normalization import normalize_feedback_frame
from feedback_triage_agent.rules import (
    REQUIRED_FIELDS,
    build_issue_title,
    classify_feedback_record,
    detect_human_review_reasons,
    distribution,
)


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return str(value).strip() == ""


def row_label(row: Dict[str, Any], index: int) -> str:
    row_id = row.get("id")
    return str(row_id).strip() if not is_blank(row_id) else f"row_{index + 2}"


def load_feedback(state: AgentRunState) -> ToolResult:
    input_path = Path(state.input_path)
    if not input_path.exists():
        return ToolResult(
            step_name="load_feedback",
            status="error",
            input_summary=f"path={input_path}",
            output_summary="input file not found",
            warnings=[f"找不到输入文件: {input_path}"],
            next_action="stop",
        )

    try:
        dataframe = pd.read_csv(input_path)
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        return ToolResult(
            step_name="load_feedback",
            status="error",
            input_summary=f"path={input_path}",
            output_summary="input CSV could not be read",
            warnings=[f"CSV 读取失败: {exc}"],
            next_action="stop",
        )

    normalization_summary = ""
    if state.normalize_input:
        try:
            result = normalize_feedback_frame(dataframe, state.input_name or input_path.name)
        except ValueError as exc:
            return ToolResult(
                step_name="load_feedback",
                status="error",
                input_summary=f"path={input_path}, normalize_input=True",
                output_summary="input CSV could not be normalized",
                warnings=[str(exc)],
                next_action="stop",
            )
        dataframe = result.dataframe
        state.output_dir.mkdir(parents=True, exist_ok=True)
        state.normalized_input_path = state.output_dir / "normalized_feedback.csv"
        dataframe.to_csv(state.normalized_input_path, index=False)
        state.normalization_applied = result.changed
        state.normalization_column_mapping = result.column_mapping
        state.normalization_defaults = result.defaults
        normalization_summary = (
            f", normalized=True, mappings={result.column_mapping}, "
            f"defaults={result.defaults}, preserved={result.preserved_columns}"
        )

    state.columns = [str(column) for column in dataframe.columns]
    state.raw_records = dataframe.to_dict("records")

    warnings = []
    if dataframe.empty:
        warnings.append("CSV 文件为空")

    return ToolResult(
        step_name="load_feedback",
        status="warning" if warnings else "success",
        input_summary=f"path={input_path}, ask_parser={state.ask_parser_source}",
        output_summary=(
            f"loaded {len(state.raw_records)} rows, {len(state.columns)} columns"
            f"{normalization_summary}"
        ),
        warnings=warnings,
        next_action="validate_schema",
        payload={
            "columns": state.columns,
            "row_count": len(state.raw_records),
            "normalization_applied": state.normalization_applied,
            "normalization_column_mapping": state.normalization_column_mapping,
            "normalization_defaults": state.normalization_defaults,
        },
    )


def validate_schema(state: AgentRunState) -> ToolResult:
    state.required_fields = REQUIRED_FIELDS.copy()
    state.missing_columns = [field for field in REQUIRED_FIELDS if field not in state.columns]
    state.missing_values = {}
    state.invalid_records = []
    state.duplicate_ids = []
    state.records = []

    if not state.missing_columns:
        missing_row_indexes = set()
        for field in REQUIRED_FIELDS:
            missing_ids = []
            for index, row in enumerate(state.raw_records):
                if is_blank(row.get(field)):
                    missing_row_indexes.add(index)
                    missing_ids.append(row_label(row, index))
            if missing_ids:
                state.missing_values[field] = missing_ids

        for index, row in enumerate(state.raw_records):
            current_id = row_label(row, index)
            if index in missing_row_indexes:
                continue
            try:
                state.records.append(FeedbackRecord.model_validate(row))
            except ValidationError as exc:
                state.invalid_records.append(f"{current_id}: {exc.errors()[0]['msg']}")

        id_counts = Counter(record.id for record in state.records)
        state.duplicate_ids = sorted(record_id for record_id, count in id_counts.items() if count > 1)

    warnings = []
    if state.missing_columns:
        warnings.append(f"缺失字段: {', '.join(state.missing_columns)}")
    if state.missing_values:
        warnings.append("存在必填字段空值")
    if state.invalid_records:
        warnings.append("存在无法通过 pydantic 校验的样本")
    if state.duplicate_ids:
        warnings.append("存在重复 id，后续结果需按行核对")

    return ToolResult(
        step_name="validate_schema",
        status="warning" if warnings else "success",
        input_summary=f"required_fields={', '.join(REQUIRED_FIELDS)}",
        output_summary=f"valid_records={len(state.records)}, missing_columns={len(state.missing_columns)}",
        warnings=warnings,
        next_action="classify_feedback",
        payload={
            "missing_columns": state.missing_columns,
            "missing_values": state.missing_values,
            "invalid_records": state.invalid_records,
            "duplicate_ids": state.duplicate_ids,
        },
    )


def classify_feedback(state: AgentRunState) -> ToolResult:
    warnings: List[str] = []
    fallback_reasons: List[str] = []
    llm_client: Optional[DeepSeekClient] = None

    if state.llm_requested:
        try:
            llm_client = DeepSeekClient()
            state.llm_available = True
            state.llm_model = llm_client.model
        except (LLMUnavailableError, ValueError) as exc:
            state.llm_available = False
            state.llm_fallback_used = True
            fallback_reasons.append(str(exc))
    else:
        fallback_reasons.append("LLM disabled by runner option")

    classified = []
    disable_llm_after_failure = False
    for index, record in enumerate(state.records, start=1):
        item = classify_feedback_record(record)
        item.record_key = f"{record.id}::{index}"
        if llm_client is None or disable_llm_after_failure:
            if disable_llm_after_failure:
                item.classification_source = "llm_fallback"
                item.llm_error = "DeepSeek 调用失败后，本轮剩余样本直接使用 rules.py"
            classified.append(item)
            continue

        state.llm_attempted_count += 1
        try:
            draft = llm_client.draft_feedback(record)
        except LLMCallError as exc:
            state.llm_failed_count += 1
            state.llm_fallback_used = True
            item.classification_source = "llm_fallback"
            item.llm_error = str(exc)
            fallback_reasons.append(f"{record.id}: {exc}")
            disable_llm_after_failure = True
        else:
            state.llm_used = True
            state.llm_success_count += 1
            item.issue_category = draft.issue_category
            item.llm_rule_disagreement = draft.issue_category != item.rule_issue_category
            item.summary = draft.summary
            item.user_need = draft.user_need
            item.product_suggestion = draft.product_suggestion
            item.classification_source = "llm"
        classified.append(item)

    state.classified_feedback = classified
    state.llm_fallback_reasons = fallback_reasons
    category_distribution = distribution([item.issue_category for item in state.classified_feedback])
    if state.llm_fallback_used:
        warnings.append("LLM 不可用或调用失败，已 fallback 到 rules.py")

    return ToolResult(
        step_name="classify_feedback",
        status="warning" if warnings else "success",
        input_summary=f"records={len(state.records)}, llm_requested={state.llm_requested}",
        output_summary=(
            f"classified={len(state.classified_feedback)}, llm_used={state.llm_used}, "
            f"llm_attempted={state.llm_attempted_count}, llm_success={state.llm_success_count}, "
            f"llm_failed={state.llm_failed_count}, fallback={state.llm_fallback_used}, "
            f"categories={category_distribution}"
        ),
        warnings=warnings,
        next_action="detect_badcases",
        payload={
            "category_distribution": category_distribution,
            "llm_used": state.llm_used,
            "llm_model": state.llm_model,
            "llm_fallback_used": state.llm_fallback_used,
            "llm_fallback_reasons": state.llm_fallback_reasons,
        },
    )


def detect_badcases(state: AgentRunState) -> ToolResult:
    review_queue: List[str] = []
    reason_counter = Counter()

    for item in state.classified_feedback:
        reasons = detect_human_review_reasons(item)
        if item.id in state.duplicate_ids:
            reasons.append("重复 ID")
        item.human_review_reasons = reasons
        item.needs_human_review = bool(reasons)
        if item.needs_human_review:
            review_queue.append(item.id)
            reason_counter.update(reasons)

    state.human_review_queue = review_queue

    return ToolResult(
        step_name="detect_badcases",
        status="warning" if review_queue else "success",
        input_summary=f"classified={len(state.classified_feedback)}",
        output_summary=f"human_review_queue={len(review_queue)}, reasons={dict(reason_counter)}",
        warnings=["存在需要人工复核的样本"] if review_queue else [],
        next_action="generate_issue_cards",
        payload={"human_review_queue": review_queue, "reason_distribution": dict(reason_counter)},
    )


def generate_issue_cards(state: AgentRunState) -> ToolResult:
    cards: List[IssueCard] = []
    for item in state.classified_feedback:
        cards.append(
            IssueCard(
                title=build_issue_title(item.priority, item.issue_category, item.summary),
                representative_id=item.id,
                user_summary=item.summary,
                issue_category=item.issue_category,
                priority=item.priority,
                user_need=item.user_need,
                product_suggestion=item.product_suggestion,
                human_review_reasons=item.human_review_reasons,
            )
        )
    state.issue_cards = cards

    return ToolResult(
        step_name="generate_issue_cards",
        status="success",
        input_summary=f"classified={len(state.classified_feedback)}",
        output_summary=f"issue_cards={len(cards)}",
        next_action="qa_check",
        payload={"issue_card_count": len(cards)},
    )


def qa_check(state: AgentRunState) -> ToolResult:
    category_distribution = distribution([item.issue_category for item in state.classified_feedback])
    priority_distribution = distribution([item.priority for item in state.classified_feedback])
    state.qa_summary = {
        "total_samples": len(state.raw_records),
        "valid_samples": len(state.records),
        "llm_used": state.llm_used,
        "llm_model": state.llm_model,
        "llm_fallback_used": state.llm_fallback_used,
        "llm_fallback_reasons": state.llm_fallback_reasons,
        "missing_columns": state.missing_columns,
        "missing_values": state.missing_values,
        "invalid_records": state.invalid_records,
        "duplicate_ids": state.duplicate_ids,
        "category_distribution": category_distribution,
        "priority_distribution": priority_distribution,
        "human_review_ids": state.human_review_queue,
        "human_review_count": len(state.human_review_queue),
        "llm_rule_disagreement_ids": [
            item.id for item in state.classified_feedback if item.llm_rule_disagreement
        ],
        "normalization_requested": state.normalize_input,
        "normalization_applied": state.normalization_applied,
        "normalization_column_mapping": state.normalization_column_mapping,
        "normalization_defaults": state.normalization_defaults,
        "normalized_input_path": (
            str(state.normalized_input_path) if state.normalized_input_path else ""
        ),
        "ask_parser_source": state.ask_parser_source,
        "ask_parser_model": state.ask_parser_model,
        "ask_parser_fallback_reason": state.ask_parser_fallback_reason,
    }

    warnings = []
    if state.missing_columns or state.missing_values or state.invalid_records or state.duplicate_ids:
        warnings.append("schema 或字段值存在 QA 风险")
    if state.human_review_queue:
        warnings.append("存在人工复核队列")

    return ToolResult(
        step_name="qa_check",
        status="warning" if warnings else "success",
        input_summary=f"cards={len(state.issue_cards)}, classified={len(state.classified_feedback)}",
        output_summary=(
            f"total={state.qa_summary['total_samples']}, "
            f"review={state.qa_summary['human_review_count']}"
        ),
        warnings=warnings,
        next_action="export_report",
        payload=state.qa_summary,
    )


def export_report(state: AgentRunState) -> ToolResult:
    exported_files = [
        "issue_cards.md",
        "qa_report.md",
        "run_log.md",
        "triage_results.csv",
        "review_decisions.csv",
    ]
    if state.normalized_input_path:
        exported_files.insert(0, "normalized_feedback.csv")
    result = ToolResult(
        step_name="export_report",
        status="success",
        input_summary=f"output_dir={state.output_dir}",
        output_summary="exported " + ", ".join(exported_files),
        next_action="done",
    )
    final_logs = state.run_log + [RunStepLog.from_tool_result(result)]
    output_paths = write_outputs(state, final_logs)
    state.output_paths = output_paths
    result.payload = {key: str(value) for key, value in output_paths.items()}
    return result
