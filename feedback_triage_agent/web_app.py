from __future__ import annotations

from contextlib import asynccontextmanager
import re
import shutil
import os
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from feedback_triage_agent import __version__
from feedback_triage_agent import observation
from feedback_triage_agent.agent import FeedbackTriageAgent
from feedback_triage_agent.html_report import (
    ReportInputError,
    generate_html_report,
    parse_bullet_map,
    parse_run_log,
)
from feedback_triage_agent.task_parser import (
    parse_ask_task,
)
from feedback_triage_agent.rules import REQUIRED_FIELDS
from feedback_triage_agent.review import apply_review_decisions
from feedback_triage_agent.web_models import DownloadFile, WebRunData


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
LOCAL_WEB_RUNS_DIR = DATA_DIR / "web_runs"
DEPLOY_WEB_RUNS_DIR = Path("/tmp/feedback-triage-runs")
LOCAL_OBSERVATION_TASKS_DIR = DATA_DIR / "observation_tasks"
DEPLOY_OBSERVATION_TASKS_DIR = Path("/tmp/feedback-risk-tasks")
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
STATIC_ASSET_VERSION = str(
    int(
        max(
            (STATIC_DIR / filename).stat().st_mtime
            for filename in ("app.css", "risk_workspace.css", "risk_workspace.js")
        )
    )
)

SAMPLE_FEEDBACK_PATH = DATA_DIR / "sample_feedback.csv"
AI_REVIEWS_PATH = DATA_DIR / "ai_app_reviews.csv"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_INPUT_ROWS = 5000
MAX_LLM_ROWS = 100
DEFAULT_RUN_RETENTION_HOURS = 24
DEFAULT_MAX_WEB_RUNS = 50

REQUIRED_WEB_OUTPUTS = [
    "issue_cards.md",
    "qa_report.md",
    "run_log.md",
    "triage_results.csv",
    "weekly_summary.md",
    "review_decisions.csv",
]
DOWNLOADS = [
    ("normalized_feedback.csv", "标准化输入 CSV"),
    ("issue_cards.md", "问题卡片 Markdown"),
    ("qa_report.md", "QA 报告 Markdown"),
    ("run_log.md", "运行日志 Markdown"),
    ("triage_results.csv", "结构化 CSV"),
    ("weekly_summary.md", "产品周报 Markdown"),
    ("review_decisions.csv", "人工复核决策模板"),
    ("triage_results_reviewed.csv", "已复核结构化 CSV"),
    ("review_summary.md", "人工复核摘要"),
    ("report.html", "静态 HTML 报告"),
    ("outputs.zip", "全部输出 zip"),
]


def boolish(value: object) -> bool:
    normalized = str(value).strip().lower()
    return normalized in {"true", "1", "yes", "y", "on"}


def env_int(name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value >= minimum else default


def resolve_web_runs_dir() -> Path:
    configured = os.getenv("FEEDBACK_TRIAGE_WEB_RUNS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if os.getenv("VERCEL"):
        return DEPLOY_WEB_RUNS_DIR
    return LOCAL_WEB_RUNS_DIR


def resolve_observation_tasks_dir() -> Path:
    configured = os.getenv("FEEDBACK_RISK_TASKS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if os.getenv("VERCEL"):
        return DEPLOY_OBSERVATION_TASKS_DIR
    return LOCAL_OBSERVATION_TASKS_DIR


WEB_RUNS_DIR = resolve_web_runs_dir()
OBSERVATION_TASKS_DIR = resolve_observation_tasks_dir()
RUN_RETENTION_HOURS = env_int(
    "FEEDBACK_TRIAGE_RUN_RETENTION_HOURS",
    DEFAULT_RUN_RETENTION_HOURS,
)
MAX_WEB_RUNS = env_int("FEEDBACK_TRIAGE_MAX_WEB_RUNS", DEFAULT_MAX_WEB_RUNS)


def web_llm_enabled() -> bool:
    return bool(web_llm_status()["enabled"])


def web_llm_status() -> Dict[str, object]:
    deepseek_api_key_present = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
    web_llm_flag_enabled = boolish(os.getenv("FEEDBACK_TRIAGE_WEB_LLM_ENABLED", ""))
    enabled = deepseek_api_key_present and web_llm_flag_enabled
    if enabled:
        label = "DeepSeek 已启用"
        detail = "当前 Web App 进程已读取 API key，且 Web LLM 开关已启用。"
        badge_class = "status-success"
    elif deepseek_api_key_present:
        label = "API key 已读取，Web LLM 未启用"
        detail = "当前 Web App 进程已读取 API key；还需要设置 FEEDBACK_TRIAGE_WEB_LLM_ENABLED=true 并重启 Web App。"
        badge_class = "status-warning"
    elif web_llm_flag_enabled:
        label = "API key 未读取"
        detail = "当前 Web App 进程已启用 Web LLM 开关，但没有读取到非空 DEEPSEEK_API_KEY。"
        badge_class = "status-warning"
    else:
        label = "本地规则模式"
        detail = "当前 Web App 进程没有读取到非空 DEEPSEEK_API_KEY，且 Web LLM 开关未启用。"
        badge_class = "status-info"
    return {
        "enabled": enabled,
        "deepseek_api_key_present": deepseek_api_key_present,
        "web_llm_flag_enabled": web_llm_flag_enabled,
        "label": label,
        "detail": detail,
        "badge_class": badge_class,
    }


def deployment_label() -> str:
    return "线上 Demo" if os.getenv("VERCEL") else "本地运行"


def storage_notice() -> str:
    if os.getenv("VERCEL"):
        return "线上 Demo 使用临时文件存储；平台重启或实例回收后任务可能丢失，请勿上传敏感或生产数据。"
    return f"任务保存在本机 {OBSERVATION_TASKS_DIR}；当前版本不接数据库、账号或付费存储。"


def yes_no_label(value: object) -> str:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return "是"
    if normalized in {"false", "0", "no", "n", "off"}:
        return "否"
    return str(value)


def parser_source_label(value: object) -> str:
    labels = {
        "direct": "直接运行",
        "rules": "本地规则",
        "deepseek": "DeepSeek",
    }
    return labels.get(str(value).strip().lower(), str(value))


def status_label(value: object) -> str:
    labels = {
        "success": "成功",
        "warning": "提醒",
        "error": "失败",
    }
    return labels.get(str(value).strip().lower(), str(value))


def action_label(value: object) -> str:
    labels = {
        "validate_schema": "校验字段",
        "classify_feedback": "开始分类",
        "detect_badcases": "识别复核样本",
        "generate_issue_cards": "生成问题卡片",
        "qa_check": "执行 QA 检查",
        "export_report": "导出报告",
        "done": "完成",
        "stop": "停止",
    }
    return labels.get(str(value).strip(), str(value))


def step_label(value: object) -> str:
    labels = {
        "load_feedback": "读取反馈",
        "validate_schema": "校验字段",
        "classify_feedback": "反馈分类",
        "detect_badcases": "识别复核样本",
        "generate_issue_cards": "生成问题卡片",
        "qa_check": "QA 检查",
        "export_report": "导出报告",
    }
    match = re.match(r"^(\d+)\.\s*(.+)$", str(value).strip())
    if not match:
        return labels.get(str(value), str(value))
    index, name = match.groups()
    return f"{index}. {labels.get(name, name)}"


def step_result_label(value: object) -> str:
    labels = {
        "load_feedback": "已读取输入数据",
        "validate_schema": "字段结构已校验",
        "classify_feedback": "已完成问题分类",
        "detect_badcases": "已识别需要人工复核的样本",
        "generate_issue_cards": "已生成问题卡片",
        "qa_check": "已完成质量检查",
        "export_report": "已导出报告文件",
    }
    match = re.match(r"^\d+\.\s*(.+)$", str(value).strip())
    key = match.group(1) if match else str(value)
    return labels.get(key, str(value))


def decorate_run_steps(steps: List[Dict[str, str]]) -> List[Dict[str, str]]:
    decorated = []
    for step in steps:
        row = dict(step)
        row["step_label"] = step_label(step.get("step", ""))
        row["result_label"] = step_result_label(step.get("step", ""))
        row["status_label"] = status_label(step.get("status", ""))
        row["next_action_label"] = action_label(step.get("next_action", ""))
        decorated.append(row)
    return decorated


def is_run_dir_name(name: str) -> bool:
    return bool(
        re.match(r"^run_\d{8}_\d{6}(?:_[A-Za-z0-9_-]+)*(?:_\d{2})?$", name)
    )


def cleanup_web_runs(now: Optional[float] = None) -> None:
    if not WEB_RUNS_DIR.exists():
        return

    current_time = time.time() if now is None else now
    cutoff = current_time - (RUN_RETENTION_HOURS * 60 * 60)
    run_dirs = [
        path
        for path in WEB_RUNS_DIR.iterdir()
        if path.is_dir() and is_run_dir_name(path.name)
    ]

    remaining_dirs = []
    for run_dir in run_dirs:
        try:
            modified_at = run_dir.stat().st_mtime
        except OSError:
            continue
        if modified_at < cutoff:
            shutil.rmtree(run_dir, ignore_errors=True)
        else:
            remaining_dirs.append((modified_at, run_dir))

    remaining_dirs.sort(key=lambda item: item[0], reverse=True)
    for _modified_at, run_dir in remaining_dirs[MAX_WEB_RUNS:]:
        shutil.rmtree(run_dir, ignore_errors=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cleanup_web_runs()
    OBSERVATION_TASKS_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Feedback Triage Agent Web App",
    version=__version__,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["static_asset_version"] = STATIC_ASSET_VERSION


def render_index(request: Request, error: Optional[str] = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "error": error,
            "version": __version__,
            "deployment_label": deployment_label(),
            "sample_exists": SAMPLE_FEEDBACK_PATH.exists(),
            "ai_reviews_exists": AI_REVIEWS_PATH.exists(),
            "web_llm_enabled": web_llm_enabled(),
            "web_llm_status": web_llm_status(),
            "web_runs_dir": str(WEB_RUNS_DIR),
            "run_retention_hours": RUN_RETENTION_HOURS,
            "max_upload_mb": int(MAX_UPLOAD_BYTES / (1024 * 1024)),
            "max_input_rows": MAX_INPUT_ROWS,
            "max_llm_rows": MAX_LLM_ROWS,
        },
        status_code=status_code,
    )


def render_task_index(
    request: Request,
    *,
    message: Optional[str] = None,
    error: Optional[str] = None,
    status_code: int = 200,
):
    try:
        tasks = observation.list_tasks(OBSERVATION_TASKS_DIR)
    except (OSError, ValueError) as exc:
        tasks = []
        error = error or f"观察任务目录无法读取：{exc}"
        status_code = max(status_code, 500)
    return templates.TemplateResponse(
        request,
        "task_index.html",
        {
            "tasks": tasks,
            "message": message,
            "error": error,
            "version": __version__,
            "deployment_label": deployment_label(),
            "storage_notice": storage_notice(),
        },
        status_code=status_code,
    )


def parse_observation_window(value: object, *, default: int = 72) -> int:
    raw_value = str(value).strip()
    if not raw_value:
        return default
    try:
        window = int(raw_value)
    except ValueError as exc:
        raise ValueError("观察窗口必须是 24、48 或 72 小时。") from exc
    if window not in observation.SUPPORTED_WINDOWS:
        raise ValueError("观察窗口必须是 24、48 或 72 小时。")
    return window


def render_task_workspace(
    request: Request,
    task_id: str,
    *,
    selected_window: int = 72,
    selected_source: str = "all",
    message: Optional[str] = None,
    error: Optional[str] = None,
    status_code: int = 200,
):
    task = observation.load_task(OBSERVATION_TASKS_DIR, task_id)
    workspace = observation.build_workspace(
        task,
        selected_window=selected_window,
        selected_source=selected_source,
    )
    return templates.TemplateResponse(
        request,
        "workspace.html",
        {
            "task": workspace["task"],
            "workspace": workspace,
            "selected_window": workspace["selected_window"],
            "selected_source": workspace["selected_source"],
            "sources": workspace["sources"],
            "message": message,
            "error": error,
            "version": __version__,
            "deployment_label": deployment_label(),
            "storage_notice": storage_notice(),
        },
        status_code=status_code,
    )


def clean_form_value(
    value: object,
    label: str,
    *,
    maximum: int,
    required: bool = False,
) -> str:
    cleaned = str(value or "").strip()
    if required and not cleaned:
        raise ValueError(f"{label}不能为空。")
    if len(cleaned) > maximum:
        raise ValueError(f"{label}不能超过 {maximum} 个字符。")
    return cleaned


def task_workspace_url(
    task_id: str,
    *,
    selected_window: int = 72,
    selected_source: str = "all",
    message: Optional[str] = None,
    error: Optional[str] = None,
    fragment: str = "",
) -> str:
    parameters = {
        "window": str(selected_window),
        "source": selected_source or "all",
    }
    if message:
        parameters["message"] = message
    if error:
        parameters["error"] = error
    suffix = f"#{fragment}" if fragment else ""
    return f"/tasks/{task_id}?{urlencode(parameters)}{suffix}"


def selection_from_request(
    request: Request,
    selected_window: Optional[str],
    selected_source: Optional[str],
) -> Tuple[int, str]:
    window_value = selected_window or ""
    source_value = selected_source or ""
    if not window_value or not source_value:
        referer = request.headers.get("referer", "")
        if referer:
            query = parse_qs(urlparse(referer).query)
            window_value = window_value or query.get("window", [""])[0]
            source_value = source_value or query.get("source", [""])[0]
    return parse_observation_window(window_value), source_value.strip() or "all"


def append_observation_failure(
    task: Dict[str, object],
    *,
    action: str,
    message: str,
    details: Optional[Dict[str, object]] = None,
) -> None:
    observation.append_audit_event(
        task,
        action,
        message,
        details=details or {},
    )


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    return cleaned.strip("-")[:40]


def create_run_dir(output_name: str = "") -> Path:
    cleanup_web_runs()
    WEB_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = sanitize_name(output_name)
    base_name = f"run_{timestamp}" + (f"_{suffix}" if suffix else "")
    run_dir = WEB_RUNS_DIR / base_name
    counter = 2
    while run_dir.exists():
        run_dir = WEB_RUNS_DIR / f"{base_name}_{counter:02d}"
        counter += 1
    run_dir.mkdir(parents=True)
    return run_dir


def cleanup_failed_run(run_dir: Path) -> None:
    shutil.rmtree(run_dir, ignore_errors=True)


def validate_run_id(run_id: str) -> None:
    if not is_run_dir_name(run_id):
        raise ValueError("运行目录名称不合法。")


def get_run_dir(run_id: str) -> Path:
    validate_run_id(run_id)
    run_dir = WEB_RUNS_DIR / run_id
    if not run_dir.exists():
        raise FileNotFoundError("找不到这次运行的输出目录。")
    return run_dir


def validate_csv_input(path: Path, *, require_schema: bool = True) -> int:
    try:
        dataframe = pd.read_csv(path, nrows=MAX_INPUT_ROWS + 1)
    except Exception as exc:
        raise ValueError(f"CSV 无法读取，请检查文件编码和格式: {exc}") from exc
    missing = [field for field in REQUIRED_FIELDS if field not in dataframe.columns]
    if require_schema and missing:
        raise ValueError("CSV 缺少必填字段: " + "，".join(missing))
    if len(dataframe) > MAX_INPUT_ROWS:
        raise ValueError(f"CSV 超过 {MAX_INPUT_ROWS} 行限制，请拆分后重试。")
    return len(dataframe)


def save_upload(upload_file: UploadFile, destination: Path) -> None:
    total_bytes = 0
    with destination.open("wb") as file:
        while chunk := upload_file.file.read(1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_BYTES:
                raise ValueError("上传文件超过 5 MB 限制。")
            file.write(chunk)


def resolve_builtin_source(data_source: str) -> Path:
    if data_source == "sample":
        return SAMPLE_FEEDBACK_PATH
    if data_source == "ai_reviews":
        return AI_REVIEWS_PATH
    raise ValueError("没有选择数据源。")


def create_outputs_zip(output_dir: Path) -> Path:
    zip_path = output_dir / "outputs.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, _label in DOWNLOADS:
            if filename == "outputs.zip":
                continue
            path = output_dir / filename
            if path.exists():
                archive.write(path, arcname=filename)
    return zip_path


def verify_outputs(output_dir: Path) -> None:
    missing = [filename for filename in REQUIRED_WEB_OUTPUTS if not (output_dir / filename).exists()]
    if missing:
        raise ValueError("Agent 输出文件缺失: " + "，".join(missing))


def execute_agent_run(
    input_path: Path,
    run_dir: Path,
    *,
    llm_requested: bool,
    generate_html: bool,
    normalize_input: bool = False,
    input_name: str = "",
    ask_parser_source: str = "direct",
    ask_parser_model: str = "",
    ask_parser_fallback_reason: str = "",
    ask_parser_prompt_tokens: int = 0,
    ask_parser_completion_tokens: int = 0,
    ask_parser_total_tokens: int = 0,
) -> None:
    row_count = validate_csv_input(input_path, require_schema=not normalize_input)
    if llm_requested and row_count > MAX_LLM_ROWS:
        raise ValueError(f"启用 LLM 时最多处理 {MAX_LLM_ROWS} 条反馈，请拆分输入或使用规则模式。")
    agent = FeedbackTriageAgent(
        input_path=input_path,
        output_dir=run_dir,
        llm_requested=llm_requested,
        normalize_input=normalize_input,
        input_name=input_name or input_path.name,
        ask_parser_source=ask_parser_source,
        ask_parser_model=ask_parser_model,
        ask_parser_fallback_reason=ask_parser_fallback_reason,
        ask_parser_prompt_tokens=ask_parser_prompt_tokens,
        ask_parser_completion_tokens=ask_parser_completion_tokens,
        ask_parser_total_tokens=ask_parser_total_tokens,
    )
    state = agent.run()
    if state.run_log and state.run_log[-1].status == "error":
        last_step = state.run_log[-1]
        detail = "；".join(last_step.warnings) or last_step.output_summary
        raise ValueError(detail)

    verify_outputs(run_dir)
    if generate_html:
        generate_html_report(run_dir)
    create_outputs_zip(run_dir)


def frame_distribution(values: pd.Series) -> List[Dict[str, object]]:
    counts = values.fillna("").astype(str).replace("", "未填写").value_counts()
    max_count = int(counts.max()) if len(counts) else 0
    rows = []
    for name, count in counts.items():
        rows.append(
            {
                "name": name,
                "count": int(count),
                "percent": 0 if max_count == 0 else int(round(int(count) / max_count * 100)),
            }
        )
    return rows


def read_results(run_id: str) -> WebRunData:
    output_dir = get_run_dir(run_id)
    verify_outputs(output_dir)

    reviewed_path = output_dir / "triage_results_reviewed.csv"
    results_path = reviewed_path if reviewed_path.exists() else output_dir / "triage_results.csv"
    results = pd.read_csv(results_path).fillna("")
    qa_values = parse_bullet_map((output_dir / "qa_report.md").read_text(encoding="utf-8"))
    run_steps = decorate_run_steps(
        parse_run_log((output_dir / "run_log.md").read_text(encoding="utf-8"))
    )

    review_mask = (
        results["needs_human_review"].map(boolish)
        if "needs_human_review" in results
        else pd.Series(False, index=results.index)
    )
    review_items = [
        {
            "id": row.get("id", ""),
            "record_key": row.get("record_key", row.get("id", "")),
            "issue_category": row.get("issue_category", ""),
            "priority": row.get("priority", ""),
            "human_review_reasons": row.get("human_review_reasons", ""),
            "review_status": row.get("review_status", "pending"),
            "risk_class": risk_class(row.get("priority", ""), row.get("human_review_reasons", "")),
        }
        for _, row in results[review_mask].iterrows()
    ]

    issue_cards = [
        {
            "id": row.get("id", ""),
            "record_key": row.get("record_key", row.get("id", "")),
            "issue_category": row.get("issue_category", ""),
            "priority": row.get("priority", ""),
            "summary": row.get("summary", ""),
            "product_suggestion": row.get("product_suggestion", ""),
            "needs_human_review": boolish(row.get("needs_human_review", "")),
            "human_review_reasons": row.get("human_review_reasons", ""),
            "review_status": row.get("review_status", ""),
        }
        for _, row in results.iterrows()
    ]

    downloads = [
        DownloadFile(name=name, label=label, exists=(output_dir / name).exists())
        for name, label in DOWNLOADS
    ]

    metrics: Dict[str, object] = {
        "total_samples": qa_values.get("总样本数", len(results)),
        "valid_samples": qa_values.get("有效样本数", len(results)),
        "issue_cards": len(issue_cards),
        "human_review_count": len(review_items),
        "reviewed_count": (
            int(results["review_status"].eq("reviewed").sum())
            if "review_status" in results
            else 0
        ),
        "open_review_count": (
            int(results["review_status"].eq("open").sum())
            if "review_status" in results
            else len(review_items)
        ),
        "llm_used": qa_values.get("是否使用 LLM", "False"),
        "fallback": qa_values.get("是否 fallback 到 rules.py", "False"),
        "ask_parser_source": qa_values.get("解析来源", "direct"),
        "ask_parser_model": qa_values.get("解析模型", "未使用"),
        "ask_parser_tokens": qa_values.get("解析总 tokens", 0),
        "llm_tokens": qa_values.get("反馈初稿总 tokens", 0),
        "output_dir": str(output_dir),
    }
    metrics["llm_used_label"] = yes_no_label(metrics["llm_used"])
    metrics["fallback_label"] = yes_no_label(metrics["fallback"])
    metrics["ask_parser_source_label"] = parser_source_label(metrics["ask_parser_source"])

    return WebRunData(
        run_id=run_id,
        output_dir=output_dir,
        metrics=metrics,
        category_distribution=frame_distribution(results["issue_category"]),
        priority_distribution=frame_distribution(results["priority"]),
        review_items=review_items,
        issue_cards=issue_cards,
        run_steps=run_steps,
        downloads=downloads,
    )


def risk_class(priority: object, reasons: object) -> str:
    text = f"{priority} {reasons}"
    if "P0" in text:
        return "risk-p0"
    if "低置信度" in text:
        return "risk-low-confidence"
    if "多个问题" in text:
        return "risk-multi"
    return ""


@app.get("/")
def index(
    request: Request,
    message: str = "",
    error: str = "",
):
    return render_task_index(
        request,
        message=message or None,
        error=error or None,
    )


@app.post("/tasks")
def create_observation_task(
    request: Request,
    name: str = Form(""),
    product_name: str = Form(""),
    baseline_version: str = Form(""),
    current_version: str = Form(""),
    baseline_window_start: str = Form(""),
    baseline_window_end: str = Form(""),
    current_window_start: str = Form(""),
    current_window_end: str = Form(""),
    followup_window_start: str = Form(""),
    followup_window_end: str = Form(""),
    comparison_basis: str = Form("equivalent_window"),
    comparison_note: str = Form(""),
    change_summary: str = Form(""),
):
    try:
        task = observation.create_task(
            OBSERVATION_TASKS_DIR,
            name=clean_form_value(name, "任务名称", maximum=120, required=True),
            product_name=clean_form_value(
                product_name,
                "产品名称",
                maximum=120,
                required=True,
            ),
            baseline_version=clean_form_value(
                baseline_version,
                "基线版本",
                maximum=80,
                required=True,
            ),
            current_version=clean_form_value(
                current_version,
                "当前版本",
                maximum=80,
                required=True,
            ),
            baseline_window_start=clean_form_value(
                baseline_window_start,
                "基线窗口开始时间",
                maximum=64,
                required=True,
            ),
            baseline_window_end=clean_form_value(
                baseline_window_end,
                "基线窗口结束时间",
                maximum=64,
                required=True,
            ),
            current_window_start=clean_form_value(
                current_window_start,
                "当前窗口开始时间",
                maximum=64,
                required=True,
            ),
            current_window_end=clean_form_value(
                current_window_end,
                "当前窗口结束时间",
                maximum=64,
                required=True,
            ),
            followup_window_start=clean_form_value(
                followup_window_start,
                "后续窗口开始时间",
                maximum=64,
            ),
            followup_window_end=clean_form_value(
                followup_window_end,
                "后续窗口结束时间",
                maximum=64,
            ),
            comparison_basis=clean_form_value(
                comparison_basis,
                "比较口径",
                maximum=32,
                required=True,
            ),
            comparison_note=clean_form_value(
                comparison_note,
                "其他口径说明",
                maximum=500,
            ),
            change_summary=clean_form_value(
                change_summary,
                "版本变化摘要",
                maximum=1200,
            ),
        )
    except ValueError as exc:
        return render_task_index(request, error=str(exc), status_code=400)
    except OSError:
        return render_task_index(
            request,
            error="观察任务无法保存，请检查当前存储目录后重试。",
            status_code=500,
        )

    return RedirectResponse(
        url=task_workspace_url(
            task["task_id"],
            message="观察任务已创建，请继续导入基线和当前反馈。",
        ),
        status_code=303,
    )


@app.get("/tasks/{task_id}")
def observation_workspace(
    request: Request,
    task_id: str,
    window: str = "72",
    source: str = "all",
    message: str = "",
    error: str = "",
):
    status_code = 200
    try:
        selected_window = parse_observation_window(window)
    except ValueError as exc:
        selected_window = 72
        error = error or str(exc)
        status_code = 400
    try:
        selected_source = clean_form_value(
            source or "all",
            "反馈来源",
            maximum=120,
            required=True,
        )
        return render_task_workspace(
            request,
            task_id,
            selected_window=selected_window,
            selected_source=selected_source,
            message=message or None,
            error=error or None,
            status_code=status_code,
        )
    except FileNotFoundError as exc:
        return render_task_index(request, error=str(exc), status_code=404)
    except ValueError as exc:
        return render_task_index(request, error=str(exc), status_code=400)


@app.post("/tasks/{task_id}/imports")
def import_observation_feedback(
    request: Request,
    task_id: str,
    window_kind: str = Form(""),
    observation_hours: str = Form(""),
    source: str = Form(""),
    import_mode: str = Form("cumulative"),
    file: Optional[UploadFile] = File(None),
):
    try:
        task = observation.load_task(OBSERVATION_TASKS_DIR, task_id)
    except FileNotFoundError as exc:
        return render_task_index(request, error=str(exc), status_code=404)
    except ValueError as exc:
        return render_task_index(request, error=str(exc), status_code=400)

    selected_window = 72
    selected_source = "all"
    temporary_path: Optional[Path] = None
    core_import_started = False
    try:
        selected_window = parse_observation_window(observation_hours)
        clean_window_kind = clean_form_value(
            window_kind,
            "数据窗口",
            maximum=16,
            required=True,
        )
        clean_source = clean_form_value(
            source,
            "反馈来源",
            maximum=120,
            required=True,
        )
        selected_source = clean_source
        clean_mode = clean_form_value(
            import_mode or "cumulative",
            "导入方式",
            maximum=24,
            required=True,
        )
        if file is None or not file.filename:
            raise ValueError("请选择要上传的 CSV 文件。")
        if not file.filename.lower().endswith(".csv"):
            raise ValueError("上传文件必须是 CSV 格式。")

        with tempfile.NamedTemporaryFile(
            prefix="feedback-risk-",
            suffix=".csv",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        save_upload(file, temporary_path)
        core_import_started = True
        result = observation.add_import(
            task,
            source_path=temporary_path,
            window_kind=clean_window_kind,
            observation_hours=selected_window,
            source=clean_source,
            import_mode=clean_mode,
            filename=file.filename,
        )
    except (OSError, ValueError) as exc:
        error_message = (
            str(exc)
            if isinstance(exc, ValueError)
            else "上传文件无法保存，请稍后重试。"
        )
        if not core_import_started:
            try:
                append_observation_failure(
                    task,
                    action="导入失败",
                    message=error_message,
                    details={
                        "window_kind": window_kind,
                        "observation_hours": observation_hours,
                        "source": source,
                        "import_mode": import_mode or "cumulative",
                        "filename": file.filename if file else "",
                    },
                )
            except (OSError, ValueError):
                pass
        return RedirectResponse(
            url=task_workspace_url(
                task_id,
                selected_window=selected_window,
                selected_source=selected_source,
                error=error_message,
                fragment="import-feedback",
            ),
            status_code=303,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    message_text = (
        f"已导入 {result['accepted_count']} 条新反馈，"
        f"跳过 {result.get('skipped_count', 0)} 条完全相同的既有记录，"
        f"文件内重复 {result.get('within_file_duplicate_count', result['duplicate_count'])} 条，"
        f"异常 {result['error_count']} 条。"
    )
    if result.get("skip_reasons"):
        message_text += " 跳过原因：" + "；".join(result["skip_reasons"])
    return RedirectResponse(
        url=task_workspace_url(
            task_id,
            selected_window=selected_window,
            selected_source="all",
            message=message_text,
            fragment="import-feedback",
        ),
        status_code=303,
    )


@app.post("/tasks/{task_id}/clusters/{cluster_id}/actions")
def apply_observation_cluster_action(
    request: Request,
    task_id: str,
    cluster_id: str,
    action: str = Form(""),
    risk_level: str = Form(""),
    owner: str = Form(""),
    work_status: str = Form(""),
    next_action: str = Form(""),
    result: str = Form(""),
    target_cluster_id: str = Form(""),
    feedback_ids: str = Form(""),
    note: str = Form(""),
    selected_window: Optional[str] = Form(None),
    selected_source: Optional[str] = Form(None),
):
    try:
        task = observation.load_task(OBSERVATION_TASKS_DIR, task_id)
    except FileNotFoundError as exc:
        return render_task_index(request, error=str(exc), status_code=404)
    except ValueError as exc:
        return render_task_index(request, error=str(exc), status_code=400)

    window = 72
    source = "all"
    clean_action = action.strip()
    try:
        window, source = selection_from_request(
            request,
            selected_window,
            selected_source,
        )
        source = clean_form_value(
            source,
            "反馈来源",
            maximum=120,
            required=True,
        )
        clean_action = clean_form_value(
            action,
            "人工操作",
            maximum=32,
            required=True,
        )
        clean_cluster_id = clean_form_value(
            cluster_id,
            "问题簇 ID",
            maximum=160,
            required=True,
        )
        changes = {
            "risk_level": clean_form_value(
                risk_level,
                "风险等级",
                maximum=8,
            ),
            "owner": clean_form_value(owner, "负责人", maximum=120),
            "work_status": clean_form_value(
                work_status,
                "处理状态",
                maximum=40,
            ),
            "next_action": clean_form_value(
                next_action,
                "下一步动作",
                maximum=300,
            ),
            "result": clean_form_value(result, "处理结果", maximum=500),
            "target_cluster_id": clean_form_value(
                target_cluster_id,
                "目标问题簇 ID",
                maximum=160,
            ),
            "feedback_ids": clean_form_value(
                feedback_ids,
                "反馈 ID",
                maximum=1200,
            ),
        }
        clean_note = clean_form_value(note, "操作说明", maximum=800)
        observation.apply_cluster_action(
            task,
            clean_cluster_id,
            clean_action,
            changes=changes,
            reason=clean_note,
            actor="human",
            selected_window=window,
            selected_source=source,
        )
    except (OSError, ValueError) as exc:
        error_message = (
            str(exc)
            if isinstance(exc, ValueError)
            else "人工操作无法保存，请稍后重试。"
        )
        try:
            append_observation_failure(
                task,
                action="人工操作失败",
                message=error_message,
                details={
                    "cluster_id": cluster_id,
                    "action": clean_action,
                    "selected_window": window,
                    "selected_source": source,
                },
            )
        except (OSError, ValueError):
            pass
        return RedirectResponse(
            url=task_workspace_url(
                task_id,
                selected_window=window,
                selected_source=source,
                error=error_message,
                fragment=f"cluster-{cluster_id}",
            ),
            status_code=303,
        )

    action_labels = {
        "confirm": "风险结论已确认。",
        "reject": "风险结论已驳回。",
        "keep_open": "问题簇已设为保持观察。",
        "update": "负责人和处理记录已更新。",
        "merge": "问题簇已合并。",
        "split": "问题簇成员已拆分。",
    }
    return RedirectResponse(
        url=task_workspace_url(
            task_id,
            selected_window=window,
            selected_source=source,
            message=action_labels.get(clean_action, "人工操作已记录。"),
            fragment=f"cluster-{cluster_id}",
        ),
        status_code=303,
    )


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "version": __version__,
        "sample_feedback_available": SAMPLE_FEEDBACK_PATH.exists(),
        "ai_reviews_available": AI_REVIEWS_PATH.exists(),
        "web_runs_dir": str(WEB_RUNS_DIR),
        "observation_tasks_dir": str(OBSERVATION_TASKS_DIR),
        "observation_storage": "temporary" if os.getenv("VERCEL") else "local_files",
        "run_retention_hours": RUN_RETENTION_HOURS,
        "max_web_runs": MAX_WEB_RUNS,
        "web_llm_enabled": web_llm_enabled(),
        "deepseek_api_key_present": web_llm_status()["deepseek_api_key_present"],
        "web_llm_flag_enabled": web_llm_status()["web_llm_flag_enabled"],
    }


@app.post("/run")
async def run_agent(
    request: Request,
    data_source: str = Form(""),
    use_llm: Optional[str] = Form(None),
    rule_only: Optional[str] = Form(None),
    output_name: str = Form(""),
    generate_html: Optional[str] = Form("on"),
    upload_file: Optional[UploadFile] = File(None),
):
    if not data_source:
        return render_index(request, "请选择一个数据源，或上传 CSV 文件。", status_code=400)

    run_dir = create_run_dir(output_name)
    try:
        if data_source == "upload":
            if upload_file is None or not upload_file.filename:
                raise ValueError("请选择要上传的 CSV 文件。")
            if not upload_file.filename.lower().endswith(".csv"):
                raise ValueError("上传文件必须是 CSV 格式。")
            input_path = run_dir / "input.csv"
            save_upload(upload_file, input_path)
        else:
            input_path = resolve_builtin_source(data_source)
            if not input_path.exists():
                raise ValueError(f"内置数据文件不存在: {input_path}")

        llm_requested = web_llm_enabled() and boolish(use_llm) and not boolish(rule_only)
        execute_agent_run(
            input_path,
            run_dir,
            llm_requested=llm_requested,
            generate_html=boolish(generate_html),
            input_name=input_path.name,
        )
    except (ValueError, ReportInputError, FileNotFoundError) as exc:
        cleanup_failed_run(run_dir)
        return render_index(request, str(exc), status_code=400)
    except Exception:
        cleanup_failed_run(run_dir)
        return render_index(request, "Agent 运行失败，请检查输入 CSV 后重试。", status_code=500)

    return RedirectResponse(url=f"/runs/{run_dir.name}", status_code=303)


@app.post("/ask")
def ask_agent(
    request: Request,
    task: str = Form(""),
    upload_file: Optional[UploadFile] = File(None),
    rule_parser: Optional[str] = Form(None),
):
    task = task.strip()
    if not task:
        return render_index(request, "请输入自然语言任务。", status_code=400)

    has_upload = upload_file is not None and bool(upload_file.filename)
    uploaded_filename = upload_file.filename if has_upload else ""
    if has_upload and not uploaded_filename.lower().endswith(".csv"):
        return render_index(request, "上传文件必须是 CSV 格式。", status_code=400)
    parsed = parse_ask_task(
        task,
        uploaded_filename=uploaded_filename,
        use_deepseek=web_llm_enabled() and not boolish(rule_parser),
    )
    if not has_upload:
        input_path = parsed.input_path
        if input_path is None:
            return render_index(
                request,
                "无法识别输入文件，请在任务中写明 CSV 路径，或者先上传 CSV 文件。",
                status_code=400,
            )

        if not input_path.is_absolute():
            input_path = PROJECT_ROOT / input_path
        if not input_path.exists():
            return render_index(request, f"识别到输入文件 {input_path}，但文件不存在。", status_code=400)

    run_dir = create_run_dir("ask")
    try:
        input_name = input_path.name if not has_upload else upload_file.filename
        if has_upload:
            input_path = run_dir / "input.csv"
            save_upload(upload_file, input_path)

        execute_agent_run(
            input_path,
            run_dir,
            llm_requested=parsed.llm_requested and web_llm_enabled(),
            generate_html=parsed.html_requested,
            normalize_input=parsed.normalize_input,
            input_name=input_name,
            ask_parser_source=parsed.parser_source,
            ask_parser_model=parsed.parser_model,
            ask_parser_fallback_reason=parsed.parser_fallback_reason,
            ask_parser_prompt_tokens=parsed.parser_prompt_tokens,
            ask_parser_completion_tokens=parsed.parser_completion_tokens,
            ask_parser_total_tokens=parsed.parser_total_tokens,
        )
    except (ValueError, ReportInputError, FileNotFoundError) as exc:
        cleanup_failed_run(run_dir)
        return render_index(request, str(exc), status_code=400)
    except Exception:
        cleanup_failed_run(run_dir)
        return render_index(request, "Agent 运行失败，请检查自然语言任务和输入 CSV 后重试。", status_code=500)

    return RedirectResponse(url=f"/runs/{run_dir.name}", status_code=303)


@app.get("/runs/{run_id}")
def results(request: Request, run_id: str, review_applied: bool = False):
    try:
        run_data = read_results(run_id)
    except (ValueError, FileNotFoundError) as exc:
        return render_index(request, str(exc), status_code=404)
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "run": run_data,
            "version": __version__,
            "deployment_label": deployment_label(),
            "web_llm_enabled": web_llm_enabled(),
            "web_llm_status": web_llm_status(),
            "review_message": "人工复核决策已应用。" if review_applied else None,
            "review_error": None,
        },
    )


@app.post("/runs/{run_id}/reviews/apply")
async def apply_reviews(
    request: Request,
    run_id: str,
    decisions_file: UploadFile = File(...),
):
    try:
        output_dir = get_run_dir(run_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="找不到这次运行。")

    if not decisions_file.filename or not decisions_file.filename.lower().endswith(".csv"):
        run_data = read_results(run_id)
        return templates.TemplateResponse(
            request,
            "results.html",
            {
                "run": run_data,
                "version": __version__,
                "deployment_label": deployment_label(),
                "web_llm_enabled": web_llm_enabled(),
                "web_llm_status": web_llm_status(),
                "review_message": None,
                "review_error": "请上传 CSV 格式的复核决策文件。",
            },
            status_code=400,
        )

    uploaded_path = output_dir / "review_decisions.upload.csv"
    try:
        save_upload(decisions_file, uploaded_path)
        apply_review_decisions(
            output_dir / "triage_results.csv",
            uploaded_path,
            output_dir,
        )
        shutil.copyfile(uploaded_path, output_dir / "review_decisions.csv")
        create_outputs_zip(output_dir)
    except ValueError as exc:
        run_data = read_results(run_id)
        return templates.TemplateResponse(
            request,
            "results.html",
            {
                "run": run_data,
                "version": __version__,
                "deployment_label": deployment_label(),
                "web_llm_enabled": web_llm_enabled(),
                "web_llm_status": web_llm_status(),
                "review_message": None,
                "review_error": str(exc),
            },
            status_code=400,
        )
    finally:
        uploaded_path.unlink(missing_ok=True)

    return RedirectResponse(url=f"/runs/{run_id}?review_applied=true", status_code=303)


@app.get("/runs/{run_id}/download/{filename}")
def download(run_id: str, filename: str):
    allowed = {name for name, _label in DOWNLOADS}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="文件不允许下载。")
    try:
        output_dir = get_run_dir(run_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="找不到这次运行。")
    path = output_dir / filename
    if filename == "outputs.zip" and not path.exists():
        create_outputs_zip(output_dir)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在。")
    return FileResponse(path, filename=filename)


def main() -> None:
    url = "http://127.0.0.1:8000"
    print(f"Feedback Triage Agent Web App running at {url}")
    uvicorn.run("feedback_triage_agent.web_app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
