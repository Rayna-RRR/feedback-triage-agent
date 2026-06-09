from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Dict, List

import pandas as pd


class ReportInputError(RuntimeError):
    """Raised when exported agent files are missing or unreadable."""


def require_report_inputs(output_dir: Path) -> Dict[str, Path]:
    paths = {
        "triage_results": output_dir / "triage_results.csv",
        "qa_report": output_dir / "qa_report.md",
        "issue_cards": output_dir / "issue_cards.md",
        "run_log": output_dir / "run_log.md",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise ReportInputError(
            "缺少报告输入文件，请先运行 run 命令生成导出结果: " + "，".join(missing)
        )
    return paths


def parse_bullet_map(markdown: str) -> Dict[str, str]:
    values = {}
    for line in markdown.splitlines():
        match = re.match(r"^- ([^:：]+)[:：]\s*(.*)$", line.strip())
        if match:
            values[match.group(1).strip()] = match.group(2).strip()
    return values


def parse_boundary_items(markdown: str) -> List[str]:
    marker = "## Agent 本轮判断边界"
    if marker not in markdown:
        return []
    section = markdown.split(marker, 1)[1]
    next_section = section.find("\n## ")
    if next_section >= 0:
        section = section[:next_section]
    return [line[2:].strip() for line in section.splitlines() if line.strip().startswith("- ")]


def parse_issue_cards(markdown: str) -> List[Dict[str, str]]:
    cards = []
    for section in re.split(r"\n(?=## \d+\. )", markdown):
        section = section.strip()
        if not section.startswith("## "):
            continue
        lines = section.splitlines()
        title = lines[0].replace("## ", "", 1).strip()
        values = parse_bullet_map(section)
        cards.append(
            {
                "title": title,
                "id": values.get("代表样本 ID", ""),
                "summary": values.get("用户原话摘要", ""),
                "category": values.get("问题类型", ""),
                "priority": values.get("优先级", ""),
                "suggestion": values.get("产品建议", ""),
                "review_reasons": values.get("需要人工复核的原因", ""),
            }
        )
    return cards


def parse_run_log(markdown: str) -> List[Dict[str, str]]:
    steps = []
    for section in re.split(r"\n(?=## \d+\. )", markdown):
        section = section.strip()
        if not section.startswith("## "):
            continue
        lines = section.splitlines()
        title = lines[0].replace("## ", "", 1).strip()
        values = parse_bullet_map(section)
        steps.append(
            {
                "step": title,
                "status": values.get("状态", ""),
                "input_summary": values.get("输入摘要", ""),
                "output_summary": values.get("输出摘要", ""),
                "warnings": values.get("warnings", ""),
                "next_action": values.get("下一步动作", ""),
            }
        )
    return steps


def boolish(value: object) -> bool:
    normalized = str(value).strip().lower()
    return normalized in {"true", "1", "yes", "y"}


def count_map_frame(values: pd.Series) -> pd.DataFrame:
    return values.fillna("").astype(str).replace("", "未填写").value_counts().rename_axis("name").reset_index(name="count")


def render_table(headers: List[str], rows: List[List[object]]) -> str:
    header_html = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    if not rows:
        return f"<table><thead><tr>{header_html}</tr></thead><tbody><tr><td colspan=\"{len(headers)}\">无</td></tr></tbody></table>"

    row_html = []
    for row in rows:
        cells = "".join(f"<td>{escape(str(value))}</td>" for value in row)
        row_html.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(row_html)}</tbody></table>"


def render_metric_cards(metrics: Dict[str, object]) -> str:
    cards = []
    for label, value in metrics.items():
        cards.append(
            "<div class=\"metric\">"
            f"<span>{escape(label)}</span>"
            f"<strong>{escape(str(value))}</strong>"
            "</div>"
        )
    return "<div class=\"metrics\">" + "".join(cards) + "</div>"


def generate_html_report(output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    paths = require_report_inputs(output_dir)

    results = pd.read_csv(paths["triage_results"]).fillna("")
    qa_markdown = paths["qa_report"].read_text(encoding="utf-8")
    issue_cards_markdown = paths["issue_cards"].read_text(encoding="utf-8")
    run_log_markdown = paths["run_log"].read_text(encoding="utf-8")

    qa_values = parse_bullet_map(qa_markdown)
    issue_cards = parse_issue_cards(issue_cards_markdown)
    run_steps = parse_run_log(run_log_markdown)
    boundaries = parse_boundary_items(qa_markdown)

    review_mask = results["needs_human_review"].map(boolish) if "needs_human_review" in results else pd.Series([], dtype=bool)
    review_items = results[review_mask] if len(results) else results

    metrics = {
        "总样本数": qa_values.get("总样本数", len(results)),
        "有效样本数": qa_values.get("有效样本数", len(results)),
        "问题卡片数": len(issue_cards),
        "人工复核队列数": qa_values.get("需要人工复核样本数", len(review_items)),
        "LLM 使用情况": qa_values.get("是否使用 LLM", "False"),
        "Fallback 情况": qa_values.get("是否 fallback 到 rules.py", "False"),
    }

    category_rows = count_map_frame(results["issue_category"]).values.tolist() if "issue_category" in results else []
    priority_rows = count_map_frame(results["priority"]).values.tolist() if "priority" in results else []
    review_rows = [
        [
            row.get("id", ""),
            row.get("issue_category", ""),
            row.get("priority", ""),
            row.get("human_review_reasons", ""),
        ]
        for _, row in review_items.iterrows()
    ]
    card_rows = [
        [
            card["id"],
            card["title"],
            card["category"],
            card["priority"],
            card["summary"],
            card["suggestion"],
        ]
        for card in issue_cards
    ]
    run_rows = [
        [
            step["step"],
            step["status"],
            step["output_summary"],
            step["warnings"],
            step["next_action"],
        ]
        for step in run_steps
    ]
    boundary_html = "".join(f"<li>{escape(item)}</li>" for item in boundaries) or "<li>无</li>"

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Feedback Triage Agent Report</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #1f2933; background: #f6f8fa; }}
    header {{ padding: 32px 40px 18px; background: #ffffff; border-bottom: 1px solid #d9e2ec; }}
    main {{ padding: 24px 40px 48px; max-width: 1180px; margin: 0 auto; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin: 28px 0 12px; font-size: 20px; }}
    p {{ margin: 0; color: #52606d; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }}
    .metric {{ background: #ffffff; border: 1px solid #d9e2ec; border-radius: 6px; padding: 14px; }}
    .metric span {{ display: block; color: #52606d; font-size: 13px; }}
    .metric strong {{ display: block; margin-top: 6px; font-size: 22px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #d9e2ec; border-radius: 6px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf1f5; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #eef3f8; color: #334e68; }}
    tr:last-child td {{ border-bottom: 0; }}
    ul {{ background: #ffffff; border: 1px solid #d9e2ec; border-radius: 6px; padding: 14px 22px; }}
    li {{ margin: 6px 0; }}
  </style>
</head>
<body>
  <header>
    <h1>Feedback Triage Agent Report</h1>
    <p>本地静态报告，来源目录：{escape(str(output_dir))}</p>
  </header>
  <main>
    <h2>运行总览</h2>
    {render_metric_cards(metrics)}

    <h2>问题类型分布</h2>
    {render_table(["问题类型", "数量"], category_rows)}

    <h2>优先级分布</h2>
    {render_table(["优先级", "数量"], priority_rows)}

    <h2>人工复核样本列表</h2>
    {render_table(["ID", "问题类型", "优先级", "原因"], review_rows)}

    <h2>问题卡片摘要</h2>
    {render_table(["ID", "标题", "问题类型", "优先级", "摘要", "产品建议"], card_rows)}

    <h2>Agent Run Log 七步摘要</h2>
    {render_table(["步骤", "状态", "输出摘要", "Warnings", "下一步"], run_rows)}

    <h2>本轮判断边界</h2>
    <ul>{boundary_html}</ul>
  </main>
</body>
</html>
"""
    report_path = output_dir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path
