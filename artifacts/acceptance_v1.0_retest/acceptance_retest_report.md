# Feedback Triage Agent 原验收复验报告

- 复验日期：2026-07-28
- 复验范围：原 `artifacts/acceptance_v1.0/data/` 数据、原验收预期、真实本地 Web 页面
- 原首次报告：`artifacts/acceptance_v1.0/acceptance_report.md`（保留，未覆盖）
- 复验状态：**PASS**

## 原验收预期命中

基线、当前、后续均为独立 48h 窗口，各 30 条；当前相对基线、后续相对当前分别计算，累计快照与增量重复导入不重复计数。

| 问题簇 | 基线 | 当前 | 后续 | 当前相对基线 | 后续相对当前 |
| --- | ---: | ---: | ---: | --- | --- |
| 导出文件失败 | 1 | 6 | 2 | 加重 | 缓解 |
| 回答被截断 | 0 | 4 | 4 | 新增 | 稳定 |
| 登录失败 | 4 | 4 | 6 | 稳定 | 加重 |
| 引用内容错误 | 7 | 2 | 1 | 缓解 | 缓解 |
| 模糊体验反馈（待复核） | 0 | 2 | 2 | 待复核／趋势暂不判定 | 待复核／趋势暂不判定 |
| 导出成功但格式错乱 | 2 | 2 | 2 | 稳定 | 稳定 |
| 正向或中性补足 | 16 | 10 | 13 | — | — |

真实页面还验证了：

- 累计快照重复导入：0 新写入、30 跳过、0 文件内重复、0 异常；页面和审计显示跳过原因。
- 异常门禁：重复 ID、窗口外时间、缺少正文均整批拒绝，当前窗口仍为 30 条，失败原因写入导入记录和审计。
- 原始证据直接展示反馈 ID、原文、来源、产品版本、所属窗口及窗口起止时间。
- 真实页面完成确认、驳回、负责人/处理状态更新、拆分、合并；刷新和应用重启后数据、审计和人工结果仍在。
- `/run` 与 `/ask` 旧接口均通过本地 HTTP 兼容验证并生成原有报告产物。
- 390px 下页面文档和 body 的 `scrollWidth` 均为 390，无整体横向滚动；导入、证据和人工操作控件保持可用。桌面端关键页面同样完成检查。

## 自动化检查

- `./.venv/bin/python -m pytest`：`141 passed in 3.09s`
- Python 编译检查：通过
- JavaScript `node --check`：通过
- `git diff --check`：通过
- 仓库无额外 lint/build/test 配置；`pyproject.toml` 的 pytest 配置已由全量测试覆盖。

## 原始数据哈希

修复前后 SHA-256 一致，六个文件均未修改：

```text
f65e1960b2772752df776f5bd49b86420062830177ed2cc02effe5ecf3954eb9  data/baseline_48h.csv
8597cee4ad516817c3aeed1dd4ce725f17e846aad36dbe5ee2303c5dd3bbf59d  data/current_48h.csv
dba53b71ae9a929419e7bdf5cdb0228e22a5a38c65a4ecb83b97b2ffe44f4ce4  data/followup_48h.csv
a4885fab0080437b53fc14073b365451adfa79c12c2321a5a684db6225467d07  data/invalid_duplicate_id.csv
653d5a917bf535ffbdfe4ad8bcfbc1568c75c05c7c07e0a971848e38130942c5  data/invalid_missing_review_text.csv
5991f353663213985e4a3d2c23738b570c81f7a4179c0c1301a32913855088ec  data/invalid_out_of_window.csv
```

本目录中的 `observation_tasks/` 保存真实 Web 复验状态，`legacy_runs/` 保存 `/run`、`/ask` 复验产物。
