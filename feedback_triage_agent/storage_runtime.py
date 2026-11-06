"""Request-scoped, allowlisted diagnostics. Never serialize state or exceptions."""
from contextvars import ContextVar
import json
import logging
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4


request_id = ContextVar("observation_request_id", default="outside_request")
logger = logging.getLogger("feedback_triage_agent.observation_storage")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.propagate = False
_pid = os.getpid()
_process_start_id = uuid4().hex


def _local_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
            stderr=subprocess.DEVNULL, text=True, timeout=2,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


_local_commit_sha = _local_commit() if not os.getenv("VERCEL") else "unknown"


def runtime_identity():
    global _pid, _process_start_id
    if os.getpid() != _pid:  # Also distinguish workers forked after import.
        _pid, _process_start_id = os.getpid(), uuid4().hex
    sha = os.getenv("VERCEL_GIT_COMMIT_SHA", "") if os.getenv("VERCEL") else _local_commit_sha
    return {
        "commit_sha": sha if re.fullmatch(r"[0-9a-fA-F]{40}", sha or "") else "unknown",
        "process_start_id": _process_start_id,
        "deployment_id": os.getenv("VERCEL_DEPLOYMENT_ID") or ("unknown" if os.getenv("VERCEL") else "local"),
    }


def storage_event(operation, backend, result, task_id=None):
    event = {
        **runtime_identity(), "request_id": request_id.get(),
        "operation": operation, "storage_backend": backend,
        "task_id": task_id, "result": result,
    }
    logger.info(json.dumps(event, ensure_ascii=False))

