# Release Feedback Risk Workbench v1.0 静态演示

静态首页 `/` 和示例工作台 `/demo/` 沿用当前主产品的三个 Jinja 模板、CSS 和交互脚本。构建时调用现有演示任务生成逻辑，在临时目录导入仓库的 [基线、当前、后续三个 48h 验收 CSV](../artifacts/acceptance_v1.0/data/)。两轮比较、问题簇、原文证据、负责人示例和复核留痕来自这次重放。导入与审计时间标为构建阶段，原文证据保留样例窗口日期。

## 构建与预览

从仓库根目录用 Python 3.12 运行以下命令。

```bash
python -m pip install -r netlify-demo/requirements.txt
python -m netlify-demo.build
python -m http.server 8765 --bind 127.0.0.1 --directory netlify-demo/dist
```

打开 [本机静态预览](http://127.0.0.1:8765/)。

Git 构建使用根目录的 [netlify.toml](../netlify.toml)。Netlify 的 Base directory 选仓库根目录，Publish directory 为 `netlify-demo/dist`。构建输出只有 HTML、CSS 和 JS，可将整个 `dist` 目录作为一个独立站点的站点根目录发布。当前仅执行了本地预览。 [Netlify 构建配置](https://docs.netlify.com/build/configure-builds/file-based-configuration/) · [Netlify 手动部署](https://docs.netlify.com/deploy/create-deploys/)

## 支持范围

| 路径 | 静态演示行为 |
| --- | --- |
| 首页 → 体验演示任务 → 风险总览 | 预置一条任务，展示三个 48h 验收窗口和两轮比较 |
| 问题簇 → 原文证据 | 展开成员证据并查看反馈 ID、版本、来源和窗口起止时间 |
| 人工复核 | 可预览确认、驳回、保持观察和更新处理动作。结果显示在当前表单内，刷新即清除。风险统计、负责人摘要和审计区继续显示构建时的样例 |
| 后续窗口验证 | 复核预览可跳到对应问题簇的后续对比。若后续窗口无对应簇，则跳到后续对比区 |
| 创建、导入和筛选 | 保留表单预览。演示数据固定为 48h、App Store 来源，创建、上传、筛选、合并和拆分控件均不可提交 |

浏览器仅请求静态文件。访问者的表单内容留在当前页面内，页面没有运行时 Python API 或服务器持久化。样例反馈、负责人和复核用于演示。

## 验收记录

基线为 [main @ 5305e7d](https://github.com/Rayna-RRR/feedback-triage-agent/commit/5305e7d4f4a4cce14341c0c407e229b5c66cf93f)，包含 [PR #16](https://github.com/Rayna-RRR/feedback-triage-agent/pull/16)。

- Python 3.12.14 下的 `python -m pytest` 为 263 passed、61 条依赖弃用或兼容性警告。
- Netlify CLI 27.18.0 的 `netlify build --offline` 与 `netlify serve --offline` 通过。两次构建的 6 个发布文件 SHA-256 一致。发布 CSS 与产品脚本逐字节匹配，两个 JS 均通过语法检查。
- Chromium 验证了 1440 × 1000、1061 × 720 和 390 × 844 的主路径、表单行为、直接导航和刷新。文档无横向溢出，页面内锚点可达，控制台错误与非静态请求均为 0。页面展示的 71 处成员证据回溯到 51 个验收样例 ID。
- 对照 [视觉收口截图](../artifacts/v1.0_visual_closure/screenshots/) 和同尺寸的本地 `main`。首页与工作台沿用相同字体、字号、面板与卡片样式。原桌面参考截图右侧有裁切，静态版按钮和内容完整显示。示例任务数据、演示说明和只读控件会改变部分文字的折行。

| 视口 | 截图 |
| --- | --- |
| 桌面 | [首页](screenshots/home-1440.png) · [风险总览](screenshots/workspace-1440.png) · [原文证据](screenshots/evidence-1440.png) · [后续验证](screenshots/followup-1440.png) |
| 390px | [首页](screenshots/home-390.png) · [工作台](screenshots/workspace-390.png) · [复核预览](screenshots/review-390.png) |
