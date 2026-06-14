from __future__ import annotations

import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from feedback_triage_agent import __version__
from feedback_triage_agent.agent import FeedbackTriageAgent
from feedback_triage_agent.html_report import (
    ReportInputError,
    generate_html_report,
    parse_bullet_map,
    parse_run_log,
)
from feedback_triage_agent.task_parser import (
    infer_input_path,
    should_disable_llm,
    should_enable_llm,
    should_generate_html_report,
)
from feedback_triage_agent.rules import REQUIRED_FIELDS
from feedback_triage_agent.review import apply_review_decisions
from feedback_triage_agent.web_models import DownloadFile, WebRunData


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
WEB_RUNS_DIR = DATA_DIR / "web_runs"
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

SAMPLE_FEEDBACK_PATH = DATA_DIR / "sample_feedback.csv"
AI_REVIEWS_PATH = DATA_DIR / "ai_app_reviews.csv"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_INPUT_ROWS = 5000
MAX_LLM_ROWS = 100

REQUIRED_WEB_OUTPUTS = [
    "issue_cards.md",
    "qa_report.md",
    "run_log.md",
    "triage_results.csv",
    "review_decisions.csv",
]
DOWNLOADS = [
    ("issue_cards.md", "问题卡片 Markdown"),
    ("qa_report.md", "QA 报告 Markdown"),
    ("run_log.md", "Agent run log"),
    ("triage_results.csv", "结构化 CSV"),
    ("review_decisions.csv", "人工复核决策模板"),
    ("triage_results_reviewed.csv", "已复核结构化 CSV"),
    ("review_summary.md", "人工复核摘要"),
    ("report.html", "静态 HTML 报告"),
    ("outputs.zip", "全部输出 zip"),
]


app = FastAPI(title="Feedback Triage Agent Web App", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def render_index(request: Request, error: Optional[str] = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "error": error,
            "version": __version__,
            "sample_exists": SAMPLE_FEEDBACK_PATH.exists(),
            "ai_reviews_exists": AI_REVIEWS_PATH.exists(),
        },
        status_code=status_code,
    )


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    return cleaned.strip("-")[:40]


def create_run_dir(output_name: str = "") -> Path:
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
    if not re.match(r"^run_\d{8}_\d{6}(?:_[A-Za-z0-9_-]+)*(?:_\d{2})?$", run_id):
        raise ValueError("运行目录名称不合法。")


def get_run_dir(run_id: str) -> Path:
    validate_run_id(run_id)
    run_dir = WEB_RUNS_DIR / run_id
    if not run_dir.exists():
        raise FileNotFoundError("找不到这次运行的输出目录。")
    return run_dir


def validate_csv_input(path: Path) -> int:
    try:
        dataframe = pd.read_csv(path, nrows=MAX_INPUT_ROWS + 1)
    except Exception as exc:
        raise ValueError(f"CSV 无法读取，请检查文件编码和格式: {exc}") from exc
    missing = [field for field in REQUIRED_FIELDS if field not in dataframe.columns]
    if missing:
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
) -> None:
    row_count = validate_csv_input(input_path)
    if llm_requested and row_count > MAX_LLM_ROWS:
        raise ValueError(f"启用 LLM 时最多处理 {MAX_LLM_ROWS} 条反馈，请拆分输入或使用规则模式。")
    agent = FeedbackTriageAgent(input_path=input_path, output_dir=run_dir, llm_requested=llm_requested)
    state = agent.run()
    if state.run_log and state.run_log[-1].status == "error":
        raise ValueError(state.run_log[-1].output_summary)

    verify_outputs(run_dir)
    if generate_html:
        generate_html_report(run_dir)
    create_outputs_zip(run_dir)


def boolish(value: object) -> bool:
    normalized = str(value).strip().lower()
    return normalized in {"true", "1", "yes", "y", "on"}


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
    run_steps = parse_run_log((output_dir / "run_log.md").read_text(encoding="utf-8"))

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
        "output_dir": str(output_dir),
    }

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
def index(request: Request):
    return render_index(request)


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

        llm_requested = boolish(use_llm) and not boolish(rule_only)
        execute_agent_run(
            input_path,
            run_dir,
            llm_requested=llm_requested,
            generate_html=boolish(generate_html),
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
):
    task = task.strip()
    if not task:
        return render_index(request, "请输入自然语言任务。", status_code=400)

    has_upload = upload_file is not None and bool(upload_file.filename)
    if not has_upload:
        try:
            input_path = infer_input_path(task)
        except ValueError as exc:
            return render_index(request, f"{exc}，或者先上传 CSV 文件。", status_code=400)

        if not input_path.is_absolute():
            input_path = PROJECT_ROOT / input_path
        if not input_path.exists():
            return render_index(request, f"识别到输入文件 {input_path}，但文件不存在。", status_code=400)

    run_dir = create_run_dir("ask")
    try:
        if has_upload:
            if not upload_file.filename.lower().endswith(".csv"):
                raise ValueError("上传文件必须是 CSV 格式。")
            input_path = run_dir / "input.csv"
            save_upload(upload_file, input_path)

        execute_agent_run(
            input_path,
            run_dir,
            llm_requested=should_enable_llm(task) and not should_disable_llm(task),
            generate_html=should_generate_html_report(task),
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
