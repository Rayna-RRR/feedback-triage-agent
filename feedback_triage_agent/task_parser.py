import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from feedback_triage_agent.llm_client import (
    DeepSeekClient,
    LLMCallError,
    LLMUnavailableError,
)


TASK_SEPARATOR_PATTERN = r"[，,；;\n]"


@dataclass(frozen=True)
class ParsedAskTask:
    input_path: Optional[Path]
    output_dir: Path
    llm_requested: bool
    html_requested: bool
    normalize_input: bool
    parser_source: str
    parser_model: str = ""
    parser_fallback_reason: str = ""
    parser_prompt_tokens: int = 0
    parser_completion_tokens: int = 0
    parser_total_tokens: int = 0


def _strip_task_prefix(value: str) -> str:
    cleaned = value.strip().strip("\"'“”")
    return re.sub(r"^(?:请)?(?:分析|读取|处理|分诊)\s*", "", cleaned).strip()


def infer_input_path(task: str) -> Path:
    quoted_patterns = [
        r'"([^"]+\.csv)"',
        r"'([^']+\.csv)'",
        r"“([^”]+\.csv)”",
    ]
    for pattern in quoted_patterns:
        match = re.search(pattern, task, flags=re.IGNORECASE)
        if match:
            return Path(match.group(1).strip())

    candidates = re.split(TASK_SEPARATOR_PATTERN, task)
    for candidate in candidates:
        csv_match = re.search(r"(.+?\.csv)\b", candidate, flags=re.IGNORECASE)
        if csv_match:
            path_text = _strip_task_prefix(csv_match.group(1))
            if path_text:
                return Path(path_text)
    raise ValueError("无法识别输入文件，请在任务中写明 CSV 路径，例如 data/ai_app_reviews.csv。")


def infer_output_dir(task: str) -> Path:
    match = re.search(
        rf"(?:输出到|输出目录|保存到)\s*(.+?)(?={TASK_SEPARATOR_PATTERN}|$)",
        task,
        flags=re.IGNORECASE,
    )
    if match:
        output_text = match.group(1).strip().strip("\"'“”")
        if output_text:
            return Path(output_text)
    return Path("data/output_ask")


def should_disable_llm(task: str) -> bool:
    compact = re.sub(r"\s+", "", task.lower())
    return any(
        phrase in compact
        for phrase in [
            "不要用llm",
            "不用llm",
            "不使用llm",
            "关闭llm",
            "只用规则",
            "仅用规则",
            "仅使用规则",
            "规则版",
        ]
    )


def should_enable_llm(task: str) -> bool:
    compact = re.sub(r"\s+", "", task.lower())
    return any(
        phrase in compact
        for phrase in [
            "使用llm",
            "启用llm",
            "用llm",
            "使用deepseek",
            "用deepseek",
            "启用deepseek",
        ]
    ) and not should_disable_llm(task)


def should_generate_html_report(task: str) -> bool:
    compact = re.sub(r"\s+", "", task.lower())
    return any(
        phrase in compact
        for phrase in [
            "生成html报告",
            "html报告",
            "网页报告",
            "静态html",
        ]
    )


def should_normalize_input(task: str) -> bool:
    compact = re.sub(r"\s+", "", task.lower())
    return any(
        phrase in compact
        for phrase in [
            "转换格式",
            "调整格式",
            "调换成符合",
            "改成符合",
            "整理成标准",
            "标准化csv",
            "标准格式",
            "符合格式",
            "格式不符合",
            "修正格式",
            "适配格式",
            "normalizecsv",
            "normalizethecsv",
        ]
    )


def parse_task_with_rules(task: str) -> ParsedAskTask:
    try:
        input_path: Optional[Path] = infer_input_path(task)
    except ValueError:
        input_path = None
    return ParsedAskTask(
        input_path=input_path,
        output_dir=infer_output_dir(task),
        llm_requested=should_enable_llm(task) and not should_disable_llm(task),
        html_requested=should_generate_html_report(task),
        normalize_input=should_normalize_input(task),
        parser_source="rules",
    )


def parse_ask_task(
    task: str,
    *,
    uploaded_filename: str = "",
    use_deepseek: bool = True,
) -> ParsedAskTask:
    rules = parse_task_with_rules(task)
    if not use_deepseek:
        return rules

    try:
        client = DeepSeekClient()
        intent = client.parse_task(task, uploaded_filename=uploaded_filename)
    except (LLMUnavailableError, LLMCallError, ValueError) as exc:
        return ParsedAskTask(
            input_path=rules.input_path,
            output_dir=rules.output_dir,
            llm_requested=rules.llm_requested,
            html_requested=rules.html_requested,
            normalize_input=rules.normalize_input,
            parser_source="rules",
            parser_fallback_reason=str(exc),
        )

    llm_requested = intent.use_llm_for_triage
    if should_disable_llm(task):
        llm_requested = False
    elif should_enable_llm(task):
        llm_requested = True

    input_path = rules.input_path
    if not uploaded_filename and input_path is None and intent.input_path:
        input_path = Path(intent.input_path)

    output_dir = rules.output_dir
    if output_dir == Path("data/output_ask") and intent.output_dir:
        output_dir = Path(intent.output_dir)

    usage = getattr(client, "last_usage", {})
    return ParsedAskTask(
        input_path=input_path,
        output_dir=output_dir,
        llm_requested=llm_requested,
        html_requested=intent.generate_html_report or rules.html_requested,
        normalize_input=intent.normalize_input or rules.normalize_input,
        parser_source="deepseek",
        parser_model=client.model,
        parser_prompt_tokens=usage.get("prompt_tokens", 0),
        parser_completion_tokens=usage.get("completion_tokens", 0),
        parser_total_tokens=usage.get("total_tokens", 0),
    )
