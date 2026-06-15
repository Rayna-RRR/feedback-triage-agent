from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from feedback_triage_agent.rules import REQUIRED_FIELDS


COLUMN_ALIASES = {
    "id": ["id", "review_id", "reviewid", "feedback_id", "feedbackid", "comment_id", "uuid"],
    "source": ["source", "platform", "channel", "store", "market"],
    "app_name": ["app_name", "appname", "app", "product_name", "product"],
    "review_text": [
        "review_text",
        "reviewtext",
        "content",
        "review",
        "text",
        "comment",
        "feedback",
        "body",
        "message",
    ],
    "rating": ["rating", "score", "stars", "star", "rate"],
}

FILENAME_NOISE = {
    "review",
    "reviews",
    "feedback",
    "comment",
    "comments",
    "latest",
    "export",
    "data",
    "dataset",
    "csv",
}

KNOWN_APP_NAMES = {
    "chatgpt": "ChatGPT",
}


@dataclass
class NormalizationResult:
    dataframe: pd.DataFrame
    column_mapping: Dict[str, str] = field(default_factory=dict)
    defaults: Dict[str, str] = field(default_factory=dict)
    generated_ids: int = 0
    preserved_columns: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.column_mapping or self.defaults or self.generated_ids)


def normalize_column_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def infer_source(columns: List[str]) -> str:
    keys = {normalize_column_key(column) for column in columns}
    if {"reviewid", "content", "score"}.issubset(keys):
        return "google_play"
    return "unknown"


def infer_app_name(input_name: str) -> str:
    stem = Path(input_name).stem
    parts = [
        part
        for part in re.split(r"[^A-Za-z0-9]+", stem)
        if part and not part.isdigit() and part.lower() not in FILENAME_NOISE
    ]
    if not parts:
        return "unknown_app"
    normalized = "".join(parts).lower()
    if normalized in KNOWN_APP_NAMES:
        return KNOWN_APP_NAMES[normalized]
    return " ".join(parts)


def _find_source_column(columns: List[str], aliases: List[str]) -> Optional[str]:
    indexed_columns = {normalize_column_key(column): column for column in columns}
    for alias in aliases:
        match = indexed_columns.get(normalize_column_key(alias))
        if match is not None:
            return match
    return None


def _blank_mask(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def normalize_feedback_frame(dataframe: pd.DataFrame, input_name: str) -> NormalizationResult:
    source_columns = [str(column).strip() for column in dataframe.columns]
    source_frame = dataframe.copy()
    source_frame.columns = source_columns

    mapping: Dict[str, str] = {}
    selected_sources: Dict[str, str] = {}
    standard_columns: Dict[str, pd.Series] = {}
    for target in REQUIRED_FIELDS:
        source = _find_source_column(source_columns, COLUMN_ALIASES[target])
        if source is not None:
            selected_sources[target] = source
            if source != target:
                mapping[target] = source
            standard_columns[target] = source_frame[source].copy()

    missing_semantic_fields = [
        field for field in ("review_text", "rating") if field not in standard_columns
    ]
    if missing_semantic_fields:
        raise ValueError(
            "无法标准化 CSV，未识别到字段: "
            + "，".join(missing_semantic_fields)
            + "。请使用常见列名或先改名后重试。"
        )

    defaults: Dict[str, str] = {}
    generated_ids = 0
    row_count = len(source_frame)

    if "id" not in standard_columns:
        standard_columns["id"] = pd.Series(
            [f"row_{index:06d}" for index in range(1, row_count + 1)],
            index=source_frame.index,
            dtype="object",
        )
        generated_ids = row_count
        defaults["id"] = "generated row_XXXXXX"
    else:
        blank_ids = _blank_mask(standard_columns["id"])
        generated_ids = int(blank_ids.sum())
        if generated_ids:
            replacements = [
                f"row_{index + 1:06d}" if is_blank else value
                for index, (value, is_blank) in enumerate(
                    zip(standard_columns["id"], blank_ids)
                )
            ]
            standard_columns["id"] = pd.Series(replacements, index=source_frame.index)
            defaults["id"] = "generated for blank values"

    source_default = infer_source(source_columns)
    if "source" not in standard_columns:
        standard_columns["source"] = pd.Series(
            [source_default] * row_count,
            index=source_frame.index,
            dtype="object",
        )
        defaults["source"] = source_default
    else:
        blank_sources = _blank_mask(standard_columns["source"])
        if blank_sources.any():
            standard_columns["source"] = standard_columns["source"].mask(
                blank_sources, source_default
            )
            defaults["source"] = source_default

    app_default = infer_app_name(input_name)
    if "app_name" not in standard_columns:
        standard_columns["app_name"] = pd.Series(
            [app_default] * row_count,
            index=source_frame.index,
            dtype="object",
        )
        defaults["app_name"] = app_default
    else:
        blank_apps = _blank_mask(standard_columns["app_name"])
        if blank_apps.any():
            standard_columns["app_name"] = standard_columns["app_name"].mask(
                blank_apps, app_default
            )
            defaults["app_name"] = app_default

    normalized = pd.DataFrame(
        {field: standard_columns[field] for field in REQUIRED_FIELDS},
        index=source_frame.index,
    )
    consumed_columns = set(selected_sources.values())
    preserved_columns = [
        column
        for column in source_columns
        if column not in consumed_columns and column not in REQUIRED_FIELDS
    ]
    if preserved_columns:
        normalized = pd.concat([normalized, source_frame[preserved_columns]], axis=1)

    return NormalizationResult(
        dataframe=normalized,
        column_mapping=mapping,
        defaults=defaults,
        generated_ids=generated_ids,
        preserved_columns=preserved_columns,
    )
