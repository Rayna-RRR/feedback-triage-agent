"""检查 clean_reviews.csv 的标注质量。

这是项目的轻量本地 QA helper，只做数据质量检查，不生成分析结论。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLEAN_REVIEWS_PATH = PROJECT_ROOT / "data" / "clean_reviews.csv"
QA_REPORT_PATH = PROJECT_ROOT / "docs" / "qa_report.md"

REQUIRED_COLUMNS = [
    "id",
    "source",
    "app_name",
    "review_date",
    "rating",
    "review_text",
    "usage_scene",
    "issue_category",
    "ai_issue_type",
    "user_sentiment",
    "user_need",
    "priority",
    "product_suggestion",
    "notes",
]

ALLOWED_VALUES = {
    "usage_scene": {
        "写作",
        "搜索",
        "学习",
        "办公",
        "聊天",
        "图片/视频",
        "代码",
        "综合/不明确",
    },
    "issue_category": {
        "模型能力问题",
        "交互体验问题",
        "性能与稳定性问题",
        "会员与商业化问题",
        "内容安全与合规问题",
        "账号、隐私与数据问题",
        "用户预期与产品定位问题",
    },
    "ai_issue_type": {
        "回答不准",
        "幻觉 / 编造信息",
        "指令跟随差",
        "上下文记忆差",
        "搜索引用不足",
        "生成内容质量不稳定",
        "多轮对话体验差",
        "响应速度慢",
        "功能入口难找",
        "会员限制影响核心体验",
        "不明确/其他",
    },
    "user_sentiment": {"正向", "负向", "中性", "混合", "不明确"},
    "priority": {"P0", "P1", "P2"},
}

TARGET_APPS = {
    "豆包": "DB_",
    "DeepSeek": "DS_",
    "Kimi": "KIMI_",
}

VAGUE_SUGGESTION_PHRASES = [
    "优化体验",
    "提升质量",
    "增强用户粘性",
    "完善功能",
    "改善服务",
    "提升用户满意度",
]

SEVERE_BLOCKER_TERMS = [
    "无法使用",
    "闪退",
    "登不上",
    "登录不了",
    "数据丢失",
    "内容丢失",
    "扣费",
    "隐私",
    "严重错误",
    "误导",
    "骗人",
]

LOW_RELEVANCE_TERMS = [
    "占用手机空间",
    "安装包",
    "下载不了",
    "下载失败",
    "应用商店下载",
    "奶茶",
    "点餐",
    "外卖",
    "购物",
    "配送",
    "商家",
    "优惠券",
    "收货",
]


@dataclass
class WarningItem:
    row_id: str
    message: str


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"未找到文件：{path}")

    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames or [], list(reader)


def normalize(value: str | None) -> str:
    return (value or "").strip()


def count_chinese_chars(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def row_label(row: dict[str, str], index: int) -> str:
    return normalize(row.get("id")) or f"第 {index} 行"


def add_warning(bucket: list[WarningItem], row_id: str, message: str) -> None:
    bucket.append(WarningItem(row_id=row_id, message=message))


def build_report_section(title: str, items: list[WarningItem]) -> list[str]:
    lines = [f"## {title}", ""]
    if not items:
        lines.extend(["暂无。", ""])
        return lines

    for item in items:
        lines.append(f"- `{item.row_id}`：{item.message}")
    lines.append("")
    return lines


def has_specific_action(text: str) -> bool:
    action_terms = ["增加", "补充", "建立", "说明", "展示", "记录", "提示", "拆分", "复盘", "修复", "调整"]
    return any(term in text for term in action_terms)


def write_report(
    total_rows: int,
    rows_with_issues: set[str],
    missing_column_warnings: list[WarningItem],
    invalid_value_warnings: list[WarningItem],
    missing_field_warnings: list[WarningItem],
    vague_suggestion_warnings: list[WarningItem],
    priority_warnings: list[WarningItem],
    low_information_warnings: list[WarningItem],
    unclear_ratio_warnings: list[WarningItem],
    consistency_warnings: list[WarningItem],
) -> None:
    QA_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 标签质量 QA 报告",
        "",
        "本报告由 `scripts/label_quality_check.py` 生成，只用于检查 `data/clean_reviews.csv` 的标注质量，不代表最终分析结论。",
        "",
        "## 汇总",
        "",
        f"- 检查总行数：{total_rows}",
        f"- 存在问题的行数：{len(rows_with_issues)}",
        "",
    ]

    lines.extend(build_report_section("缺失列警告", missing_column_warnings))
    lines.extend(build_report_section("非法枚举值警告", invalid_value_warnings))
    lines.extend(build_report_section("关键字段为空警告", missing_field_warnings))
    lines.extend(build_report_section("建议语句过泛警告", vague_suggestion_warnings))
    lines.extend(build_report_section("优先级检查警告", priority_warnings))
    lines.extend(build_report_section("疑似无关或低信息量评论警告", low_information_warnings))
    lines.extend(build_report_section("不明确/其他比例警告", unclear_ratio_warnings))
    lines.extend(build_report_section("标签一致性警告", consistency_warnings))

    lines.extend(
        [
            "## 建议下一步",
            "",
            "- 先修正缺失列和非法枚举值，再复核优先级。",
            "- 对疑似无关或低信息量评论判断是否应从分析样本中移除。",
            "- 将过泛的 `product_suggestion` 改写为具体、可执行、可验证的建议。",
            "- 对 `ai_issue_type` 为 `不明确/其他` 的行，检查是否可以选择更明确的 AI 问题类型。",
            "",
        ]
    )

    QA_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    fieldnames, rows = read_rows(CLEAN_REVIEWS_PATH)

    missing_column_warnings: list[WarningItem] = []
    invalid_value_warnings: list[WarningItem] = []
    missing_field_warnings: list[WarningItem] = []
    vague_suggestion_warnings: list[WarningItem] = []
    priority_warnings: list[WarningItem] = []
    low_information_warnings: list[WarningItem] = []
    unclear_ratio_warnings: list[WarningItem] = []
    consistency_warnings: list[WarningItem] = []
    rows_with_issues: set[str] = set()

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    for column in missing_columns:
        add_warning(missing_column_warnings, "文件结构", f"缺少必需列 `{column}`。")
        rows_with_issues.add("文件结构")

    unclear_count = 0
    for index, row in enumerate(rows, start=2):
        current_id = row_label(row, index)

        review_text = normalize(row.get("review_text"))
        user_need = normalize(row.get("user_need"))
        product_suggestion = normalize(row.get("product_suggestion"))
        ai_issue_type = normalize(row.get("ai_issue_type"))
        priority = normalize(row.get("priority"))
        app_name = normalize(row.get("app_name"))
        notes = normalize(row.get("notes"))
        combined_issue_text = f"{review_text} {user_need} {product_suggestion} {notes}"

        if ai_issue_type == "不明确/其他":
            unclear_count += 1

        for field, allowed_values in ALLOWED_VALUES.items():
            value = normalize(row.get(field))
            if value and value not in allowed_values:
                add_warning(
                    invalid_value_warnings,
                    current_id,
                    f"`{field}` 的值 `{value}` 不在允许范围内。",
                )
                rows_with_issues.add(current_id)

        for field in ["review_text", "user_need", "product_suggestion"]:
            if not normalize(row.get(field)):
                add_warning(missing_field_warnings, current_id, f"`{field}` 为空。")
                rows_with_issues.add(current_id)

        if review_text and count_chinese_chars(review_text) < 4:
            add_warning(low_information_warnings, current_id, "评论文本少于 4 个中文字符，信息量可能不足。")
            rows_with_issues.add(current_id)

        if any(term in review_text for term in LOW_RELEVANCE_TERMS):
            add_warning(low_information_warnings, current_id, "评论可能偏向下载、安装、手机空间或生活服务内容，需复核是否与 AI 产品体验相关。")
            rows_with_issues.add(current_id)

        expected_prefix = TARGET_APPS.get(app_name)
        if expected_prefix is None:
            add_warning(low_information_warnings, current_id, f"`app_name` 为 `{app_name}`，不在主分析 App 范围：豆包、DeepSeek、Kimi。")
            rows_with_issues.add(current_id)
        elif not current_id.startswith(expected_prefix):
            add_warning(low_information_warnings, current_id, f"`id` 前缀与 `app_name` 不匹配，`{app_name}` 应使用 `{expected_prefix}` 开头。")
            rows_with_issues.add(current_id)

        if any(phrase in product_suggestion for phrase in VAGUE_SUGGESTION_PHRASES):
            add_warning(vague_suggestion_warnings, current_id, "产品建议包含过泛表达，需要改写得更具体。")
            rows_with_issues.add(current_id)

        if ai_issue_type == "不明确/其他" and has_specific_action(product_suggestion):
            add_warning(
                consistency_warnings,
                current_id,
                "`ai_issue_type` 为 `不明确/其他`，但产品建议较具体，建议复核问题类型是否可更明确。",
            )
            rows_with_issues.add(current_id)

        has_severe_term = any(term in combined_issue_text for term in SEVERE_BLOCKER_TERMS)
        if priority == "P0" and not has_severe_term:
            add_warning(priority_warnings, current_id, "标为 P0，但文本未明显出现严重阻断或高风险关键词。")
            rows_with_issues.add(current_id)
        if priority == "P2" and has_severe_term:
            add_warning(priority_warnings, current_id, "标为 P2，但文本出现严重阻断或高风险关键词。")
            rows_with_issues.add(current_id)

    if rows:
        unclear_ratio = unclear_count / len(rows)
        if unclear_count >= 3 or unclear_ratio > 0.3:
            add_warning(
                unclear_ratio_warnings,
                "整体数据",
                f"`ai_issue_type` 为 `不明确/其他` 的行数为 {unclear_count}，占比约 {unclear_ratio:.0%}，建议复核标签口径。",
            )
            rows_with_issues.add("整体数据")

    write_report(
        total_rows=len(rows),
        rows_with_issues=rows_with_issues,
        missing_column_warnings=missing_column_warnings,
        invalid_value_warnings=invalid_value_warnings,
        missing_field_warnings=missing_field_warnings,
        vague_suggestion_warnings=vague_suggestion_warnings,
        priority_warnings=priority_warnings,
        low_information_warnings=low_information_warnings,
        unclear_ratio_warnings=unclear_ratio_warnings,
        consistency_warnings=consistency_warnings,
    )

    total_warnings = sum(
        len(bucket)
        for bucket in [
            missing_column_warnings,
            invalid_value_warnings,
            missing_field_warnings,
            vague_suggestion_warnings,
            priority_warnings,
            low_information_warnings,
            unclear_ratio_warnings,
            consistency_warnings,
        ]
    )

    print("AI Review Label QA Agent")
    print(f"检查文件：{CLEAN_REVIEWS_PATH}")
    print(f"检查总行数：{len(rows)}")
    print(f"存在问题的行数：{len(rows_with_issues)}")
    print(f"警告总数：{total_warnings}")
    print(f"QA 报告已写入：{QA_REPORT_PATH}")


if __name__ == "__main__":
    main()
