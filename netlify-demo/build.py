"""Render the main workbench with the repository's acceptance demo task."""

from hashlib import sha256
from pathlib import Path
from shutil import copyfile, rmtree
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bs4 import BeautifulSoup, Tag

from feedback_triage_agent import __version__, observation, web_app


DEMO_DIR = Path(__file__).resolve().parent
PUBLISH_DIR = DEMO_DIR / "dist"
ASSETS = [
    web_app.STATIC_DIR / "risk_workspace.css",
    web_app.STATIC_DIR / "risk_workspace.js",
    DEMO_DIR / "static" / "demo.css",
    DEMO_DIR / "static" / "demo.js",
]
STORAGE_NOTICE = "静态演示使用仓库验收样例生成。人工复核仅在当前页面预览，刷新即清除。"


def element(root: Tag, selector: str) -> Tag:
    node = root.select_one(selector)
    if node is None:
        raise ValueError(f"Workbench template is missing {selector}")
    return node


def replace_copy(root: Tag, changes: dict[str, str]) -> None:
    for selector, text in changes.items():
        element(root, selector).string = text


def render_page(template: str, version: str, **context) -> BeautifulSoup:
    html = web_app.templates.env.get_template(template).render(
        **context,
        url_for=lambda _route, path: f"/static/{path}",
        static_asset_version=version,
        version=__version__,
        deployment_label="静态演示",
        storage_notice=STORAGE_NOTICE,
    )
    page = BeautifulSoup(html, "html.parser")
    routes = {
        "/demo": "/demo/",
        f"/tasks/{web_app.DEMO_TASK_ID}": "/demo/",
    }
    for link in page.select('a[href^="/"]:not([href="/"])'):
        link["href"] = routes[link["href"]]
    # A dialog-method form never navigates or sends its fields over HTTP.
    for form in page.select("form"):
        form.attrs.pop("action", None)
        form.attrs.pop("enctype", None)
        form["method"] = "dialog"

    page.head.append(
        page.new_tag("link", rel="stylesheet", href=f"/static/demo.css?v={version}")
    )
    return page


def disable_controls(form: Tag) -> None:
    for control in form.select("button, input, select, textarea"):
        control["disabled"] = ""


def render_home(tasks: list, version: str) -> BeautifulSoup:
    page = render_page("task_index.html", version, tasks=tasks)
    replace_copy(
        page,
        {
            ".risk-hero .risk-button": "查看任务表单",
            ".risk-demo-callout p": (
                "使用仓库验收样例展示基线、当前与后续三个 48h 窗口，"
                "可查看问题簇、原文证据、人工复核与后续验证。数据仅供演示。"
            ),
            ".risk-metric-grid article:first-child small": "来自仓库验收样例",
            ".risk-metric-grid article:nth-child(3) small": "演示任务已预载三份快照",
            "#create-task-title": "创建版本观察任务 · 表单预览",
            "#create-task .risk-section-heading p:last-child": "静态演示使用预置任务。以下展示创建任务所需的字段。",
            ".risk-form-actions p": "此表单仅供查看。可从首页体验预置的演示任务。",
            ".risk-form-actions button": "创建并进入工作台（预览）",
        },
    )
    element(page, 'nav a[href="#create-task"]').contents[-1].replace_with("查看任务表单")
    disable_controls(element(page, "[data-task-form]"))
    return page


def prepare_review_panels(page: BeautifulSoup, workspace: dict) -> None:
    followup_cards = page.select("#followup-round .risk-followup-card")
    followup_clusters = workspace["followup_comparison"]["clusters"]
    followup_ids = set()
    for card, cluster in zip(followup_cards, followup_clusters, strict=True):
        card["id"] = f"followup-{cluster['cluster_id']}"
        followup_ids.add(cluster["cluster_id"])

    clusters = workspace["clusters"]
    for cluster in clusters:
        cluster_id = cluster["cluster_id"]
        panel = element(page, f"#cluster-{cluster_id} .risk-action-panel")
        panel["id"] = f"review-{cluster_id}"
        form = element(panel, "[data-cluster-action-form]")
        form["autocomplete"] = "off"
        form["data-review-status"] = cluster["review_status"]
        form["data-followup"] = (
            f"#followup-{cluster_id}" if cluster_id in followup_ids else "#followup-round"
        )
        for option in form.select('option[value="merge"], option[value="split"]'):
            option["disabled"] = ""
            option.string = f"{option.get_text()}（静态版不可用）"
        element(form, 'textarea[name="note"]')["placeholder"] = "填写本次演示的判断依据"
        element(form, 'button[type="submit"]')["disabled"] = ""
        replace_copy(
            panel,
            {
                "summary": "人工复核演示",
                ".risk-action-submit p": "操作结果仅在此表单预览，刷新后清除。",
                ".risk-action-submit button": "预览本次复核",
            },
        )
        form.append(
            page.new_tag("div", attrs={"data-demo-review-result": "", "role": "status"})
        )

    target = next(
        (cluster for cluster in clusters if cluster.get("last_human_action")),
        clusters[0],
    )
    review_link = element(page, 'nav a[href="#clusters"] + a[href="#clusters"]')
    review_link["href"] = f"#review-{target['cluster_id']}"
    review_link["data-demo-review-link"] = ""
    followup_link = page.new_tag("a", href="#followup-round")
    icon = page.new_tag("span", attrs={"class": "risk-nav-icon", "aria-hidden": "true"})
    icon.string = "↗"
    followup_link.extend([icon, "后续验证"])
    review_link.insert_after(followup_link)


def render_workspace(workspace: dict, version: str) -> BeautifulSoup:
    # The replay timestamps vary by build. The fixture evidence keeps its own dates.
    for entry in workspace["imports"]:
        entry["imported_at"] = "构建时"
    for event in workspace["audit_events"]:
        event["timestamp"] = "构建时重放"
    page = render_page(
        "workspace.html",
        version,
        workspace=workspace,
        task=workspace["task"],
        selected_window=workspace["selected_window"],
        selected_source=workspace["selected_source"],
        sources=workspace["sources"],
        is_demo=True,
    )
    replace_copy(
        page,
        {
            ".risk-demo-notice strong": "这是预生成的示例任务",
            ".risk-demo-notice p": "内容来自仓库验收样例，用于展示工作流程。样例中的反馈、责任人与复核均为演示数据。",
            ".risk-workspace-header .risk-button": "查看问题簇",
            ".risk-toolbar > p": "验收样例仅含 48h 快照，三个窗口的反馈来源均为 App Store。",
            "#import-title": "观察窗口导入记录",
            "#import-feedback .risk-section-heading p:last-child": "三个窗口在构建时从仓库验收 CSV 导入。下方表单为只读预览。",
            ".risk-import-guidance p": "静态演示使用下方列出的预置快照。",
            ".risk-import-guidance button": "校验并导入（预览）",
            ".risk-table caption": "验收样例导入记录",
            ".risk-table thead th:first-child": "生成阶段",
            "#audit-log .risk-section-heading p:last-child": "这里展示构建时重放的导入、规则判断与预置复核。表单中的复核预览只显示在当前页面。",
        },
    )
    element(page, ".risk-workspace-header .risk-button")["href"] = "#clusters"
    element(page, 'nav a[href="#import-feedback"]').contents[-1].replace_with("导入记录")
    for stamp in page.select(".risk-timeline time"):
        stamp.name = "small"
    element(page, "[data-import-guidance]").attrs.pop("data-import-guidance")
    for selector in (".risk-toolbar form", ".risk-import-form"):
        disable_controls(element(page, selector))

    prepare_review_panels(page, workspace)
    noscript = page.new_tag("noscript")
    noscript.string = "启用 JavaScript 后可预览人工复核。"
    element(page, ".risk-demo-notice > div").append(noscript)
    element(page, 'script[src*="risk_workspace.js"]').insert_after(
        page.new_tag("script", src=f"/static/demo.js?v={version}")
    )
    return page


def build() -> None:
    with TemporaryDirectory(prefix="workbench-fixture-") as directory:
        root = Path(directory)
        with patch.object(web_app, "OBSERVATION_TASKS_DIR", root):
            task = web_app.ensure_demo_task()
        workspace = observation.build_workspace(task, selected_window=48)
        tasks = observation.list_tasks(root)

    version = sha256(b"".join(asset.read_bytes() for asset in ASSETS)).hexdigest()[:12]
    home = render_home(tasks, version)
    demo = render_workspace(workspace, version)
    with TemporaryDirectory(prefix=".build-", dir=DEMO_DIR) as directory:
        staging = Path(directory) / "dist"
        (staging / "demo").mkdir(parents=True)
        (staging / "static").mkdir()
        (staging / "index.html").write_text(str(home), encoding="utf-8")
        (staging / "demo" / "index.html").write_text(str(demo), encoding="utf-8")
        for asset in ASSETS:
            copyfile(asset, staging / "static" / asset.name)
        if PUBLISH_DIR.exists():
            rmtree(PUBLISH_DIR)
        staging.replace(PUBLISH_DIR)
    print("Static Workbench generated in netlify-demo/dist")


if __name__ == "__main__":
    build()
