"""Whole-task PostgreSQL persistence, isolated by deployment namespace."""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re

import psycopg
from psycopg.types.json import Jsonb

from feedback_triage_agent.storage_runtime import storage_event


class StorageError(Exception):
    status_code = 503
    code = "unavailable"

    def __init__(self, message="观察任务存储暂时不可用，本次操作未确认保存。请重新打开任务核对后再试。"):
        super().__init__(message)


class StorageConfigurationError(StorageError):
    code = "unconfigured"

    def __init__(self):
        super().__init__("观察任务存储尚未正确配置，当前无法创建、读取或保存任务。")


class StorageConflict(StorageError):
    status_code = 409
    code = "conflict"

    def __init__(self):
        super().__init__("任务已被另一项操作更新，本次修改未保存。请刷新后重新核对并提交。")


class DatabaseTaskRef(str):
    """An opaque, JSON-serializable locator carrying a server-only store handle."""

    def __new__(cls, store, task_id):
        ref = super().__new__(cls, "postgresql:" + store.namespace + ":" + task_id)
        ref.store, ref.task_id = store, task_id
        return ref

    def __deepcopy__(self, memo):
        return self


@dataclass(frozen=True)
class PostgresTaskStore:
    dsn: str = field(repr=False)
    namespace: str

    def __post_init__(self):
        if not self.dsn or not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", self.namespace):
            raise StorageConfigurationError()

    def ref(self, task_id):
        if not re.fullmatch(r"task_[A-Za-z0-9_-]+", task_id):
            raise ValueError("任务 ID 不合法。")
        return DatabaseTaskRef(self, task_id)

    def _connection(self):
        # One short-lived connection per operation, compatible with Neon pooling.
        conn = psycopg.connect(self.dsn, connect_timeout=5)
        try:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            conn.execute("SET LOCAL lock_timeout = '5s'")
        except psycopg.Error:
            conn.close()
            raise
        return conn

    def initialize_schema(self):
        try:
            with self._connection() as conn:
                conn.execute((Path(__file__).parent / "sql" / "observation_tasks.sql").read_text())
        except psycopg.Error:
            storage_event("initialize_schema", "postgresql", "unavailable")
            raise StorageError() from None

    def available(self):
        try:
            with self._connection() as conn:
                conn.execute("SELECT revision, state FROM fta_observation_tasks LIMIT 0")
        except psycopg.Error:
            storage_event("health", "postgresql", "unavailable")
            raise StorageError() from None
        return True

    def load(self, task_id):
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT state, revision FROM fta_observation_tasks WHERE namespace=%s AND task_id=%s",
                    (self.namespace, task_id),
                ).fetchone()
        except psycopg.Error:
            storage_event("read", "postgresql", "unavailable", task_id)
            raise StorageError() from None
        if row is None:
            storage_event("read", "postgresql", "not_found", task_id)
            raise FileNotFoundError("找不到这个观察任务。")
        state = deepcopy(row[0])
        state["_storage_revision"] = row[1]
        storage_event("read", "postgresql", "success", task_id)
        return state

    def save(self, task_id, state):
        expected = state.get("_storage_revision")
        payload = {k: v for k, v in state.items() if k != "_storage_revision"}
        operation = "create" if expected is None else "save"
        try:
            # State, imports, decisions, rules and audit are a single JSONB value.
            # The revision predicate is rechecked after any concurrent row lock.
            with self._connection() as conn:
                if expected is None:
                    row = conn.execute(
                        "INSERT INTO fta_observation_tasks(namespace,task_id,state) VALUES (%s,%s,%s) "
                        "ON CONFLICT DO NOTHING RETURNING revision",
                        (self.namespace, task_id, Jsonb(payload)),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "UPDATE fta_observation_tasks SET state=%s,revision=revision+1,updated_at=clock_timestamp() "
                        "WHERE namespace=%s AND task_id=%s AND revision=%s RETURNING revision",
                        (Jsonb(payload), self.namespace, task_id, expected),
                    ).fetchone()
                if row is None:
                    raise StorageConflict()
            state["_storage_revision"] = row[0]  # Only after the commit succeeded.
        except StorageConflict:
            storage_event(operation, "postgresql", "conflict", task_id)
            raise
        except psycopg.Error:
            storage_event(operation, "postgresql", "unavailable", task_id)
            raise StorageError() from None
        storage_event(operation, "postgresql", "success", task_id)

    def task_refs(self):
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT task_id FROM fta_observation_tasks WHERE namespace=%s ORDER BY updated_at DESC",
                    (self.namespace,),
                ).fetchall()
        except psycopg.Error:
            storage_event("list", "postgresql", "unavailable")
            raise StorageError() from None
        storage_event("list", "postgresql", "success")
        return [self.ref(row[0]) for row in rows]


def configured_backend():
    value = os.getenv("FEEDBACK_RISK_STORAGE_BACKEND", "").strip()
    return value or ("postgresql" if os.getenv("VERCEL") else "json")


def configured_storage(local_root):
    backend = configured_backend()
    if backend == "json" and not os.getenv("VERCEL"):
        return Path(local_root)
    if backend != "postgresql":
        raise StorageConfigurationError()
    dsn = next((os.getenv(k, "").strip() for k in
                ("FEEDBACK_RISK_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL")
                if os.getenv(k, "").strip()), "")
    if not dsn:
        raise StorageConfigurationError()
    namespace = os.getenv("FEEDBACK_RISK_DB_NAMESPACE", "").strip()
    if os.getenv("VERCEL_ENV") == "preview":
        if not namespace:
            branch = os.getenv("VERCEL_GIT_COMMIT_REF", "")
            if not branch:
                raise StorageConfigurationError()
            namespace = "preview_" + hashlib.sha256(branch.encode()).hexdigest()[:20]
        if not namespace.startswith(("preview_", "preview-")):
            raise StorageConfigurationError()
    elif not namespace:
        if os.getenv("VERCEL") and os.getenv("VERCEL_ENV") != "production":
            raise StorageConfigurationError()
        namespace = "production" if os.getenv("VERCEL") else "local"
    return PostgresTaskStore(dsn, namespace)

