# 发版后反馈风险工作台 v1.0 独立产品验收报告

## 结论

**FAIL**

核心流程存在数据完整性、问题簇判断、后续窗口建模、证据可追溯性和移动端可用性问题，因此不能判定为 `CONDITIONAL PASS` 或 `PASS`。自动化测试通过不改变本结论。

主要阻断项：

- 固定数据未得到六个预期问题簇；导出失败与“导出成功但格式错乱”被合并为一个簇。
- 重复 ID 和窗口外时间均被导入，没有明确报错，也没有阻止脏数据写入。
- 后续 48 小时数据没有形成独立窗口，而是追加到当前窗口，导致当前反馈从 30 条变为 60 条。
- 390px 移动端主页面出现明显横向溢出和内容裁切。
- 证据卡片展示了原文、ID、来源和相对窗口，但未明确展示版本；模糊簇在人工处理前被自动标为“缓解”，结论强度不符合预期。

## 验收范围、环境和基线

- 验收日期：2026-07-28（Asia/Shanghai）。
- 当前 commit：`8604560607039c848164736652c85e5ceb38c648`（`docs: improve portfolio presentation for feedback triage agent`）。
- 实际运行环境：macOS；系统 `python3` 为 3.9.6；验收隔离环境 `/private/tmp/feedback-risk-acceptance-venv` 使用 Python 3.13.12；Node.js v22.20.0；npm 10.9.3。
- 启动命令：

  ```text
  FEEDBACK_RISK_TASKS_DIR=artifacts/acceptance_v1.0/observation_tasks FEEDBACK_TRIAGE_WEB_RUNS_DIR=artifacts/acceptance_v1.0/legacy_runs /private/tmp/feedback-risk-acceptance-venv/bin/python -m feedback_triage_agent.web_app
  ```

- 实际页面入口：`http://127.0.0.1:8000/`。
- 实际验收数据：3 个有效窗口、共 90 条反馈；3 个异常输入文件；2 个观察任务；4 次人工簇操作（确认、驳回、合并、拆分）。
- 已完整读取：`AGENTS.md`、`README.md`、`models.py`、`observation.py`、`rules.py`、`web_app.py`、相关模板、静态资源和测试说明/测试文件。

## 独立验收数据

数据文件：[`artifacts/acceptance_v1.0/data`](./data/)。每条有效反馈均有唯一 ID、时间、版本、来源和原文；三个窗口各 30 条，使用不同措辞表达同一问题，未通过修改预期结果迁就实现。

| 问题簇 | 基线预期 | 当前预期 | 后续预期 | 数据核对结果 |
|---|---:|---:|---:|---|
| 导出文件失败 | 1 | 6 | 2 | 输入数据按预期准备；页面将其与格式错乱合并 |
| 回答被截断 | 0 | 4 | 4 | 输入数据按预期准备；页面拆成多个泛化簇 |
| 登录失败 | 4 | 4 | 6 | 输入数据按预期准备；页面识别为登录/账号/访问异常 |
| 引用内容错误 | 7 | 2 | 1 | 输入数据按预期准备；页面归入回答不准确或编造内容 |
| “变得不好用”等模糊反馈 | 0 | 2 | 2 | 输入数据按预期准备；页面进入低置信度簇，但初始趋势仍显示“缓解” |
| 导出成功但格式错乱 | 2 | 2 | 2 | 输入数据按预期准备；页面与导出失败合并 |
| 正向或中性补足 | 16 | 10 | 13 | 三窗均补足至 30 条 |

文件：[`baseline_48h.csv`](./data/baseline_48h.csv)、[`current_48h.csv`](./data/current_48h.csv)、[`followup_48h.csv`](./data/followup_48h.csv)。

## 页面验收结果

证据截图集中在 [`artifacts/acceptance_v1.0/screenshots`](./screenshots/)，任务持久化状态在 [`observation_tasks`](./observation_tasks/)；严重程度：P1 为核心验收阻断，P2 为非阻断问题。

| 验收项 | 预期 | 实际结果 | 证据 | 严重程度 |
|---|---|---|---|---|
| 创建观察任务并导入窗口 | 能创建任务并导入基线、当前、后续三个连续 48 小时窗口 | 能创建任务并导入基线和当前；后续没有独立窗口入口，后续数据只能追加到当前 | [`02-task-form-desktop.png`](./screenshots/02-task-form-desktop.png)、[`03-task-form-before-submit.png`](./screenshots/03-task-form-before-submit.png)、[`08-incremental-task-result.png`](./screenshots/08-incremental-task-result.png) | P1 |
| 缺少必要字段 | 明确报错且不写入 | 缺少 `review_text` 时明确报错“CSV 未识别到反馈正文字段”，未产生有效脏数据 | [`invalid_missing_review_text.csv`](./data/invalid_missing_review_text.csv)、[`task_20260728_101740_v2-4_816762/observation_state.json`](./observation_tasks/task_20260728_101740_v2-4_816762/observation_state.json) | 通过 |
| 重复 ID | 明确报错且不写入 | 页面接受 1 条有效反馈、去重 1 条，未报错；不符合“重复 ID 拒绝写入”要求 | [`invalid_duplicate_id.csv`](./data/invalid_duplicate_id.csv)、同上状态文件中的导入审计 | P1 |
| 时间超出窗口 | 明确报错且不写入 | 页面接受 1 条有效反馈，未报错；窗口外时间未被拦截 | [`invalid_out_of_window.csv`](./data/invalid_out_of_window.csv)、同上状态文件中的导入审计 | P1 |
| 累计与增量导入 | 两种方式最终数量、风险状态一致且无重复计数 | 两个独立任务在清理后的基线/当前导入均为 30/30，均显示 14 个问题簇，未发现首次导入重复计数；但两者均未命中固定六簇预期 | [`task_20260728_101740_v2-4_816762/observation_state.json`](./observation_tasks/task_20260728_101740_v2-4_816762/observation_state.json)、[`task_20260728_103741_v2-4_43ba39/observation_state.json`](./observation_tasks/task_20260728_103741_v2-4_43ba39/observation_state.json)、[`08-incremental-task-result.png`](./screenshots/08-incremental-task-result.png) | P1 |
| 同义反馈聚合 | 不同说法应聚合同一问题 | 部分同义反馈被分散到“卡住/无响应”“性能卡”“性能失败”等多个泛化簇；未能稳定聚合 | [`06-radar-clusters-desktop.png`](./screenshots/06-radar-clusters-desktop.png)、主任务状态文件 | P1 |
| 语义不同的问题不误合并 | 导出失败与导出成功格式错乱必须分开 | 两者合并为“复制、导出或分享链路异常”，当前 8、基线 3；无法区分固定两簇 | [`05-current-import-clusters-desktop.png`](./screenshots/05-current-import-clusters-desktop.png)、[`06-radar-clusters-desktop.png`](./screenshots/06-radar-clusters-desktop.png) | P1 |
| 六个问题簇状态 | 命中固定预期的新增、加重、稳定、缓解和低置信度复核 | 实际为 14 个簇；例如导出相关合并为当前 8/基线 3，回答截断当前 4/基线 0 被泛化拆散，模糊簇初始显示“缓解” | [`06-radar-clusters-desktop.png`](./screenshots/06-radar-clusters-desktop.png)、[`07-raw-evidence-desktop.png`](./screenshots/07-raw-evidence-desktop.png) | P1 |
| 结论回溯证据 | ID、原文、版本和窗口应全部一致 | 原文、ID、来源和 current 相对窗口可回溯；证据卡未显式展示 v2.4，也未显式展示 48h，版本无法仅凭卡片核验 | [`07-raw-evidence-desktop.png`](./screenshots/07-raw-evidence-desktop.png)、主任务状态文件 | P1 |
| 模糊反馈 | 进入低置信度复核，不包装为确定趋势 | 进入低置信度簇（置信度约 0.15），但人工处理前自动趋势为“缓解”，不符合“不得自动下强结论” | [`06-radar-clusters-desktop.png`](./screenshots/06-radar-clusters-desktop.png)、[`09-post-operations-desktop.png`](./screenshots/09-post-operations-desktop.png) | P1 |
| 人工确认 | 确认一个问题簇 | 完成；设置负责人 Release Ops、处理状态“处理中”、下一步动作和结果 | [`09-post-operations-desktop.png`](./screenshots/09-post-operations-desktop.png)、主任务状态文件 | 通过 |
| 驳回模糊簇 | 驳回并保留原因和复核上下文 | 完成；记录“模糊反馈无法支持确定结论”的驳回原因 | [`09-post-operations-desktop.png`](./screenshots/09-post-operations-desktop.png)、主任务状态文件 | 通过 |
| 合并重复簇 | 合并后状态和证据正确 | 完成；将“性能与稳定性问题：卡”合并到“卡住、无响应或无法继续” | [`09-post-operations-desktop.png`](./screenshots/09-post-operations-desktop.png)、主任务状态文件 | 通过 |
| 拆分混合簇 | 拆出指定成员并保留关联关系 | 完成；从宽泛簇拆出指定反馈 | [`09-post-operations-desktop.png`](./screenshots/09-post-operations-desktop.png)、主任务状态文件 | 通过 |
| 操作审计 | 每次人工操作有前后状态、时间和修改内容 | 确认、驳回、合并、拆分均写入 `cluster_actions` 和审计事件，包含 timestamp、before、changes/reason/actor | [`10-owner-audit-desktop.png`](./screenshots/10-owner-audit-desktop.png)、[`task_20260728_101740_v2-4_816762/observation_state.json`](./observation_tasks/task_20260728_101740_v2-4_816762/observation_state.json) | 通过 |
| 页面数据同步 | 列表、问题卡、Radar、复核队列、负责人摘要和刷新后数据一致 | 操作后各区域与刷新后的页面同步；负责人摘要显示 Release Ops/处理中/已确认复现路径 | [`09-post-operations-desktop.png`](./screenshots/09-post-operations-desktop.png)、[`10-owner-audit-desktop.png`](./screenshots/10-owner-audit-desktop.png) | 通过 |
| 重启持久化 | 任务、处理状态和审计记录仍存在 | 重启本地应用后 30/30、14 簇、负责人和四条审计操作仍在 | [`task_20260728_101740_v2-4_816762/observation_state.json`](./observation_tasks/task_20260728_101740_v2-4_816762/observation_state.json)、[`10-owner-audit-desktop.png`](./screenshots/10-owner-audit-desktop.png) | 通过 |
| 导入后续窗口 | 展示缓解、持续或再次加重，且不覆盖上一轮 | 后续导入后当前变为 60 条、问题簇变为 15 个；没有第三窗口或上一轮/后续轮次的独立展示 | [`followup_48h.csv`](./data/followup_48h.csv)、主任务状态文件 | P1 |
| 因果边界文案 | 明确“发版后新增/加重不等于由版本导致” | 页面明确展示“相关不等于因果”及完整免责声明 | [`01-home-desktop.png`](./screenshots/01-home-desktop.png)、[`04-workspace-empty-desktop.png`](./screenshots/04-workspace-empty-desktop.png)、[`06-radar-clusters-desktop.png`](./screenshots/06-radar-clusters-desktop.png) | 通过 |
| `/run`、`/ask` 兼容接口 | 可运行但不成为主入口 | POST `/run` 和 `/ask` 均返回 303 并生成结果页；GET `/run` 返回 405，符合其 POST 兼容接口形态；主导航以观察任务工作台为入口 | [`legacy_runs/run_20260728_105225_acceptance_legacy`](./legacy_runs/run_20260728_105225_acceptance_legacy/)、[`legacy_runs/run_20260728_105353_ask`](./legacy_runs/run_20260728_105353_ask/) | 通过 |
| 桌面关键流程 | 无溢出、遮挡、不可点击或信息缺失 | 桌面端可创建、导入、查看、复核、操作、刷新和重启恢复；未发现阻断性桌面点击问题 | [`01-home-desktop.png`](./screenshots/01-home-desktop.png)、[`06-radar-clusters-desktop.png`](./screenshots/06-radar-clusters-desktop.png)、[`09-post-operations-desktop.png`](./screenshots/09-post-operations-desktop.png) | 通过 |
| 390px 移动关键流程 | 无横向溢出、遮挡、不可点击或信息缺失 | 主页面出现横向裁切：标题、存储提示、Hero、筛选区和指标区均超出视口；移动端关键流程不可判定为通过 | [`11-main-mobile-390.png`](./screenshots/11-main-mobile-390.png) | P1 |

## 实际聚合结果摘要

清理后的主任务页面显示基线 30 条、当前 30 条、14 个问题簇、待人工复核 12 个。页面实际簇包括：回答冗长/上下文衔接（4/0，新增）、卡住/无响应（1/0，新增）、不好用（1/0，新增）、性能卡（1/0，新增）、复制/导出/分享异常（8/3，加重）、性能失败（3/2，加重）、登录/账号/访问异常（4/4，稳定）、导航/输入/页面操作困难（1/1，稳定）、回答不准确/编造（2/4，缓解）、交互界面（1/1，稳定）、不明确/其他（7/9，缓解）、同步（0/1，缓解）、模型错了（0/2，缓解）、产品定位（0/1，缓解）。

这与固定的六个问题簇及其状态预期不一致，属于核心业务判定失败。

## 自动化检查

以下命令均在验收隔离 Python 环境或仓库目录执行，报告真实输出：

| 检查 | 实际输出 |
|---|---|
| 全量测试 | `133 passed in 1.56s` |
| Python 编译 | `rg --files -g '*.py' -0 \| xargs -0 env PYTHONPYCACHEPREFIX=/private/tmp/feedback-risk-pyc /private/tmp/feedback-risk-acceptance-venv/bin/python -m py_compile`，退出码 0，无输出 |
| JavaScript 语法 | `rg --files -g '*.js' -0 \| xargs -0 -n1 node --check`，退出码 0，无输出 |
| Git 空白检查 | `git diff --check`，退出码 0，无输出 |
| 仓库规定的其他检查 | 未发现 README/AGENTS 规定的额外 lint、构建或部署检查；按要求执行 pytest、编译和语法检查 |

自动化检查证明实现可运行和测试用例稳定，但没有代替真实页面、真实导入链路和移动端验收。

## 未能验证的项目

- 390px 移动端的导入子流程未完成截图和完整点击走查：无头浏览器跳转导入锚点时页面未正常渲染，产生空白截图，已不纳入产物；因此该子流程标记为未验证。主页面 390px 渲染已实际失败，见 [`11-main-mobile-390.png`](./screenshots/11-main-mobile-390.png)。
- 未进行真实外部部署、跨设备真机网络和第三方 App Store 连接验收；本轮范围为本地真实 Web 页面和本地数据链路。
- 未进行完整屏幕阅读器语义审计；本轮已做桌面/移动视口、点击流程和页面内容验收。

## 建议修复顺序（本轮未实施）

1. 在任何写入前强校验必填字段、唯一 ID 和窗口边界；重复或窗口外数据应明确拒绝并保留失败审计。
2. 拆分导出文件失败与导出成功格式错乱的聚合规则，重新校准同义聚合/混合拆分，并确保六簇趋势按窗口计算。
3. 将后续 48 小时建模为独立窗口，保留基线、当前和后续的可比较快照，避免追加覆盖当前结论。
4. 在证据卡片显式展示版本、窗口起止时间、来源、唯一 ID 和原文；低置信度簇不得自动输出“缓解/加重”等强趋势结论。
5. 修复 390px 下的横向溢出、裁切和关键控件可见性，再补做移动端完整关键流程验收。

## Git 状态与变更边界

验收前 `git status --short`：

```text
 M .env.example
 M .gitignore
 M .vercelignore
 M PROJECT_BRIEF.md
 M README.md
 M docs/index.html
 M feedback_triage_agent/models.py
 M feedback_triage_agent/rules.py
 M feedback_triage_agent/templates/index.html
 M feedback_triage_agent/templates/results.html
 M feedback_triage_agent/web_app.py
 M tests/test_rules.py
 M tests/test_web_app.py
?? feedback_triage_agent/observation.py
?? feedback_triage_agent/static/risk_workspace.css
?? feedback_triage_agent/static/risk_workspace.js
?? feedback_triage_agent/templates/risk_base.html
?? feedback_triage_agent/templates/task_index.html
?? feedback_triage_agent/templates/workspace.html
?? tests/test_observation.py
?? tests/test_risk_workbench.py
```

验收后 `git status --short`：

```text
 M .env.example
 M .gitignore
 M .vercelignore
 M PROJECT_BRIEF.md
 M README.md
 M docs/index.html
 M feedback_triage_agent/models.py
 M feedback_triage_agent/rules.py
 M feedback_triage_agent/templates/index.html
 M feedback_triage_agent/templates/results.html
 M feedback_triage_agent/web_app.py
 M tests/test_rules.py
 M tests/test_web_app.py
?? artifacts/
?? feedback_triage_agent/observation.py
?? feedback_triage_agent/static/risk_workspace.css
?? feedback_triage_agent/static/risk_workspace.js
?? feedback_triage_agent/templates/risk_base.html
?? feedback_triage_agent/templates/task_index.html
?? feedback_triage_agent/templates/workspace.html
?? tests/test_observation.py
?? tests/test_risk_workbench.py
```

验收期间未修改业务代码，未重构，未提交，未推送，未部署；仅新增 `artifacts/acceptance_v1.0/` 下的验收数据、截图、兼容接口输出和本报告。现有修改均予以保留。
