import re
from pathlib import Path


TASK_SEPARATOR_PATTERN = r"[，,；;\n]"


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
