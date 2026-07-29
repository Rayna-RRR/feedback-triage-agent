from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union
from uuid import uuid4

import pandas as pd
from pydantic import ValidationError

from feedback_triage_agent.models import FeedbackRecord
from feedback_triage_agent.rules import (
    classify_feedback_record,
    detect_human_review_reasons,
)


STATE_FILENAME = "observation_state.json"
SCHEMA_VERSION = 1
SUPPORTED_WINDOWS = (24, 48, 72)
SUPPORTED_IMPORT_MODES = {"cumulative", "incremental"}
SUPPORTED_WINDOW_KINDS = {"baseline", "current", "followup"}
SUPPORTED_ACTIONS = {"confirm", "reject", "keep_open", "update", "merge", "split"}
POSITIVE_CATEGORY = "正向反馈/无明确问题"
LOCAL_TIMEZONE = timezone(timedelta(hours=8))
WINDOW_LABELS = {
    "baseline": "基线窗口",
    "current": "当前窗口",
    "followup": "后续窗口",
}
POSITIVE_CLUSTER_MARKERS = (
    "很好",
    "不错",
    "顺手",
    "顺畅",
    "方便",
    "清楚",
    "清晰",
    "稳定",
    "实用",
    "帮助",
    "推荐",
    "容易上手",
    "运行正常",
    "省时",
    "清爽",
    "及时",
    "高效",
    "省心",
    "完整",
    "满意",
    "没有遇到其他问题",
    "没有其他问题",
    "没有再出问题",
    "值得",
    "可以接受",
)
NEGATIVE_CLUSTER_MARKERS = (
    "失败",
    "错误",
    "错",
    "不准",
    "不准确",
    "错乱",
    "卡",
    "慢",
    "闪退",
    "崩溃",
    "截断",
    "不好用",
    "不太好",
    "不出现",
    "无响应",
)

COLUMN_ALIASES = {
    "id": ("id", "review_id", "reviewid", "feedback_id", "feedbackid", "comment_id", "uuid"),
    "source": ("source", "platform", "channel", "store", "market"),
    "app_name": ("app_name", "appname", "app", "product_name", "product"),
    "review_text": (
        "review_text",
        "reviewtext",
        "content",
        "review",
        "text",
        "comment",
        "feedback",
        "body",
        "message",
    ),
    "rating": ("rating", "score", "stars", "star", "rate"),
    "created_at": (
        "created_at",
        "createdat",
        "timestamp",
        "review_created_at",
        "reviewcreatedat",
        "date",
        "time",
    ),
    "version": ("version", "app_version", "release_version", "版本"),
}

TOPIC_RULES: Sequence[Tuple[str, str, Optional[str], Sequence[str]]] = (
    (
        "crash-data-loss",
        "崩溃、闪退或内容丢失",
        "性能与稳定性问题",
        ("闪退", "崩溃", "crash", "内容丢失", "数据丢失", "草稿丢失"),
    ),
    (
        "stuck-no-response",
        "卡住、无响应或无法继续",
        "性能与稳定性问题",
        ("卡住", "卡死", "无响应", "没反应", "一直转圈", "freeze", "frozen"),
    ),
    (
        "slow-latency",
        "响应慢或加载延迟",
        "性能与稳定性问题",
        ("很慢", "太慢", "延迟", "加载慢", "响应慢", "slow", "latency"),
    ),
    (
        "wrong-hallucination",
        "回答不准确或编造内容",
        "模型能力问题",
        ("不准确", "不准", "答错", "回答错", "编造", "幻觉", "hallucination", "wrong answer"),
    ),
    (
        "irrelevant-answer",
        "答非所问或未理解意图",
        "模型能力问题",
        ("答非所问", "没理解", "理解错", "跑题", "irrelevant"),
    ),
    (
        "verbose-context",
        "回答冗长或上下文衔接问题",
        "模型能力问题",
        ("啰嗦", "太长", "冗长", "上下文", "记不住", "verbose", "context"),
    ),
    (
        "copy-export",
        "复制、导出或分享链路异常",
        "交互体验问题",
        ("复制", "导出", "分享", "copy", "export", "share"),
    ),
    (
        "navigation-input",
        "导航、输入或页面操作困难",
        "交互体验问题",
        ("入口", "找不到", "按钮", "输入框", "页面", "navigation", "button"),
    ),
    (
        "theme-display",
        "主题、显示或可读性问题",
        "交互体验问题",
        ("夜间模式", "暗色", "字体", "显示", "可读", "theme", "display"),
    ),
    (
        "billing-entitlement",
        "付费、扣款或会员权益异常",
        "会员与商业化问题",
        ("扣费", "扣款", "支付", "退款", "会员", "订阅", "billing", "payment", "subscription"),
    ),
    (
        "price-quota",
        "价格、额度或使用限制",
        "会员与商业化问题",
        ("太贵", "价格", "额度", "次数", "限制", "price", "quota", "limit"),
    ),
    (
        "login-account",
        "登录、账号或访问异常",
        "账号、隐私与数据问题",
        ("登录", "账号", "验证码", "登不上", "login", "account"),
    ),
    (
        "privacy-delete",
        "隐私、数据删除或泄露担忧",
        "账号、隐私与数据问题",
        ("隐私", "泄露", "删除数据", "注销", "privacy", "leak", "delete data"),
    ),
    (
        "unsafe-content",
        "内容安全或合规风险",
        "内容安全与合规问题",
        ("违规", "有害", "色情", "暴力", "仇恨", "违法", "unsafe", "harmful"),
    ),
)


def _special_topic_for_text(text: str) -> Optional[Tuple[str, str, str]]:
    """Recognize a narrow function/failure pair before broad category keywords."""
    normalized = re.sub(r"\s+", " ", str(text).casefold()).strip()
    has_export = any(token in normalized for token in ("导出", "export", "download"))
    if has_export:
        format_markers = (
            "显示成功",
            "成功但",
            "生成但",
            "成功生成",
            "列顺序",
            "列排列",
            "列混乱",
            "格式错乱",
            "文件格式",
            "格式异常",
            "排版错乱",
            "排版",
            "文字挤",
            "format",
            "layout",
            "columns are wrong",
        )
        failure_markers = (
            "没有生成",
            "没有产出",
            "未生成",
            "没有任何反应",
            "不出现",
            "迟迟",
            "卡在",
            "不动",
            "提示失败",
            "一直转圈",
            "没出来",
            "没有拿到",
            "没拿到",
            "not generated",
            "no file",
            "stuck",
            "doesn't appear",
            "does not appear",
            "failed",
        )
        if any(marker in normalized for marker in format_markers):
            return ("export-format", "导出成功但格式错乱", "交互体验问题")
        if any(marker in normalized for marker in failure_markers):
            return ("export-failure", "导出文件失败", "交互体验问题")

    answer_markers = ("回答", "答案", "输出", "上下文")
    truncation_markers = (
        "截断",
        "中途",
        "一半",
        "后半段",
        "尾部",
        "只剩开头",
        "断掉",
        "没显示",
        "显示到",
        "truncated",
        "cut off",
        "stopped halfway",
    )
    if any(marker in normalized for marker in answer_markers) and any(
        marker in normalized for marker in truncation_markers
    ):
        return ("answer-truncated", "回答被截断", "模型能力问题")

    citation_markers = ("引用", "来源", "citation", "reference")
    wrong_markers = (
        "不存在",
        "不准确",
        "对不上",
        "张冠李戴",
        "编错",
        "错误",
        "错了",
        "不一致",
        "wrong",
        "incorrect",
        "mismatch",
    )
    if any(marker in normalized for marker in citation_markers) and any(
        marker in normalized for marker in wrong_markers
    ):
        return ("citation-error", "引用内容错误", "模型能力问题")

    vague_markers = (
        "不好用",
        "不太好用",
        "说不清",
        "说不上来",
        "难以描述",
        "具体问题说不上",
        "具体哪里",
        "vague",
        "hard to describe",
    )
    if any(marker in normalized for marker in vague_markers):
        return ("vague-experience", "模糊体验反馈（待复核）", "不明确/其他")

    login_markers = ("登录", "账号", "验证码", "login", "sign in", "account")
    login_failure_markers = (
        "失败",
        "收不到",
        "进不去",
        "无法",
        "不上",
        "验证",
        "失效",
        "登录页",
        "failed",
        "cannot",
        "can't",
        "unable",
    )
    if any(marker in normalized for marker in login_markers) and any(
        marker in normalized for marker in login_failure_markers
    ):
        return ("login-failure", "登录失败", "账号、隐私与数据问题")
    return None

TaskRef = Union[str, Path, Dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _column_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _safe_json_value(value: object) -> object:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    return normalized.strip("-")[:36].lower()


def _parse_datetime(value: str, field_name: str) -> datetime:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空。")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
        return parsed
    except ValueError as exc:
        raise ValueError(f"{field_name} 不是有效日期时间。") from exc


def _duration_hours(start: str, end: str, label: str) -> float:
    start_at = _parse_datetime(start, f"{label}开始时间")
    end_at = _parse_datetime(end, f"{label}结束时间")
    try:
        seconds = (end_at - start_at).total_seconds()
    except TypeError as exc:
        raise ValueError(f"{label}开始和结束时间必须使用一致的时区格式。") from exc
    if seconds <= 0:
        raise ValueError(f"{label}结束时间必须晚于开始时间。")
    return seconds / 3600


def _format_derived_datetime(value: datetime, reference: str) -> str:
    """Keep legacy task window strings in the same local/offset style."""
    if "+" not in reference and "Z" not in reference.upper():
        return value.replace(tzinfo=None).isoformat(timespec="minutes")
    return value.isoformat(timespec="minutes")


def _window_details(task: Dict[str, Any], window_kind: str) -> Dict[str, Any]:
    role = str(window_kind).strip().lower()
    if role not in SUPPORTED_WINDOW_KINDS:
        raise ValueError("数据窗口只能是 baseline、current 或 followup。")

    start_key = f"{role}_window_start"
    end_key = f"{role}_window_end"
    hours_key = f"{role}_window_hours"
    derived = False
    start = str(task.get(start_key, "") or "").strip()
    end = str(task.get(end_key, "") or "").strip()

    # v1 tasks were created before the independent follow-up window existed.
    # Derive an in-memory continuation so they remain readable without changing
    # their stored baseline/current evidence.
    if role == "followup" and (not start or not end):
        current_end = str(task.get("current_window_end", "") or "").strip()
        current_hours = float(task.get("current_window_hours") or 0)
        if not current_end or current_hours <= 0:
            raise ValueError("旧观察任务缺少可推导的后续窗口边界。")
        current_end_at = _parse_datetime(current_end, "当前窗口结束时间")
        start = current_end
        end_at = current_end_at + timedelta(hours=current_hours)
        end = _format_derived_datetime(end_at, current_end)
        derived = True

    if not start or not end:
        raise ValueError(f"{WINDOW_LABELS.get(role, role)}缺少开始或结束时间。")
    hours = float(task.get(hours_key) or _duration_hours(start, end, WINDOW_LABELS[role]))
    return {
        "window_kind": role,
        "label": WINDOW_LABELS[role],
        "start": start,
        "end": end,
        "hours": hours,
        "derived": derived,
    }


def _public_task(task: Dict[str, Any]) -> Dict[str, Any]:
    public = deepcopy(task)
    followup = _window_details(public, "followup")
    for key, value in (
        ("followup_window_start", followup["start"]),
        ("followup_window_end", followup["end"]),
        ("followup_window_hours", round(followup["hours"], 3)),
    ):
        public[key] = value
    public["followup_window_derived"] = followup["derived"]
    if followup["derived"]:
        public["compatibility_note"] = (
            "这是修复前创建的任务；后续窗口按当前窗口结束时间顺延推导，"
            "原有基线/当前数据和结论未被改写。"
        )
    else:
        public.pop("compatibility_note", None)
    return public


def _task_dir_from_ref(task_ref: TaskRef, task_id: Optional[str] = None) -> Path:
    if isinstance(task_ref, dict):
        directory = task_ref.get("task_dir") or task_ref.get("_task_dir")
        if not directory:
            raise ValueError("任务对象缺少 task_dir。")
        return Path(str(directory))

    path = Path(task_ref)
    if task_id is not None:
        if not re.fullmatch(r"task_[A-Za-z0-9_-]+", task_id):
            raise ValueError("任务 ID 不合法。")
        return path / task_id
    if path.name == STATE_FILENAME:
        return path.parent
    return path


def _state_path(task_ref: TaskRef, task_id: Optional[str] = None) -> Path:
    return _task_dir_from_ref(task_ref, task_id) / STATE_FILENAME


def _read_state(task_ref: TaskRef, task_id: Optional[str] = None) -> Dict[str, Any]:
    path = _state_path(task_ref, task_id)
    if not path.exists():
        raise FileNotFoundError("找不到这个观察任务。")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("观察任务状态文件无法读取。") from exc
    if state.get("schema_version") != SCHEMA_VERSION or "task" not in state:
        raise ValueError("观察任务状态版本不受支持。")
    return state


def _write_state(task_dir: Path, state: Dict[str, Any]) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    destination = task_dir / STATE_FILENAME
    temporary = task_dir / f".{STATE_FILENAME}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _audit(
    state: Dict[str, Any],
    action: str,
    message: str,
    *,
    actor: str = "system",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event = {
        "event_id": f"audit_{uuid4().hex[:12]}",
        "timestamp": _now(),
        "action": action,
        "message": message,
        "actor": actor,
        "details": details or {},
    }
    state.setdefault("audit_events", []).append(event)
    return event


def create_task(
    storage_root: Union[str, Path],
    *,
    name: str,
    product_name: str,
    baseline_version: str,
    current_version: str,
    baseline_window_start: str,
    baseline_window_end: str,
    current_window_start: str,
    current_window_end: str,
    followup_window_start: Optional[str] = None,
    followup_window_end: Optional[str] = None,
    comparison_basis: str = "equivalent_window",
    comparison_note: str = "",
    change_summary: str = "",
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = {
        "任务名称": name,
        "产品名称": product_name,
        "基线版本": baseline_version,
        "当前版本": current_version,
    }
    missing = [label for label, value in values.items() if not str(value).strip()]
    if missing:
        raise ValueError("请填写：" + "、".join(missing) + "。")

    basis = comparison_basis.strip() or "equivalent_window"
    if basis == "equal_window":
        basis = "equivalent_window"
    if basis not in {"equivalent_window", "other"}:
        raise ValueError("比较口径只能是同等窗口或其他口径。")

    baseline_hours = _duration_hours(
        baseline_window_start,
        baseline_window_end,
        "基线窗口",
    )
    current_hours = _duration_hours(
        current_window_start,
        current_window_end,
        "当前窗口",
    )
    clean_followup_start = str(followup_window_start or "").strip()
    clean_followup_end = str(followup_window_end or "").strip()
    if bool(clean_followup_start) != bool(clean_followup_end):
        raise ValueError("后续窗口开始和结束时间必须同时填写。")
    if not clean_followup_start:
        current_end_at = _parse_datetime(current_window_end, "当前窗口结束时间")
        clean_followup_start = current_window_end.strip()
        clean_followup_end = _format_derived_datetime(
            current_end_at + timedelta(hours=current_hours),
            current_window_end,
        )
    followup_hours = _duration_hours(
        clean_followup_start,
        clean_followup_end,
        "后续窗口",
    )
    note = comparison_note.strip()
    if basis == "equivalent_window" and abs(baseline_hours - current_hours) > (1 / 60):
        raise ValueError("同等窗口要求基线与当前窗口长度一致；如需不同长度，请选择其他口径并说明。")
    if basis == "equivalent_window" and abs(current_hours - followup_hours) > (1 / 60):
        raise ValueError("同等窗口要求基线、当前与后续窗口长度一致；如需不同长度，请选择其他口径并说明。")
    if basis == "other" and not note:
        raise ValueError("使用其他比较口径时必须填写口径说明。")

    root = Path(storage_root)
    root.mkdir(parents=True, exist_ok=True)
    generated_id = task_id or (
        "task_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + "_"
        + (_slug(name) or uuid4().hex[:8])
        + "_"
        + uuid4().hex[:6]
    )
    if not re.fullmatch(r"task_[A-Za-z0-9_-]+", generated_id):
        raise ValueError("任务 ID 不合法。")
    task_dir = root / generated_id
    if task_dir.exists():
        raise ValueError("同名任务目录已存在，请更换任务名称后重试。")

    created_at = _now()
    task = {
        "task_id": generated_id,
        "name": name.strip(),
        "product_name": product_name.strip(),
        "baseline_version": baseline_version.strip(),
        "current_version": current_version.strip(),
        "baseline_window_start": baseline_window_start.strip(),
        "baseline_window_end": baseline_window_end.strip(),
        "current_window_start": current_window_start.strip(),
        "current_window_end": current_window_end.strip(),
        "followup_window_start": clean_followup_start,
        "followup_window_end": clean_followup_end,
        "baseline_window_hours": round(baseline_hours, 3),
        "current_window_hours": round(current_hours, 3),
        "followup_window_hours": round(followup_hours, 3),
        "comparison_basis": basis,
        "comparison_note": note,
        "change_summary": change_summary.strip(),
        "default_import_mode": "cumulative",
        "status": "观察中",
        "created_at": created_at,
        "updated_at": created_at,
    }
    state = {
        "schema_version": SCHEMA_VERSION,
        "task": task,
        "imports": [],
        "cluster_actions": [],
        "merge_rules": [],
        "split_rules": [],
        "audit_events": [],
    }
    _audit(
        state,
        "创建观察任务",
        f"已创建 {baseline_version.strip()} → {current_version.strip()} 的版本观察任务。",
        actor="human",
        details={
            "comparison_basis": basis,
            "baseline_window_hours": round(baseline_hours, 3),
            "current_window_hours": round(current_hours, 3),
            "followup_window_hours": round(followup_hours, 3),
        },
    )
    _write_state(task_dir, state)
    return load_task(task_dir)


def load_task(
    root_or_task_dir: TaskRef,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    task_dir = _task_dir_from_ref(root_or_task_dir, task_id)
    state = _read_state(task_dir)
    task = _public_task(state["task"])
    task["task_dir"] = str(task_dir)
    task["imports"] = [_public_import(item) for item in state.get("imports", [])]
    task["audit_events"] = deepcopy(state.get("audit_events", []))
    task["available_windows"] = sorted(
        {
            int(item["observation_hours"])
            for item in state.get("imports", [])
            if item.get("status") == "success"
        }
    )
    task["available_window_kinds"] = sorted(
        {
            str(item["window_kind"])
            for item in state.get("imports", [])
            if item.get("status") == "success"
        }
    )
    return task


def list_tasks(storage_root: Union[str, Path]) -> List[Dict[str, Any]]:
    root = Path(storage_root)
    if not root.exists():
        return []
    tasks: List[Dict[str, Any]] = []
    for task_dir in sorted(root.glob("task_*")):
        if not task_dir.is_dir():
            continue
        try:
            task = load_task(task_dir)
            latest = max(task["available_windows"], default=0)
            cluster_count = (
                build_workspace(task, selected_window=latest)["metrics"]["cluster_count"]
                if latest
                else 0
            )
            task["latest_window"] = f"{latest}h" if latest else "尚未导入"
            task["cluster_count"] = cluster_count
            tasks.append(task)
        except (FileNotFoundError, ValueError):
            continue
    tasks.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return tasks


def append_audit_event(
    task_ref: TaskRef,
    action: str,
    message: str,
    *,
    actor: str = "system",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    task_dir = _task_dir_from_ref(task_ref)
    state = _read_state(task_dir)
    event = _audit(state, action, message, actor=actor, details=details)
    state["task"]["updated_at"] = event["timestamp"]
    _write_state(task_dir, state)
    return event


def _find_column(columns: Iterable[object], field: str) -> Optional[str]:
    index = {_column_key(column): str(column) for column in columns}
    for alias in COLUMN_ALIASES[field]:
        match = index.get(_column_key(alias))
        if match is not None:
            return match
    return None


def _fingerprint(source: str, feedback_id: str, text: str) -> str:
    identity = f"{source.casefold()}|{feedback_id.casefold()}"
    if not feedback_id:
        normalized_text = re.sub(r"\s+", " ", text.casefold()).strip()
        identity = f"{source.casefold()}|{normalized_text}"
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()


def _normalize_frame(
    dataframe: pd.DataFrame,
    *,
    task: Dict[str, Any],
    window_kind: str,
    source: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    frame = dataframe.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    mapping = {
        field: _find_column(frame.columns, field)
        for field in COLUMN_ALIASES
    }
    if mapping["review_text"] is None:
        raise ValueError("CSV 未识别到反馈正文字段，请使用 review_text、content、text 或 feedback 等常见列名。")

    records: List[Dict[str, Any]] = []
    errors: List[str] = []
    duplicate_count = 0
    generated_id_count = 0
    missing_rating_count = 0
    seen: set = set()
    seen_ids: set = set()
    duplicate_ids: List[str] = []
    out_of_window: List[str] = []
    consumed = {column for column in mapping.values() if column}
    window = _window_details(task, window_kind)

    for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
        text = _normalize_text(row.get(mapping["review_text"]))  # type: ignore[arg-type]
        if not text:
            errors.append(f"第 {row_number} 行：反馈正文为空")
            continue

        raw_id = (
            _normalize_text(row.get(mapping["id"]))
            if mapping["id"] is not None
            else ""
        )
        generated = False
        if not raw_id:
            raw_id = "generated_" + hashlib.sha1(
                f"{source}|{text}".encode("utf-8")
            ).hexdigest()[:12]
            generated = True
            generated_id_count += 1
        if raw_id in seen_ids:
            duplicate_ids.append(raw_id)
            duplicate_count += 1
        seen_ids.add(raw_id)

        raw_rating = (
            row.get(mapping["rating"])
            if mapping["rating"] is not None
            else None
        )
        if _normalize_text(raw_rating) == "":
            raw_rating = None
            missing_rating_count += 1

        raw_app = (
            _normalize_text(row.get(mapping["app_name"]))
            if mapping["app_name"] is not None
            else ""
        )
        raw_source = (
            _normalize_text(row.get(mapping["source"]))
            if mapping["source"] is not None
            else ""
        )
        created_at = (
            _normalize_text(row.get(mapping["created_at"]))
            if mapping["created_at"] is not None
            else ""
        )
        if created_at:
            try:
                created_at_value = _parse_datetime(created_at, "created_at")
            except ValueError as exc:
                errors.append(f"第 {row_number} 行：{exc}")
                continue
            window_start = _parse_datetime(window["start"], f"{window['label']}开始时间")
            window_end = _parse_datetime(window["end"], f"{window['label']}结束时间")
            if not window_start <= created_at_value <= window_end:
                out_of_window.append(
                    f"第 {row_number} 行 created_at={created_at} 不在"
                    f"{window['label']} {window['start']} 至 {window['end']} 内"
                )
        raw_version = (
            _normalize_text(row.get(mapping["version"]))
            if mapping["version"] is not None
            else ""
        )
        try:
            feedback = FeedbackRecord(
                id=raw_id,
                source=source,
                app_name=raw_app or task["product_name"],
                review_text=text,
                rating=raw_rating,
            )
        except (ValidationError, ValueError) as exc:
            errors.append(f"第 {row_number} 行：{exc}")
            continue

        fingerprint = _fingerprint(source, "" if generated else feedback.id, text)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)

        classified = classify_feedback_record(feedback)
        review_reasons = detect_human_review_reasons(classified)
        metadata = {
            str(column): _safe_json_value(row.get(column))
            for column in frame.columns
            if column not in consumed
        }
        if raw_source and raw_source != source:
            metadata["original_source"] = raw_source
        record = {
            "feedback_id": feedback.id,
            "record_key": fingerprint,
            "fingerprint": fingerprint,
            "source": source,
            "app_name": feedback.app_name,
            "version": raw_version
            or task.get(
                "baseline_version" if window_kind == "baseline" else "current_version",
                "",
            ),
            "review_text": feedback.review_text,
            "rating": feedback.rating,
            "created_at": created_at or None,
            "metadata": metadata,
            "issue_category": classified.issue_category,
            "priority": classified.priority,
            "confidence": classified.confidence,
            "matched_categories": classified.matched_categories,
            "matched_keywords": classified.matched_keywords,
            "review_reasons": review_reasons,
            "classification_source": "rules",
            "rule_issue_category": classified.rule_issue_category,
            "llm_rule_disagreement": False,
        }
        records.append(record)

    return records, {
        "column_mapping": {key: value for key, value in mapping.items() if value},
        "invalid_count": len(errors),
        "errors": errors[:50],
        "duplicate_count": duplicate_count,
        "duplicate_ids": sorted(set(duplicate_ids)),
        "out_of_window_count": len(out_of_window),
        "out_of_window": out_of_window[:50],
        "generated_id_count": generated_id_count,
        "missing_rating_count": missing_rating_count,
    }


def _matching_imports(
    state: Dict[str, Any],
    *,
    window_kind: str,
    selected_window: int,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    imports = [
        item
        for item in state.get("imports", [])
        if item.get("status") == "success"
        and item.get("window_kind") == window_kind
        and int(item.get("observation_hours", 0)) <= selected_window
        and (source is None or item.get("source") == source)
    ]
    return sorted(imports, key=lambda item: (int(item["observation_hours"]), item["imported_at"]))


def _fold_records(
    state: Dict[str, Any],
    *,
    window_kind: str,
    selected_window: int,
    selected_source: str = "all",
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    all_sources = sorted(
        {
            str(item["source"])
            for item in state.get("imports", [])
            if item.get("status") == "success"
            and item.get("window_kind") == window_kind
            and int(item.get("observation_hours", 0)) <= selected_window
        }
    )
    if selected_source != "all":
        all_sources = [source for source in all_sources if source == selected_source]

    folded: Dict[str, Dict[str, Any]] = {}
    coverage: Dict[str, int] = {}
    for source in all_sources:
        current: Dict[str, Dict[str, Any]] = {}
        for item in _matching_imports(
            state,
            window_kind=window_kind,
            selected_window=selected_window,
            source=source,
        ):
            batch = {record["fingerprint"]: deepcopy(record) for record in item.get("records", [])}
            if item["import_mode"] == "cumulative":
                current = batch
            else:
                current.update(batch)
            coverage[source] = max(
                coverage.get(source, 0),
                int(item["observation_hours"]),
            )
        for fingerprint, record in current.items():
            folded[f"{source}|{fingerprint}"] = record
    return list(folded.values()), coverage


def _record_failed_import(
    state: Dict[str, Any],
    task_dir: Path,
    *,
    import_id: str,
    window_kind: str,
    observation_hours: int,
    import_mode: str,
    source: str,
    filename: str,
    imported_at: str,
    message: str,
    errors: Optional[List[str]] = None,
    duplicate_count: int = 0,
    error_count: int = 1,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    failed = {
        "import_id": import_id,
        "status": "failed",
        "window_kind": window_kind,
        "observation_hours": observation_hours,
        "import_mode": import_mode,
        "source": source,
        "filename": filename,
        "imported_at": imported_at,
        "accepted_count": 0,
        "duplicate_count": duplicate_count,
        "skipped_count": 0,
        "error_count": error_count,
        "errors": list(errors or [message])[:50],
        "records": [],
    }
    state["imports"].append(failed)
    _audit(
        state,
        "导入失败",
        f"{filename} 未写入任何反馈：{message}",
        details={**_public_import(failed), **(details or {})},
    )
    state["task"]["updated_at"] = imported_at
    _write_state(task_dir, state)
    raise ValueError(message)


def _same_record_content(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return all(
        left.get(key) == right.get(key)
        for key in ("review_text", "rating", "created_at", "version")
    )


def add_import(
    task_ref: TaskRef,
    *,
    source_path: Union[str, Path],
    window_kind: str,
    observation_hours: int,
    source: str,
    import_mode: str = "cumulative",
    filename: str = "",
) -> Dict[str, Any]:
    task_dir = _task_dir_from_ref(task_ref)
    state = _read_state(task_dir)
    role = window_kind.strip().lower()
    mode = (import_mode or "cumulative").strip().lower()
    clean_source = source.strip()
    try:
        hours = int(observation_hours)
    except (TypeError, ValueError):
        hours = 0

    source_path = Path(source_path)
    display_filename = Path(filename or source_path.name).name
    import_id = f"import_{uuid4().hex[:12]}"
    imported_at = _now()
    validation_error = ""
    if role not in SUPPORTED_WINDOW_KINDS:
        validation_error = "数据窗口只能是 baseline、current 或 followup。"
    elif mode not in SUPPORTED_IMPORT_MODES:
        validation_error = "导入方式只能是 cumulative 或 incremental。"
    elif hours not in SUPPORTED_WINDOWS:
        validation_error = "观察窗口必须是 24、48 或 72 小时。"
    elif not clean_source:
        validation_error = "反馈来源不能为空。"

    window: Optional[Dict[str, Any]] = None
    if not validation_error:
        window = _window_details(state["task"], role)
        if hours > float(window["hours"]) + (1 / 60):
            validation_error = (
                f"{WINDOW_LABELS[role]}只有 {window['hours']:g} 小时，"
                f"不能导入 {hours}h 快照。"
            )
    if validation_error:
        _record_failed_import(
            state,
            task_dir,
            import_id=import_id,
            window_kind=role,
            observation_hours=hours,
            import_mode=mode,
            source=clean_source,
            filename=display_filename,
            imported_at=imported_at,
            message=validation_error,
        )

    try:
        dataframe = pd.read_csv(source_path, dtype=object, keep_default_na=False)
        if len(dataframe) > 5000:
            raise ValueError("CSV 超过 5000 行限制，请拆分后重试。")
        records, qa = _normalize_frame(
            dataframe,
            task=state["task"],
            window_kind=role,
            source=clean_source,
        )
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else "CSV 无法读取，请检查编码和格式。"
        _record_failed_import(
            state,
            task_dir,
            import_id=import_id,
            window_kind=role,
            observation_hours=hours,
            import_mode=mode,
            source=clean_source,
            filename=display_filename,
            imported_at=imported_at,
            message=message,
        )

    validation_errors = list(qa["errors"])
    validation_errors.extend(qa["out_of_window"])
    if qa["duplicate_ids"]:
        validation_errors.append(
            "文件内部重复反馈 ID：" + "、".join(qa["duplicate_ids"])
        )
    if qa["invalid_count"] or qa["out_of_window_count"] or qa["duplicate_ids"]:
        message_parts = []
        if qa["invalid_count"]:
            message_parts.append(f"{qa['invalid_count']} 行字段或格式校验失败")
        if qa["duplicate_ids"]:
            message_parts.append("文件内部存在重复反馈 ID")
        if qa["out_of_window_count"]:
            message_parts.append("存在窗口外时间")
        message = "导入被拒绝，整次导入未写入：" + "；".join(message_parts)
        _record_failed_import(
            state,
            task_dir,
            import_id=import_id,
            window_kind=role,
            observation_hours=hours,
            import_mode=mode,
            source=clean_source,
            filename=display_filename,
            imported_at=imported_at,
            message=message,
            errors=validation_errors,
            duplicate_count=qa["duplicate_count"],
            error_count=max(1, qa["invalid_count"] + qa["out_of_window_count"]),
        )

    existing_records, _coverage = _fold_records(
        state,
        window_kind=role,
        selected_window=hours,
        selected_source=clean_source,
    )
    existing_by_id = {record["feedback_id"]: record for record in existing_records}
    conflicts: List[str] = []
    skipped_records: List[str] = []
    for record in records:
        existing = existing_by_id.get(record["feedback_id"])
        if existing is None:
            continue
        if not _same_record_content(existing, record):
            conflicts.append(record["feedback_id"])
        else:
            skipped_records.append(record["feedback_id"])
    if conflicts:
        message = (
            "导入被拒绝，整次导入未写入：已存在 ID 但内容不同："
            + "、".join(sorted(set(conflicts)))
        )
        _record_failed_import(
            state,
            task_dir,
            import_id=import_id,
            window_kind=role,
            observation_hours=hours,
            import_mode=mode,
            source=clean_source,
            filename=display_filename,
            imported_at=imported_at,
            message=message,
            errors=[message],
            error_count=len(set(conflicts)),
        )

    new_records = [
        record for record in records if record["feedback_id"] not in existing_by_id
    ]
    if mode == "cumulative":
        stored_records = [
            deepcopy(existing_by_id.get(record["feedback_id"], record))
            for record in records
        ]
    else:
        stored_records = new_records

    skipped_count = len(skipped_records)
    within_file_duplicate_count = qa["duplicate_count"]
    compatibility_duplicate_count = (
        skipped_count if mode == "incremental" else 0
    )
    skip_reasons = (
        ["累计快照中与既有记录的 ID、原文、评分、时间和版本完全相同，保留既有记录。"]
        if skipped_count
        else []
    )
    result = {
        "import_id": import_id,
        "status": "success",
        "window_kind": role,
        "observation_hours": hours,
        "import_mode": mode,
        "source": clean_source,
        "filename": display_filename,
        "imported_at": imported_at,
        "accepted_count": len(new_records),
        "duplicate_count": within_file_duplicate_count + compatibility_duplicate_count,
        "within_file_duplicate_count": within_file_duplicate_count,
        "skipped_count": skipped_count,
        "skip_reasons": skip_reasons,
        "error_count": 0,
        "errors": [],
        "generated_id_count": qa["generated_id_count"],
        "missing_rating_count": qa["missing_rating_count"],
        "column_mapping": qa["column_mapping"],
        "classification_source": "rules",
        "records": stored_records,
    }
    state["imports"].append(result)
    skip_message = (
        f"跳过 {skipped_count} 条完全相同的既有记录（累计快照保留既有记录）。"
        if skipped_count
        else ""
    )
    if window and window["derived"]:
        skip_message = (skip_message + " " if skip_message else "") + "兼容旧任务：后续窗口边界按当前窗口结束时间顺延推导。"
    _audit(
        state,
        "导入反馈",
        (
            f"{WINDOW_LABELS[role]} {hours}h 已导入 {len(new_records)} 条新反馈；"
            f"跳过 {skipped_count} 条，文件内重复 {within_file_duplicate_count} 条。"
            + (f" {skip_message}" if skip_message else "")
        ),
        details={
            **_public_import(result),
            "generated_id_count": result["generated_id_count"],
            "missing_rating_count": result["missing_rating_count"],
            "column_mapping": result["column_mapping"],
            "skip_reasons": skip_reasons,
            "within_file_duplicate_count": within_file_duplicate_count,
            "legacy_followup_window_derived": bool(window and window["derived"]),
            "engine": "rules",
        },
    )
    state["task"]["updated_at"] = imported_at
    _write_state(task_dir, state)
    return _public_import(result)


def _public_import(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in item.items()
        if key != "records"
    }


def _topic_for_record(record: Dict[str, Any], category: str) -> Tuple[str, str, bool]:
    special = _special_topic_for_text(record["review_text"])
    if special and special[2] == category:
        return special[0], special[1], special[0] == "vague-experience"
    normalized = record["review_text"].casefold()
    for topic_id, title, expected_category, patterns in TOPIC_RULES:
        if expected_category == category and any(pattern.casefold() in normalized for pattern in patterns):
            return topic_id, title, False

    category_keywords = record.get("matched_keywords", {}).get(category, [])
    if category_keywords:
        keyword = sorted(category_keywords, key=lambda value: (-len(value), value))[0]
        topic_hash = hashlib.sha1(f"{category}|{keyword}".encode("utf-8")).hexdigest()[:10]
        return f"keyword-{topic_hash}", f"{category}：{keyword}", False
    general_hash = hashlib.sha1(category.encode("utf-8")).hexdigest()[:10]
    return f"general-{general_hash}", category, True


def _cluster_id(category: str, topic_id: str) -> str:
    digest = hashlib.sha1(f"{category}|{topic_id}".encode("utf-8")).hexdigest()[:12]
    return f"cluster_{digest}"


def _record_categories(record: Dict[str, Any]) -> List[str]:
    special = _special_topic_for_text(record["review_text"])
    if special:
        return [special[2]]
    normalized = record["review_text"].casefold()
    if (
        record.get("rating") is not None
        and int(record["rating"]) >= 4
        and any(marker.casefold() in normalized for marker in POSITIVE_CLUSTER_MARKERS)
        and not any(marker.casefold() in normalized for marker in NEGATIVE_CLUSTER_MARKERS)
    ):
        return []
    if record.get("issue_category") == POSITIVE_CATEGORY:
        return []
    categories = [
        category
        for category in record.get("matched_categories", [])
        if category != POSITIVE_CATEGORY
    ]
    if not categories and record.get("issue_category") != POSITIVE_CATEGORY:
        categories = [record["issue_category"]]
    return list(dict.fromkeys(categories))


def _empty_raw_cluster(
    cluster_id: str,
    *,
    title: str,
    issue_category: str,
    broad_topic: bool,
) -> Dict[str, Any]:
    return {
        "cluster_id": cluster_id,
        "title": title,
        "summary": "",
        "issue_category": issue_category,
        "broad_topic": broad_topic,
        "baseline_members": [],
        "current_members": [],
    }


def _evidence(
    record: Dict[str, Any],
    window_kind: str,
    task: Dict[str, Any],
) -> Dict[str, Any]:
    window = _window_details(task, window_kind)
    return {
        "feedback_id": record["feedback_id"],
        "evidence_id": f"{record['source']}:{record['feedback_id']}",
        "record_key": record["record_key"],
        "window_kind": window_kind,
        "window_label": window["label"],
        "window_start": window["start"],
        "window_end": window["end"],
        "window_hours": window["hours"],
        "source": record["source"],
        "app_name": record.get("app_name", task.get("product_name", "")),
        "version": record.get("version") or (
            task.get("baseline_version", "")
            if window_kind == "baseline"
            else task.get("current_version", "")
        ),
        "review_text": record["review_text"],
        "rating": record.get("rating"),
        "created_at": record.get("created_at"),
        "priority": record["priority"],
        "issue_category": record["issue_category"],
        "confidence": record["confidence"],
        "review_reasons": record.get("review_reasons", []),
        "classification_source": record.get("classification_source", "rules"),
        "llm_rule_disagreement": record.get("llm_rule_disagreement", False),
        "metadata": record.get("metadata", {}),
    }


def _build_raw_clusters(
    baseline_records: List[Dict[str, Any]],
    current_records: List[Dict[str, Any]],
    *,
    baseline_kind: str = "baseline",
    current_kind: str = "current",
    task: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    clusters: Dict[str, Dict[str, Any]] = {}
    for member_slot, window_kind, records in (
        ("baseline", baseline_kind, baseline_records),
        ("current", current_kind, current_records),
    ):
        for record in records:
            for category in _record_categories(record):
                topic_id, title, broad_topic = _topic_for_record(record, category)
                identifier = _cluster_id(category, topic_id)
                raw = clusters.setdefault(
                    identifier,
                    _empty_raw_cluster(
                        identifier,
                        title=title,
                        issue_category=category,
                        broad_topic=broad_topic,
                    ),
                )
                member_key = f"{window_kind}|{record['record_key']}"
                members_key = f"{member_slot}_members"
                if not any(item["_member_key"] == member_key for item in raw[members_key]):
                    item = _evidence(record, window_kind, task)
                    item["_member_key"] = member_key
                    raw[members_key].append(item)
    return clusters


def _apply_split_rules(
    raw_clusters: Dict[str, Dict[str, Any]],
    rules: List[Dict[str, Any]],
) -> None:
    for rule in rules:
        source_id = rule["source_cluster_id"]
        source = raw_clusters.get(source_id)
        if source is None:
            continue
        selected_evidence = set(rule.get("evidence_ids", []))
        selected_ids = set(rule.get("feedback_ids", []))

        def selected(item: Dict[str, Any]) -> bool:
            if selected_evidence:
                return item["evidence_id"] in selected_evidence
            return item["feedback_id"] in selected_ids

        moved_baseline = [
            item for item in source["baseline_members"] if selected(item)
        ]
        moved_current = [
            item for item in source["current_members"] if selected(item)
        ]
        if not moved_baseline and not moved_current:
            continue
        source["baseline_members"] = [
            item for item in source["baseline_members"] if not selected(item)
        ]
        source["current_members"] = [
            item for item in source["current_members"] if not selected(item)
        ]
        split_id = rule["new_cluster_id"]
        split = raw_clusters.setdefault(
            split_id,
            _empty_raw_cluster(
                split_id,
                title=rule.get("title") or f"拆分：{source['title']}",
                issue_category=source["issue_category"],
                broad_topic=False,
            ),
        )
        split["baseline_members"].extend(moved_baseline)
        split["current_members"].extend(moved_current)


def _resolve_merge_target(identifier: str, mappings: Dict[str, str]) -> str:
    seen = set()
    current = identifier
    while current in mappings and current not in seen:
        seen.add(current)
        current = mappings[current]
    return current


def _apply_merge_rules(
    raw_clusters: Dict[str, Dict[str, Any]],
    rules: List[Dict[str, Any]],
) -> None:
    mappings = {
        rule["source_cluster_id"]: rule["target_cluster_id"]
        for rule in rules
    }
    for source_id in list(raw_clusters):
        target_id = _resolve_merge_target(source_id, mappings)
        if target_id == source_id:
            continue
        source = raw_clusters.get(source_id)
        if source is None:
            continue
        target = raw_clusters.setdefault(
            target_id,
            _empty_raw_cluster(
                target_id,
                title=source["title"],
                issue_category=source["issue_category"],
                broad_topic=source["broad_topic"],
            ),
        )
        for key in ("baseline_members", "current_members"):
            existing = {item["_member_key"] for item in target[key]}
            target[key].extend(
                item for item in source[key] if item["_member_key"] not in existing
            )
        del raw_clusters[source_id]


def _change_status(
    baseline_count: int,
    current_count: int,
    baseline_total: int,
    current_total: int,
) -> Tuple[str, float, float, float]:
    baseline_share = baseline_count / baseline_total if baseline_total else 0.0
    current_share = current_count / current_total if current_total else 0.0
    delta = current_share - baseline_share
    if baseline_total == 0 or current_total == 0:
        return "证据不足", baseline_share, current_share, delta
    if baseline_count == 0 and current_count > 0:
        return "新增", baseline_share, current_share, delta
    if baseline_count > 0 and current_count == 0:
        return "缓解", baseline_share, current_share, delta
    if delta >= 0.02 and current_count > baseline_count:
        return "加重", baseline_share, current_share, delta
    if delta <= -0.02 and current_count < baseline_count:
        return "缓解", baseline_share, current_share, delta
    return "稳定", baseline_share, current_share, delta


def _finalize_cluster(
    raw: Dict[str, Any],
    *,
    baseline_total: int,
    current_total: int,
    selected_window: int,
    baseline_coverage: Dict[str, int],
    current_coverage: Dict[str, int],
    comparison_basis: str,
    comparison_note: str,
    left_label: str = "基线",
    right_label: str = "当前",
    left_window_kind: str = "baseline",
    right_window_kind: str = "current",
) -> Optional[Dict[str, Any]]:
    baseline_members = raw["baseline_members"]
    current_members = raw["current_members"]
    if not baseline_members and not current_members:
        return None
    baseline_count = len(baseline_members)
    current_count = len(current_members)
    status, baseline_share, current_share, delta_share = _change_status(
        baseline_count,
        current_count,
        baseline_total,
        current_total,
    )
    if raw.get("broad_topic"):
        status = "待复核／趋势暂不判定"
    current_priorities = [item["priority"] for item in current_members]
    all_members = current_members + baseline_members
    if "P0" in current_priorities:
        risk_level = "P0"
    elif "P1" in current_priorities or status in {"新增", "加重"}:
        risk_level = "P1"
    else:
        risk_level = "P2"

    confidences = [float(item.get("confidence", 0.0)) for item in all_members]
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    if len(all_members) == 1:
        confidence -= 0.1
    if raw.get("broad_topic"):
        confidence -= 0.1
    confidence = round(max(0.0, min(confidence, 0.95)), 2)

    gaps: List[str] = []
    if baseline_total == 0:
        gaps.append(f"缺少{left_label}反馈，无法完成前后比较")
    if current_total == 0:
        gaps.append(f"缺少{right_label}反馈，无法完成前后比较")
    for label, coverage in ((left_label, baseline_coverage), (right_label, current_coverage)):
        stale_sources = [
            f"{source}（最新 {hours}h）"
            for source, hours in sorted(coverage.items())
            if hours < selected_window
        ]
        if stale_sources:
            gaps.append(f"{label}来源未覆盖所选 {selected_window}h：" + "、".join(stale_sources))
    if raw.get("broad_topic"):
        gaps.append("问题描述较模糊，仅形成低置信度候选簇，需人工复核后再判定趋势")
    if len(all_members) == 1:
        gaps.append("当前问题簇只有 1 条证据，置信度有限")
    if any(item.get("rating") is None for item in all_members):
        gaps.append("部分反馈缺少评分，严重度仅依据原文判断")
    if comparison_basis != "equivalent_window":
        gaps.append("当前使用非同等比较口径：" + comparison_note)
    if any(item.get("llm_rule_disagreement") for item in all_members):
        gaps.append("存在规则与模型判断冲突")

    reasons = [
        (
            f"{left_label} {baseline_count}/{baseline_total} 条（{baseline_share:.1%}），"
            f"{right_label} {current_count}/{current_total} 条（{current_share:.1%}）"
        )
    ]
    if status in {"新增", "加重", "缓解"}:
        reasons.append(f"按当前导入数据，该问题从{left_label}到{right_label}呈“{status}”状态")
    elif status == "待复核／趋势暂不判定":
        reasons.append("反馈过于模糊，系统不自动输出新增、加重、稳定或缓解结论")
    if "P0" in current_priorities:
        reasons.append("当前窗口包含规则识别的 P0 高严重度反馈")
    elif "P1" in current_priorities:
        reasons.append("当前窗口包含规则识别的 P1 反馈")
    if confidence < 0.7:
        reasons.append("聚合或分类置信度不足，需要人工复核")

    member_review_reasons = [
        reason
        for item in all_members
        for reason in item.get("review_reasons", [])
    ]
    needs_review = (
        risk_level in {"P0", "P1"}
        or confidence < 0.7
        or bool(gaps)
        or bool(member_review_reasons)
    )
    summary = (
        f"{raw['title']}：{right_label} {current_count} 条，"
        f"{left_label} {baseline_count} 条；变化状态为{status}。"
    )
    clean_members = []
    for item in all_members:
        clean = {key: value for key, value in item.items() if key != "_member_key"}
        clean_members.append(clean)
    return {
        "cluster_id": raw["cluster_id"],
        "title": raw["title"],
        "summary": summary,
        "issue_category": raw["issue_category"],
        "category": raw["issue_category"],
        "baseline_count": baseline_count,
        "current_count": current_count,
        "baseline_share": round(baseline_share, 6),
        "current_share": round(current_share, 6),
        "delta_share": round(delta_share, 6),
        "change_status": status,
        "risk_level": risk_level,
        "system_risk_level": risk_level,
        "confidence": confidence,
        "risk_reasons": reasons,
        "evidence_gaps": list(dict.fromkeys(gaps)),
        "review_status": "待复核" if needs_review else "无需复核",
        "review_required": needs_review,
        "owner": "",
        "work_status": "待处理",
        "next_action": "先核对原始反馈与聚合边界" if needs_review else "继续观察",
        "result": "",
        "members": clean_members,
        "baseline_evidence": [
            item for item in clean_members if item["window_kind"] == left_window_kind
        ],
        "current_evidence": [
            item for item in clean_members if item["window_kind"] == right_window_kind
        ],
        "trajectory": "等待下一观察窗口",
        "system_snapshot": {
            "risk_level": risk_level,
            "change_status": status,
            "confidence": confidence,
            "baseline_count": baseline_count,
            "current_count": current_count,
        },
    }


def _apply_action_overrides(
    clusters: List[Dict[str, Any]],
    actions: List[Dict[str, Any]],
) -> None:
    indexed = {cluster["cluster_id"]: cluster for cluster in clusters}
    for action in actions:
        cluster = indexed.get(action["cluster_id"])
        if cluster is None:
            continue
        action_name = action["action"]
        if action_name == "confirm":
            cluster["review_status"] = "已确认"
        elif action_name == "reject":
            cluster["review_status"] = "已驳回"
        elif action_name == "keep_open":
            cluster["review_status"] = "保持观察"
        changes = action.get("changes", {})
        for source_key, target_key in (
            ("risk_level", "risk_level"),
            ("owner", "owner"),
            ("work_status", "work_status"),
            ("next_action", "next_action"),
            ("result", "result"),
        ):
            value = changes.get(source_key)
            if value not in (None, ""):
                cluster[target_key] = value
        cluster["last_human_action"] = {
            "action": action_name,
            "reason": action.get("reason", ""),
            "actor": action.get("actor", "human"),
            "timestamp": action["timestamp"],
        }


def _workspace_clusters(
    state: Dict[str, Any],
    *,
    selected_window: int,
    selected_source: str,
    left_window_kind: str = "baseline",
    right_window_kind: str = "current",
    left_label: str = "基线",
    right_label: str = "当前",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    baseline_records, baseline_coverage = _fold_records(
        state,
        window_kind=left_window_kind,
        selected_window=selected_window,
        selected_source=selected_source,
    )
    current_records, current_coverage = _fold_records(
        state,
        window_kind=right_window_kind,
        selected_window=selected_window,
        selected_source=selected_source,
    )
    raw = _build_raw_clusters(
        baseline_records,
        current_records,
        baseline_kind=left_window_kind,
        current_kind=right_window_kind,
        task=state["task"],
    )
    _apply_split_rules(raw, state.get("split_rules", []))
    _apply_merge_rules(raw, state.get("merge_rules", []))
    clusters = [
        cluster
        for cluster in (
            _finalize_cluster(
                item,
                baseline_total=len(baseline_records),
                current_total=len(current_records),
                selected_window=selected_window,
                baseline_coverage=baseline_coverage,
                current_coverage=current_coverage,
                comparison_basis=state["task"]["comparison_basis"],
                comparison_note=state["task"].get("comparison_note", ""),
                left_label=left_label,
                right_label=right_label,
                left_window_kind=left_window_kind,
                right_window_kind=right_window_kind,
            )
            for item in raw.values()
        )
        if cluster is not None
    ]
    _apply_action_overrides(clusters, state.get("cluster_actions", []))
    clusters.sort(
        key=lambda item: (
            {"P0": 0, "P1": 1, "P2": 2}.get(item["risk_level"], 3),
            {
                "新增": 0,
                "加重": 1,
                "待复核／趋势暂不判定": 2,
                "证据不足": 3,
                "稳定": 4,
                "缓解": 5,
            }.get(
                item["change_status"],
                5,
            ),
            -item["current_count"],
            item["cluster_id"],
        )
    )
    return clusters, {
        "baseline_records": baseline_records,
        "current_records": current_records,
        "baseline_coverage": baseline_coverage,
        "current_coverage": current_coverage,
    }


def _add_trajectories(
    state: Dict[str, Any],
    clusters: List[Dict[str, Any]],
    *,
    selected_window: int,
    selected_source: str,
    window_kind: str = "current",
) -> None:
    previous_windows = sorted(
        {
            int(item["observation_hours"])
            for item in state.get("imports", [])
            if item.get("status") == "success"
            and int(item["observation_hours"]) < selected_window
            and item.get("window_kind") == window_kind
        }
    )
    if not previous_windows:
        return
    previous_window = previous_windows[-1]
    previous, _details = _workspace_clusters(
        state,
        selected_window=previous_window,
        selected_source=selected_source,
        left_window_kind="baseline" if window_kind == "current" else window_kind,
        right_window_kind=window_kind,
        left_label="基线" if window_kind == "current" else "前一后续窗口",
        right_label="当前" if window_kind == "current" else "后续",
    )
    previous_by_id = {item["cluster_id"]: item for item in previous}
    for cluster in clusters:
        earlier = previous_by_id.get(cluster["cluster_id"])
        if earlier is None and cluster["current_count"]:
            cluster["trajectory"] = f"在 {selected_window}h 视图首次出现"
            continue
        if earlier is None:
            continue
        delta = cluster["current_share"] - earlier["current_share"]
        if delta >= 0.02:
            cluster["trajectory"] = f"较 {previous_window}h 继续恶化"
        elif delta <= -0.02:
            cluster["trajectory"] = f"较 {previous_window}h 有所缓解"
        else:
            cluster["trajectory"] = f"与 {previous_window}h 基本接近"


def _owner_summary(task: Dict[str, Any], clusters: List[Dict[str, Any]], selected_window: int) -> str:
    confirmed = [
        cluster
        for cluster in clusters
        if cluster["review_status"] == "已确认"
        and cluster.get("members")
        and cluster.get("owner")
    ]
    if not confirmed:
        return ""
    lines = [
        f"{task['name']} · {selected_window}h 负责人摘要",
        "说明：以下只汇总有原始证据、已人工确认且已分配负责人的问题；发版后变化不代表版本因果。",
        "",
    ]
    for cluster in confirmed:
        lines.extend(
            [
                f"- [{cluster['risk_level']}/{cluster['change_status']}] {cluster['title']}",
                f"  负责人：{cluster['owner']}；状态：{cluster['work_status']}",
                f"  动作：{cluster['next_action'] or '待补充'}",
                f"  证据：基线 {cluster['baseline_count']} 条，当前 {cluster['current_count']} 条",
                f"  结果：{cluster['result'] or '待后续窗口验证'}",
            ]
        )
    return "\n".join(lines)


def _has_successful_import(state: Dict[str, Any], window_kind: str) -> bool:
    return any(
        item.get("status") == "success"
        and item.get("window_kind") == window_kind
        for item in state.get("imports", [])
    )


def _comparison_view(
    state: Dict[str, Any],
    *,
    selected_window: int,
    selected_source: str,
    left_window_kind: str,
    right_window_kind: str,
    left_label: str,
    right_label: str,
) -> Dict[str, Any]:
    clusters, details = _workspace_clusters(
        state,
        selected_window=selected_window,
        selected_source=selected_source,
        left_window_kind=left_window_kind,
        right_window_kind=right_window_kind,
        left_label=left_label,
        right_label=right_label,
    )
    return {
        "comparison_id": f"{left_window_kind}-{right_window_kind}",
        "left_window_kind": left_window_kind,
        "right_window_kind": right_window_kind,
        "left_label": left_label,
        "right_label": right_label,
        "clusters": clusters,
        "metrics": {
            "left_feedback_count": len(details["baseline_records"]),
            "right_feedback_count": len(details["current_records"]),
            "cluster_count": len(clusters),
        },
    }


def build_workspace(
    task_ref: TaskRef,
    selected_window: int = 72,
    selected_source: str = "all",
) -> Dict[str, Any]:
    try:
        window = int(selected_window)
    except (TypeError, ValueError) as exc:
        raise ValueError("观察窗口必须是 24、48 或 72 小时。") from exc
    if window not in SUPPORTED_WINDOWS:
        raise ValueError("观察窗口必须是 24、48 或 72 小时。")

    task_dir = _task_dir_from_ref(task_ref)
    state = _read_state(task_dir)
    source = selected_source.strip() or "all"
    available_sources = sorted(
        {
            str(item["source"])
            for item in state.get("imports", [])
            if item.get("status") == "success"
        }
    )
    if source != "all" and source not in available_sources:
        source = "all"

    primary = _comparison_view(
        state,
        selected_window=window,
        selected_source=source,
        left_window_kind="baseline",
        right_window_kind="current",
        left_label="基线",
        right_label="当前",
    )
    clusters = primary["clusters"]
    _add_trajectories(
        state,
        clusters,
        selected_window=window,
        selected_source=source,
    )
    followup = None
    if _has_successful_import(state, "followup"):
        followup = _comparison_view(
            state,
            selected_window=window,
            selected_source=source,
            left_window_kind="current",
            right_window_kind="followup",
            left_label="当前",
            right_label="后续",
        )
    followup_count = followup["metrics"]["right_feedback_count"] if followup else 0
    metrics = {
        "baseline_feedback_count": primary["metrics"]["left_feedback_count"],
        "current_feedback_count": primary["metrics"]["right_feedback_count"],
        "baseline_total": primary["metrics"]["left_feedback_count"],
        "current_total": primary["metrics"]["right_feedback_count"],
        "followup_feedback_count": followup_count,
        "followup_total": followup_count,
        "cluster_count": len(clusters),
        "pending_review_count": sum(
            cluster["review_status"] in {"待复核", "保持观察"}
            for cluster in clusters
        ),
        "confirmed_count": sum(
            cluster["review_status"] == "已确认" for cluster in clusters
        ),
    }
    imports = [
        _public_import(item)
        for item in reversed(state.get("imports", []))
    ]
    task = _public_task(state["task"])
    task["task_dir"] = str(task_dir)
    return {
        "task": task,
        "selected_window": window,
        "selected_source": source,
        "sources": available_sources,
        "metrics": metrics,
        "clusters": clusters,
        "comparisons": [item for item in (primary, followup) if item is not None],
        "followup_comparison": followup,
        "imports": imports,
        "audit_events": list(reversed(deepcopy(state.get("audit_events", [])))),
        "audit": list(reversed(deepcopy(state.get("audit_events", [])))),
        "owner_summary": _owner_summary(task, clusters, window),
        "comparison_boundary": "仅说明问题在发版后新增或加重，不代表问题由该版本导致。",
    }


def render_owner_summary(
    task_ref: TaskRef,
    selected_window: int = 72,
    selected_source: str = "all",
) -> str:
    return build_workspace(
        task_ref,
        selected_window=selected_window,
        selected_source=selected_source,
    )["owner_summary"]


def apply_cluster_action(
    task_ref: TaskRef,
    cluster_id: str,
    action: str,
    *,
    changes: Optional[Dict[str, Any]] = None,
    reason: str = "",
    actor: str = "human",
    selected_window: int = 72,
    selected_source: str = "all",
) -> Dict[str, Any]:
    task_dir = _task_dir_from_ref(task_ref)
    state = _read_state(task_dir)
    action_name = action.strip().lower()
    if action_name not in SUPPORTED_ACTIONS:
        raise ValueError("不支持这项人工操作。")
    workspace = build_workspace(
        task_dir,
        selected_window=selected_window,
        selected_source=selected_source,
    )
    indexed = {item["cluster_id"]: item for item in workspace["clusters"]}
    cluster = indexed.get(cluster_id)
    if cluster is None:
        raise ValueError("找不到要操作的问题簇。")

    clean_reason = reason.strip()
    clean_changes = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in (changes or {}).items()
    }
    if action_name in {"reject", "merge", "split"} and not clean_reason:
        raise ValueError("驳回、合并或拆分问题簇时必须填写操作说明。")
    risk_level = clean_changes.get("risk_level")
    if risk_level and risk_level not in {"P0", "P1", "P2"}:
        raise ValueError("风险等级只能是 P0、P1 或 P2。")

    before = {
        key: cluster.get(key)
        for key in (
            "risk_level",
            "review_status",
            "owner",
            "work_status",
            "next_action",
            "result",
        )
    }
    action_record = {
        "action_id": f"action_{uuid4().hex[:12]}",
        "cluster_id": cluster_id,
        "action": action_name,
        "changes": clean_changes,
        "reason": clean_reason,
        "actor": actor.strip() or "human",
        "timestamp": _now(),
        "selected_window": int(selected_window),
        "selected_source": selected_source,
        "before": before,
    }

    if action_name == "merge":
        target_id = str(clean_changes.get("target_cluster_id", "")).strip()
        if not target_id or target_id not in indexed:
            raise ValueError("目标问题簇不存在。")
        if target_id == cluster_id:
            raise ValueError("问题簇不能合并到自身。")
        mappings = {
            item["source_cluster_id"]: item["target_cluster_id"]
            for item in state.get("merge_rules", [])
        }
        if _resolve_merge_target(target_id, mappings) == cluster_id:
            raise ValueError("该合并会形成循环关系。")
        state.setdefault("merge_rules", []).append(
            {
                "source_cluster_id": cluster_id,
                "target_cluster_id": target_id,
                "created_at": action_record["timestamp"],
                "reason": clean_reason,
            }
        )
    elif action_name == "split":
        feedback_ids_value = clean_changes.get("feedback_ids", [])
        if isinstance(feedback_ids_value, str):
            requested_ids = [
                value.strip()
                for value in re.split(r"[,，\n]+", feedback_ids_value)
                if value.strip()
            ]
        else:
            requested_ids = [str(value).strip() for value in feedback_ids_value if str(value).strip()]
        evidence_ids = {item["evidence_id"] for item in cluster["members"]}
        feedback_matches: Dict[str, set] = {}
        for item in cluster["members"]:
            feedback_matches.setdefault(item["feedback_id"], set()).add(item["evidence_id"])
        requested_tokens = set(requested_ids)
        if not requested_tokens:
            raise ValueError("请填写要拆出的反馈 ID。")
        requested_evidence = set()
        unknown = []
        ambiguous = []
        for token in requested_tokens:
            if token in evidence_ids:
                requested_evidence.add(token)
                continue
            matches = feedback_matches.get(token, set())
            if len(matches) == 1:
                requested_evidence.update(matches)
            elif len(matches) > 1:
                ambiguous.append(token)
            else:
                unknown.append(token)
        if ambiguous:
            raise ValueError(
                "以下反馈 ID 在多个来源中重复，请改用“来源:反馈 ID”拆分："
                + "、".join(sorted(ambiguous))
            )
        if unknown:
            raise ValueError("以下反馈 ID 不属于该问题簇：" + "、".join(unknown))
        if requested_evidence == evidence_ids:
            raise ValueError("不能拆出问题簇的全部成员。")
        split_digest = hashlib.sha1(
            "|".join(sorted(requested_evidence)).encode("utf-8")
        ).hexdigest()[:8]
        new_cluster_id = f"{cluster_id}_split_{split_digest}"
        state.setdefault("split_rules", []).append(
            {
                "source_cluster_id": cluster_id,
                "new_cluster_id": new_cluster_id,
                "evidence_ids": sorted(requested_evidence),
                "title": f"拆分：{cluster['title']}",
                "created_at": action_record["timestamp"],
                "reason": clean_reason,
            }
        )
        action_record["changes"]["new_cluster_id"] = new_cluster_id
        action_record["changes"]["evidence_ids"] = sorted(requested_evidence)

    state.setdefault("cluster_actions", []).append(action_record)
    labels = {
        "confirm": "确认问题簇",
        "reject": "驳回问题簇",
        "keep_open": "保持观察",
        "update": "更新处理记录",
        "merge": "合并问题簇",
        "split": "拆分问题簇",
    }
    _audit(
        state,
        labels[action_name],
        clean_reason or f"已对 {cluster['title']} 执行{labels[action_name]}。",
        actor=action_record["actor"],
        details={
            "cluster_id": cluster_id,
            "before": before,
            "changes": action_record["changes"],
            "selected_window": int(selected_window),
            "selected_source": selected_source,
        },
    )
    state["task"]["updated_at"] = action_record["timestamp"]
    _write_state(task_dir, state)
    return action_record
