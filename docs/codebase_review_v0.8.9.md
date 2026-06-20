# Codebase Review & Maintainability Audit v0.8.9

审查日期：2026-06-21

审查范围：

- `feedback_triage_agent/cli.py`
- `feedback_triage_agent/harness.py`
- `feedback_triage_agent/evaluation.py`
- `feedback_triage_agent/exporters.py`
- `feedback_triage_agent/review.py`
- `feedback_triage_agent/models.py`
- `feedback_triage_agent/rules.py`
- `.github/workflows/ci.yml`
- `tests/`
- `README.md`
- `pyproject.toml`
- `data/evaluation_feedback.csv`
- `data/adversarial_feedback.csv`

## 1. Executive Summary

- 当前代码库整体健康度良好，核心 Agent 主流程仍保持固定 7 步计划，适合继续做小步迭代。
- v0.8.4-v0.8.8 新增的 output contract、adversarial set、scenario metrics、harness 和 CI 没有明显破坏既有模块边界。
- CLI 目前主要承担命令参数、展示和退出码处理，尚未明显变成业务逻辑集中点。
- `harness.py` 职责清楚，主要负责串联 pytest、golden evaluation 和 adversarial evaluation，并生成汇总报告。
- `evaluation.py` 是近期增长最快的模块，已经同时承担 CSV 读取校验、逐样本预测、指标计算、scenario breakdown 和报告写入，后续需要控制继续膨胀。
- `rules.py` 是最大维护风险来源，关键词常量、否定语义、分类、优先级和人工复核启发式集中在同一文件，但当前不建议在本轮重写。
- 测试覆盖关键路径较完整，但 harness 输出合同、scenario 边界条件和 CI workflow 结构仍有可补强空间。
- 数据和输出目录边界基本清楚，不过 `data/evaluation_output/` 中仍有 tracked 运行产物，需要后续单独清理。

## 2. Architecture Boundaries

### CLI

`cli.py` 当前主要负责 Typer 命令定义、参数默认值、Rich 表格输出和根据执行结果返回非 0 退出码。`run`、`ask`、`evaluate`、`harness`、`report`、`review-apply` 的实际业务操作分别委托给 Agent、task parser、evaluation、harness、HTML report 和 review 模块。

维护判断：CLI 尚未承担过多核心逻辑。需要注意的是 `evaluate` 命令内直接维护一组质量 gate 判断，而 `harness.py` 也维护 `GOLDEN_GATES`，这会产生 gate 漂移风险。

### Harness

`harness.py` 负责：

- 可选运行 `pytest`
- 运行 golden set evaluation
- 运行 adversarial evaluation
- 判断 harness 总结果
- 写出 `harness_report.md` 和 `harness_summary.json`

维护判断：harness 目前只做总控，没有侵入 evaluation 或 rules 逻辑。风险主要是 gate 常量与 CLI 默认值重复，以及 pytest 输出没有落盘，失败时本地 harness 报告的排障信息较少。

### Evaluation

`evaluation.py` 负责：

- 读取带 expected 标签的 CSV
- 校验 expected category、priority、human review 字段
- 运行 `classify_feedback_record` 和 `detect_human_review_reasons`
- 计算总体指标和 scenario 分组指标
- 写出 `evaluation_results.csv` 和 `evaluation_report.md`

维护判断：模块边界仍然清楚，但职责开始变宽。当前 252 行还可接受；如果继续增加更多指标、更多 report 章节或更多输入 schema，建议拆出指标计算或报告渲染 helper。

### Exporters

`exporters.py` 负责 Agent 运行后的 Markdown、CSV 和 review template 导出。`TRIAGE_RESULT_COLUMNS` 明确定义并被 output contract test 引用。

维护判断：职责基本单一。需要注意 `render_qa_report` 中包含版本边界说明文本，未来版本文案可能与 README 同步成本增加。

### Review

`review.py` 负责 `review_decisions.csv` 模板、复核决策校验、reviewed 输出和复核摘要。固定列 `REVIEW_DECISIONS_COLUMNS` 已被测试引用。

维护判断：边界清楚。`boolish` 与 evaluation 的 `parse_expected_bool` 语义相近但用途不同，暂不需要合并。

### Models

`models.py` 保存 Pydantic 模型和 Literal 枚举，包括 `ClassificationSource`。模型层没有混入流程逻辑。

维护判断：结构清楚。后续修改输出字段时，应继续优先从模型、exporter columns 和 output contract 三处同步。

### Rules

`rules.py` 同时包含：

- 输入必要字段和 issue category 常量
- 多语言关键词表
- P0/P1 关键词
- 正向反馈、否定语义和 false positive 上下文
- 分类、置信度、优先级和人工复核规则
- 用户需求和产品建议模板

维护判断：这是当前最容易变重的模块。虽然不建议现在重写，但未来新增规则时应避免继续把所有常量和启发式无边界堆叠。

### Tests

测试覆盖包括：

- rules 分类与优先级
- tool-level 状态变更
- Agent 7 步完整流程
- CLI ask/report/review/evaluate/harness
- review decision apply
- evaluation metrics 和 scenario presence
- adversarial dataset 合法性
- output contract
- Web App 关键路径
- LLM client parsing 和 env config

维护判断：核心边界覆盖较好。缺口主要集中在新增 harness 输出合同、scenario 边界、CI workflow 结构和 gate 常量一致性。

## 3. Maintainability Risks

### P0：必须立即修

当前未发现必须立即修复的 P0 维护性问题。主流程、评测、harness 和 CI 都有测试或命令路径覆盖，暂无明显会阻断继续迭代的结构性问题。

### P1：建议本轮修

#### P1-1：Evaluation gate 常量重复

问题：`cli.py` 的 `evaluate` 命令默认 gate 和 `harness.py` 的 `GOLDEN_GATES` 分别维护。

影响：后续调整质量门槛时，CLI evaluate 和 harness 可能出现不一致，造成本地命令通过但 harness 失败，或反过来。

建议：把默认 gate 放到 `evaluation.py` 或一个轻量常量模块中，由 CLI 和 harness 共同引用。

#### P1-2：Harness 输出尚未形成独立 output contract

问题：`tests/test_harness.py` 验证了报告和 JSON 会生成，但没有完整锁定 `harness_summary.json` 的关键字段、类型和 report 主要章节。

影响：后续改 harness 报告格式时，可能不小心破坏下游读取 summary 的脚本或 CI artifact 使用方式。

建议：补一个轻量 harness output contract 测试，锁定必需 JSON keys、`output_paths` keys 和 report 标题章节。

#### P1-3：Scenario metrics 边界测试偏少

问题：当前测试覆盖了“没有 scenario 列仍可运行”和“adversarial report 包含 scenario 名称”，但没有覆盖空 scenario、全空 scenario、单个 scenario 无 P0 分母、多个 scenario 分组排序等边界。

影响：后续扩展 scenario breakdown 时，容易引入分母为 0、空值显示或列保留行为的回归。

建议：新增 1-2 个 evaluation 单元测试，专门覆盖 blank scenario 和 p0 denominator 为 0 的分组。

### P2：可以后续观察

#### P2-1：`rules.py` 规模继续增长

问题：`rules.py` 已经达到 800 行以上，常量和算法混在一起。

影响：新增类别、关键词或否定语义时，review 成本会上升，也更容易出现关键词误伤。

建议：暂不重写。等规则再扩展时，可以先把关键词常量拆到 `rule_keywords.py`，保持 `rules.py` 只放分类流程和启发式函数。

#### P2-2：Harness pytest 输出没有写入报告或文件

问题：`run_pytest` 捕获 stdout/stderr，但只返回布尔值和 return code，没有把日志写入 harness output。

影响：本地直接运行 harness 且 pytest 失败时，`harness_report.md` 只知道 failed，不包含失败详情。

建议：可选新增 `pytest_output.txt`，并在 summary/report 中记录路径。

#### P2-3：CI workflow 只有间接覆盖

问题：`.github/workflows/ci.yml` 没有测试验证结构，例如 Python 版本、pytest 命令和 harness 命令是否仍存在。

影响：workflow 被误改时只能等 GitHub Actions 运行发现。

建议：如果 CI 配置继续增长，可新增轻量文本/ YAML 结构测试；当前还不急。

#### P2-4：`render_qa_report` 中的版本边界说明可能滞后

问题：`exporters.py` 的 QA report 固定文本仍含历史版本表述。

影响：用户阅读导出报告时可能看到过时边界说明。

建议：后续可把版本无关的边界说明稳定化，减少每个版本都要更新 exporter 文案的需求。

## 4. Test Coverage Gaps

### CLI harness 命令测试

已有覆盖：

- `tests/test_harness.py` 覆盖 `run_evaluation_harness(skip_pytest=True)`。
- `tests/test_harness.py` 覆盖 CLI `harness --skip-pytest` 能生成 report 和 summary。

缺口：

- 没有覆盖不带 `--skip-pytest` 的 CLI harness 路径。这是合理取舍，因为测试中嵌套 pytest 成本高。
- 没有覆盖 golden gate 失败时 CLI harness 返回非 0 的路径。

建议：保持不嵌套 pytest；可用临时 root 测函数层失败路径，CLI 层继续只 smoke test。

### Scenario metrics 边界测试

已有覆盖：

- 无 `scenario` 列的旧 evaluation CSV 正常运行。
- adversarial CSV 有 `scenario` 列时正常运行。
- `evaluation_results.csv` 保留 `scenario` 列。
- report 包含 `Scenario Breakdown` 和至少一个 scenario 名称。

缺口：

- 空 scenario 值。
- scenario 列存在但全部为空。
- 分组中没有 expected P0 或 predicted P0 时的 precision/recall 分母为 0。
- 多 scenario 输出顺序是否稳定。

### CI workflow 间接覆盖不足

已有覆盖：

- 本地测试覆盖 harness 命令逻辑。
- CI workflow 会运行 pytest 和 harness。

缺口：

- 测试没有直接验证 `.github/workflows/ci.yml` 的关键命令。
- workflow 结构变化只能通过 GitHub Actions 自身发现。

当前判断：P2，可观察。CI 文件很短，不需要本轮引入 YAML 解析或复杂测试。

### Output contract 是否覆盖新增 harness 输出

已有覆盖：

- `tests/test_output_contract.py` 覆盖 Agent run 输出。
- `tests/test_harness.py` 验证 harness report 和 summary 存在。

缺口：

- 没有像 Agent output contract 一样锁定 `harness_summary.json` 的字段集合。
- 没有锁定 `output_paths` 必备 keys。
- 没有锁定 harness report 的主要章节。

建议：本轮可补一个小测试，不需要改 harness 行为。

### Adversarial set 是否只验证数据合法性，没有误作为 gate

已有覆盖：

- `tests/test_adversarial_dataset.py` 只验证数据集字段、标签合法性和样本数。
- `tests/test_harness.py` 明确验证 adversarial 低分不会让 harness 自动失败。
- README 和 CI 文档说明 adversarial 是探索性分析。

当前判断：定位清楚，没有误作为默认 gate。

## 5. Data & Output Hygiene

### 运行产物 ignore 状态

`.gitignore` 已忽略：

- `data/web_runs/`
- `data/evaluation_output/`
- `data/adversarial_output/`
- `data/harness_output/`
- `data/harness_output_skip/`
- `data/harness_output_ci/`
- `data/output/`
- `data/output_ask/`

这覆盖了当前 README、evaluate、harness、Web App 和 CLI demo 的主要输出目录。

### 运行产物是否会污染 git status

新生成的 ignored 输出不会污染 `git status`。但是当前仓库中 `data/evaluation_output/evaluation_report.md` 和 `data/evaluation_output/evaluation_results.csv` 仍是 tracked 文件。即使 `.gitignore` 已包含 `data/evaluation_output/`，Git 仍会继续跟踪已提交文件的修改。

建议：后续单独执行一次 tracked artifact 清理，把 `data/evaluation_output/` 从索引中移除但保留本地文件，避免未来 evaluate 默认命令污染 diff。

### Demo 数据与 evaluation 数据边界

当前边界清楚：

- `data/sample_feedback.csv` 用于 demo 和 Agent 流程。
- `data/evaluation_feedback.csv` 是 golden set，包含 expected 标签，不含 scenario。
- `data/adversarial_feedback.csv` 是探索性 adversarial set，包含 expected 标签和 scenario。

不要把 adversarial 样本合并进 golden set，也不要为了提高 adversarial 分数修改 expected 标签。

### README 命令是否容易误提交输出目录

README 中的命令默认写入 ignored 输出目录。一般不会污染 `git status`，但如果输出目录中已有 tracked 文件，例如当前的 `data/evaluation_output/`，重新运行命令仍可能修改 tracked 文件。

建议：在后续清理 tracked artifact 后，这个风险会显著降低。无需在本次审查步骤修改 README。

## 6. Refactor Candidates

### Candidate 1：抽出共享 evaluation gate 常量

问题：CLI evaluate 默认 gate 与 harness `GOLDEN_GATES` 重复。

影响：门槛调整时容易漂移。

建议修改：在 `evaluation.py` 增加 `DEFAULT_QUALITY_GATES`，CLI 和 harness 共同引用。

是否会改变现有行为：不会，应保持当前数值不变。

是否需要新增测试：需要。覆盖 CLI evaluate 和 harness 使用同一组 gate，或至少验证常量值和 harness 判断一致。

### Candidate 2：补 harness output contract 测试

问题：harness 输出已成为 CI artifact，但字段结构没有被像 Agent 输出一样锁住。

影响：下游读取 `harness_summary.json` 或人工查看 report 时，可能被无意破坏。

建议修改：新增测试，验证 `harness_summary.json` 至少包含 `pytest_passed`、`pytest_skipped`、`golden_passed`、`adversarial_completed`、`harness_passed`、`golden_metrics`、`adversarial_metrics`、`output_paths`；验证 report 包含主要章节。

是否会改变现有行为：不会。

是否需要新增测试：这本身就是测试改动。

### Candidate 3：补 scenario metrics 边界测试

问题：scenario breakdown 的边界条件还没有被锁住。

影响：空 scenario、分母为 0 或多组排序可能发生回归。

建议修改：增加小型临时 CSV 测试，覆盖空 scenario 和没有 P0 的 scenario 分组。

是否会改变现有行为：不会。

是否需要新增测试：需要。

### Candidate 4：记录 harness pytest 输出

问题：harness 本地运行 pytest 失败时，summary 只记录 return code，没有失败输出路径。

影响：本地排障需要重新运行 pytest。

建议修改：可选写出 `<harness-output>/pytest_output.txt`，并在 `harness_summary.json` 的 `output_paths` 中记录。

是否会改变现有行为：有轻微新增输出文件，但不改变通过/失败判定。

是否需要新增测试：需要，验证 skip 模式不强制生成 pytest log，非 skip 模式失败时有日志。

### Candidate 5：后续拆分 `rules.py` 常量

问题：关键词表和算法混在 `rules.py` 中，文件已超过 800 行。

影响：长期维护成本上升，关键词调整容易影响分类流程。

建议修改：后续把 `CATEGORY_KEYWORDS`、`P0_KEYWORDS`、`P1_KEYWORDS`、正向/否定上下文和建议模板移动到 `rule_keywords.py` 或 `rule_constants.py`。

是否会改变现有行为：不应改变，但迁移风险比前几个候选项高。

是否需要新增测试：需要运行完整规则、evaluation、output contract 和 harness 测试。

## 7. Do Not Change

本轮不建议修改：

- 不重写 `rules.py`。
- 不改变 `data/evaluation_feedback.csv` 的 expected 标签。
- 不改变 `data/adversarial_feedback.csv` 的 expected 标签。
- 不把 adversarial set 改成默认质量 gate。
- 不为了让 adversarial set 全部通过而调整规则。
- 不引入外部 review、lint、coverage 或 CI 工具作为硬依赖。
- 不新增复杂 harness 目录或框架。
- 不改变 Agent 固定 7 步主流程。
- 不改变 LLM 接入边界或默认不接外部 API 的原则。

## 8. Recommended v0.8.9 Scope

建议 v0.8.9 的最小可执行范围控制在以下 3 个小改动：

1. 抽出共享 evaluation gate 常量，让 CLI evaluate 和 harness 使用同一份默认门槛。
2. 新增 harness output contract 测试，锁定 `harness_report.md` 和 `harness_summary.json` 的关键结构。
3. 新增 scenario metrics 边界测试，覆盖空 scenario 和 P0 分母为 0 的分组。

可选第 4 个小改动：

4. 清理已 tracked 的 `data/evaluation_output/` 运行产物，仅从 Git 索引移除，不删除本地文件。

这组范围不需要修改 `rules.py`，不改变 expected 标签，不改变 Agent 主流程，也不引入新依赖。优先收益是降低 gate 漂移、保护 harness 输出结构，并让 scenario metrics 在后续规则迭代中更稳定。
