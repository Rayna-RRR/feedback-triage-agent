# AI 应用用户反馈与产品体验分析

## 项目简介

本项目基于公开应用商店评论，对豆包、DeepSeek、Kimi 三款 AI 应用的用户体验问题进行系统分析，将非结构化评论转化为可分类、可复核、可交接的产品体验问题样本。

项目定位为**分析项目 + 方法沉淀**：重点展示从原始评论到结构化产品结论的完整分析流程，以及可复用的标注口径和 QA 检查机制。本项目同时作为 [Feedback Triage Agent](https://github.com/Rayna-RRR/feedback-triage-agent) 的数据基础和分类口径来源——人工完成全流程标注与分析约需 1 小时，这一成本是后续工具化的直接动因。

## 项目背景

AI 应用的用户反馈同时包含通用体验问题和 AI 特有体验问题：既有卡顿、入口难找、会员限制说明不清楚，也有回答不准、幻觉、上下文记忆差、指令跟随差、生成质量不稳定等信号。

面对分散、情绪化、非结构化的评论，如何提炼出**可讨论、可排序、可跟踪**的产品问题，是本项目希望回答的核心问题。

具体问题包括：
- 用户在真实 AI 应用评论中最常反馈哪些产品体验问题？
- 哪些问题属于模型能力，哪些属于交互、性能、内容安全或信任问题？
- 评论中体现了哪些高价值使用场景和用户期待？
- 哪些问题应优先处理，哪些可作为产品或运营优化机会？

## 数据与样本说明

有效样本来自 `data/clean_reviews.csv`，共 30 条，覆盖三款 AI 应用，每款各 10 条。

| 维度 | 说明 |
| --- | --- |
| App 范围 | 豆包、DeepSeek、Kimi |
| 样本量 | 30 条有效评论 |
| iOS 来源 | App Store |
| Android 来源 | 应用宝；Kimi 补充小米应用商店 |
| 归档样本 | 5 条千问相关样本归档至 `data/excluded_reviews.csv` |

样本采集方式为手动公开采样，保留评论正文、评分、日期、来源等字段。初始备选应用千问的有效 AI 产品体验反馈较少，相关样本已归档，主分析聚焦豆包、DeepSeek、Kimi。

## 标注字段与分析口径

每条评论标注 10+ 字段，涵盖：

- **分类字段**：使用场景、问题大类（`issue_category`）、AI 问题类型（`ai_issue_type`）
- **判断字段**：优先级、人工复核标记
- **产品字段**：用户需求、产品建议
- **质控字段**：证据原文、复核备注

`issue_category` 为主分析层级，主要大类包括模型能力问题、交互体验问题、性能与稳定性问题、会员与商业化问题、内容安全与合规问题、账号隐私与数据问题、用户预期与产品定位问题。`ai_issue_type` 作为辅助字段，补充幻觉、指令跟随差、上下文记忆差等 AI 体验细节。

标注过程采用 AI 初稿 + 人工复核方式，处理边界样本、空泛建议和优先级偏差，确保口径一致可交接。

## 分析流程

1. **选择分析对象**：确定豆包、DeepSeek、Kimi 三款 AI 应用
2. **收集公开评论**：手动整理 App Store、应用宝、小米应用商店公开评论
3. **录入原始评论**：保存至 `data/raw_reviews.csv`，对应 Skill `01-raw-review-ingest`
4. **人工标注样本**：按编码指南标注为 `data/clean_reviews.csv`，对应 Skill `02-clean-review-labeling`
5. **检查标注质量**：检查非法标签、低信息量评论、可疑优先级，对应 `scripts/label_quality_check.py` 和 Skill `03-label-quality-check`
6. **汇总分析**：基于 `issue_category`、`priority`、`user_need`、`product_suggestion` 输出问题分布
7. **形成产品建议**：将高频问题整理为具体动作、预期改善和可观察指标

## 配套工具

本项目配套开发了 **3 个 Agent Skill** 和 **4 个 Python 脚本**，覆盖评论录入、标注复核、质量检查和汇总统计：

| 工具 | 用途 |
| --- | --- |
| `01-raw-review-ingest` Skill | 原始评论录入规范与字段要求 |
| `02-clean-review-labeling` Skill | 标注流程与口径指南 |
| `03-label-quality-check` Skill | 标注质量检查步骤 |
| `scripts/append_raw_reviews.py` | 批量追加原始评论 |
| `scripts/append_clean_reviews.py` | 批量追加标注评论 |
| `scripts/label_quality_check.py` | 自动检查标注合法性与质量 |
| `scripts/summarize_reviews.py` | 问题分布统计与汇总 |

## 核心分析产出

主要报告文件：
- `docs/analysis_report.md`：完整分析报告，含问题分布、洞察和产品建议
- `docs/coding_guide.md`：标注规则和标签口径（可迁移至客服工单、问卷开放题、社群反馈等场景）
- `docs/qa_report.md`：标注质量检查结果

主要发现：
- 模型能力问题为 Top 1，占 **36.7%**
- 性能与稳定性问题占 **20.0%**，在 Kimi 样本中较突出
- 交互体验问题和用户预期问题各占 13.3%
- P0 高优先级问题 **4 条**，涉及事实误导、幻觉、内容丢失和闪退
- 正向样本显示用户认可长上下文、复杂任务处理、代码辅助和情绪价值

## 与 Feedback Triage Agent 的关系

本项目是 [Feedback Triage Agent](https://github.com/Rayna-RRR/feedback-triage-agent) 的前置项目：

- `data/clean_reviews.csv` 的 30 条样本作为 Agent 的测试数据
- 本项目沉淀的问题分类体系和优先级口径，直接用于 Agent 的规则设计
- 人工全流程约 1 小时的处理成本，是工具化的直接动因

## 项目结构

```text
ai-app-feedback-analysis/
├── README.md
├── data/
│   ├── raw_reviews.csv
│   ├── clean_reviews.csv
│   └── excluded_reviews.csv
├── docs/
│   ├── coding_guide.md
│   ├── qa_report.md
│   └── analysis_report.md
├── scripts/
│   ├── append_raw_reviews.py
│   ├── append_clean_reviews.py
│   ├── label_quality_check.py
│   └── summarize_reviews.py
└── .agents/
    └── skills/
        ├── 01-raw-review-ingest/
        ├── 02-clean-review-labeling/
        └── 03-label-quality-check/
```

## 如何查看

建议按以下顺序阅读：

1. `docs/analysis_report.md`：完整分析结论、问题洞察和产品建议
2. `docs/coding_guide.md`：标签定义、标注规则和分析口径
3. `docs/qa_report.md`：标注质量检查结果
4. `data/clean_reviews.csv`：结构化后的有效样本

可在项目根目录运行：

```bash
python3 scripts/label_quality_check.py
python3 scripts/summarize_reviews.py
```

## 适用范围说明

- 当前样本量 30 条，适合展示分析方法和初步观察，不代表统计显著结论
- 公开评论可能偏向强情绪用户和低评分用户
- 人工编码存在主观性，复合问题评论需选择主要大类
- 产品建议基于外部反馈，内部埋点、留存、转化数据可作为后续验证
