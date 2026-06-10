import re
from pathlib import Path


def infer_input_path(task: str) -> Path:
    match = re.search(r"([A-Za-z0-9_./\\-]+\.csv)", task)
    if not match:
        raise ValueError("无法识别输入文件，请在任务中写明 CSV 路径，例如 data/ai_app_reviews.csv。")
    return Path(match.group(1))


def infer_output_dir(task: str) -> Path:
    match = re.search(r"(?:输出到|输出目录|保存到)\s*([A-Za-z0-9_./\\-]+)", task)
    if match:
        return Path(match.group(1))
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
