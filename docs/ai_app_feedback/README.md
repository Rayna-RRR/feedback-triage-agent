# 公开评论资料与复现链路

30 条公开评论、14 字段人工标注、5 条排除样本、编码指南、原分析报告和人工 QA 已作为来源快照迁入。五字段 `data/ai_app_reviews.csv` 仅是兼容输入，不替代完整标注；本次转换与既有文件逐字节一致。

## 来源与保存位置

来源仓库：[Rayna-RRR/ai-app-feedback-analysis](https://github.com/Rayna-RRR/ai-app-feedback-analysis)，固定提交：[b537f7aa1a9080eeda8d1aaedd47f2e484b6613d](https://github.com/Rayna-RRR/ai-app-feedback-analysis/tree/b537f7aa1a9080eeda8d1aaedd47f2e484b6613d)。本地来源 main 为 `c62759546fc2e8568c882915d4fb17324fb40d99`，远端新增提交只改 README，数据、文档及脚本相同。此次读取已提交文件，没有迁入本地未提交 README。

| 原路径 | 本仓库路径 | 用途 |
| --- | --- | --- |
| `data/raw_reviews.csv` | `data/ai_app_feedback/raw_reviews.csv` | 30 条公开原始样本，含日期、来源和原始备注 |
| `data/clean_reviews.csv` | `data/ai_app_feedback/clean_reviews.csv` | 30 条完整标注，14 列原样保留 |
| `data/excluded_reviews.csv` | `data/ai_app_feedback/excluded_reviews.csv` | 5 条千问排除样本及排除理由，不混入主样本 |
| `docs/coding_guide.md` | [source/coding_guide.md](source/coding_guide.md) | 原编码口径 |
| `docs/analysis_report.md` | [source/analysis_report.md](source/analysis_report.md) | 原分析报告 |
| `docs/qa_report.md` | [source/qa_report.md](source/qa_report.md) | 人工复核理由与既有裁决，脚本不得覆盖 |
| `docs/project_summary.md` | [source/project_summary.md](source/project_summary.md) | 原项目总结 |
| `README.md` | [source/README.md](source/README.md) | 来源提交的说明文档 |
| `scripts/*.py`（4 个） | `scripts/ai_app_feedback_source/*.py` | 原脚本只作追溯副本，不直接运行 |

[data/ai_app_feedback/provenance.json](../../data/ai_app_feedback/provenance.json) 记录每个迁入文件的原路径、新路径和 SHA-256。`source/` 文档中的相对路径仍属于原分析项目；在本仓库请按上表定位。源文件保持原样，后续修订应新增记录并注明依据，不覆盖历史裁决。旧分析仓库继续保留。

## 干净 checkout 复现

以下命令在仓库根目录执行。准备、原标签 QA 和汇总仅依赖 Python 3.9+ 标准库，不需要外部目录、API key 或网络。默认输入均基于脚本所在仓库定位，也可从其他工作目录用脚本绝对路径运行。

```bash
python scripts/prepare_ai_app_reviews.py
python scripts/label_quality_check.py
python scripts/summarize_reviews.py
```

输出分别为：

- `data/ai_app_reviews.csv`：原有 30 条五字段输入。
- `data/ai_app_feedback/generated/preparation.json`：输入和输出哈希、字段映射、30 个 ID。
- `data/ai_app_feedback/generated/qa_report.md`：自动 QA，可重复生成。
- `data/ai_app_feedback/generated/summary/*.csv`：App、问题大类、AI 类型、优先级及 Top 5 计数。

人工记录始终在 [source/qa_report.md](source/qa_report.md)。自动 QA 的 `--output` 不允许写入来源文档目录。

安装工作台依赖后，继续得到每条公开评论的系统输出和标签对照：

```bash
python -m pip install -e ".[dev]"
python -m feedback_triage_agent.cli run \
  --input data/ai_app_reviews.csv \
  --output data/ai_app_feedback/generated/triage --no-llm
python scripts/compare_ai_app_labels.py
python -m pytest
python -m feedback_triage_agent.cli harness \
  --output data/ai_app_feedback/generated/harness --skip-pytest
```

`--skip-pytest` 表示全量测试已在上一条命令单独执行；不能把它写成 harness 自己运行了 pytest。单独使用 harness 时可省略此参数。测试使用本地规则、模拟客户端和临时目录，不调用真实模型或在线 Demo。

系统结果保存在 `generated/triage/triage_results.csv`，按 ID 与完整标注连接；[generated/label_comparison.csv](../../data/ai_app_feedback/generated/label_comparison.csv) 保存逐条原标签、系统标签、优先级差异和系统复核标记。对照脚本检查 ID 集合以及来源、App、原文和评分一致，缺行、重复 ID 或证据改变会失败。运行日志、系统 QA、问题卡和复核队列同在 `generated/triage/`。triage/harness 运行目录不提交；来源 QA、汇总和对照表作为可重现快照提交，并由 CI 重跑比较。

外部输入必须显式指定，不再搜索被忽略的隐含目录或自动选取另一份样本：

```bash
python scripts/prepare_ai_app_reviews.py \
  --source /path/to/clean_reviews.csv \
  --output /tmp/reviews.csv --manifest /tmp/preparation.json
python scripts/label_quality_check.py \
  --input /path/to/clean_reviews.csv --output /tmp/auto_qa.md
python scripts/summarize_reviews.py \
  --input /path/to/clean_reviews.csv --output-dir /tmp/review_summary
```

`--source` 是 CSV 文件路径。准备脚本支持显式别名（如 `review_id/store/product/content/stars`），缺列、歧义列、空标识/正文、重复 ID 和非法评分会报错，不生成替代 ID 或静默换样本。该脚本用于旧接口，评分需为 1–5 整数；缺评分的来源应改用新版观察任务导入，不补造评分。用户提供外部文件时需自行明确来源和授权，仓库内公开样本无需额外下载。

## 14 字段到工作台的映射

| 完整标注字段 | 五字段兼容输入 / 保留方式 |
| --- | --- |
| `id` | 原样映射到 `id`，后续所有记录用同一 ID 追溯 |
| `source` | 原样映射到 `source` |
| `app_name` | 原样映射到 `app_name` |
| `review_date` | 保留在完整标注与 raw；不伪造成观察窗口或版本 |
| `rating` | 原样映射到 `rating` |
| `review_text` | 原样映射到 `review_text`，不改写正文 |
| `usage_scene` | 仅保留在完整标注，兼容输入无对应字段 |
| `issue_category` | 保留原人工标签；系统按原文独立分类，在对照表并列展示 |
| `ai_issue_type` | 保留原细分标签；系统无一对一对应字段 |
| `user_sentiment` | 保留原情绪标注，不等同于系统分类 |
| `user_need` | 保留人工需求；系统生成的同名字段是另一份判断 |
| `priority` | 保留人工 P0/P1/P2；系统重新判断，不覆盖原值 |
| `product_suggestion` | 保留人工建议；系统建议独立输出 |
| `notes` | 保留边界解释与次要问题，不转成系统已确认状态 |

原来的 7 个 `issue_category` 与系统同名分类可按名称比较：模型能力、交互体验、性能与稳定性、会员与商业化、内容安全与合规、账号/隐私/数据、用户预期与产品定位（完整枚举见编码指南和 CSV）。同名不意味着两种方法判定一致。系统额外有 `正向反馈/无明确问题` 和 `不明确/其他`；原来的正向能力样本常放在 `用户预期与产品定位问题`，不能机械重写成系统标签。

`ai_issue_type=不明确/其他` 是细分类型缺口，与系统的一级分类 `不明确/其他` 含义不同。安全误拦截、键盘交互、内容保存、文档解析等仍保留原细分边界与人工说明。P0/P1/P2 只在反馈层可作差异对照，不能直接当成问题簇级风险、复核状态或处理状态。

## QA 与人工判定

本次重跑原算法，30 条样本没有缺失列、非法枚举或关键字段为空警告；共 11 条警告，涉及 **9 条样本 + 1 项整体标签口径**。原脚本曾把“整体数据”也计入行数，迁入后的报告单独列出样本数和整体/结构对象数，警告规则不变。

9 个 ID 为 `DB_009`、`DB_010`、`DS_004`、`DS_005`、`DS_008`、`DS_009`、`KIMI_002`、`KIMI_005`、`KIMI_010`。它们的原理由和裁决完整保存在 [source/qa_report.md](source/qa_report.md)。例如 `DS_005` 的“隐私”触发 P2 关键词警告，但原文是正向评价，既有裁决保留 P2；`DS_009` 内容丢失和 `KIMI_010` 闪退保留 P0。保留标签表示人工接受当前口径并记录边界，不能写成“全部无问题”。

完整标注的细分 `不明确/其他` 有 10 条（33.3%），不等于 10 条都被逐条 QA 命中。来源标签 QA 的 9 条与系统分诊的人工队列也不是同一概念，队列数量可以不同。自动脚本不修改标注，不把旧人工 QA 转成新工作台的已确认记录。

## 数据限制

评论来自手动公开采样：豆包、DeepSeek、Kimi 各 10 条，时间为 2026-04 至 2026-05，来源为 App Store、应用宝和小米应用商店。来源材料没有每条评论的精确页面 URL、采集时刻或完整版本号；保存来源仓库和提交并不能补齐这些缺口。

该样本用于单批次分诊、标注边界和方法展示，缺少完整版本及前后窗口，不进入发版前后变化验证，也不证明版本因果关系。原分析结论只适用于这组小样本，标签对照不作为新的 golden set 或生产准确率。原报告提到的待验证指标不应写成已实现的业务效果。

本次实测和限制见 [verification.md](verification.md)。
