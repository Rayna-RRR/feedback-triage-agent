"""Real PostgreSQL integration; TEST_POSTGRES_DSN must name a disposable test DB."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4
from urllib.parse import urlparse

import httpx
import psycopg
from psycopg import sql
import pytest

from feedback_triage_agent import observation, web_app
from feedback_triage_agent.task_storage import PostgresTaskStore, StorageConflict, StorageError


FORM = {
    "name": "SYNTHETIC PostgreSQL acceptance", "product_name": "SYNTHETIC_ONLY",
    "baseline_version": "SYNTHETIC_BASE", "current_version": "SYNTHETIC_CURRENT",
    "baseline_window_start": "2000-01-01T00:00", "baseline_window_end": "2000-01-03T00:00",
    "current_window_start": "2000-01-04T00:00", "current_window_end": "2000-01-06T00:00",
}
P0_TEXTS = [
    "草稿不见了，现在能恢复了吗？",
    "没有广告而且昨晚保存的草稿消失了。",
    "草稿原来没保存，后来保存的草稿今天不见了。",
]


@pytest.fixture
def pg_store():
    dsn = os.getenv("TEST_POSTGRES_DSN", "")
    path = os.getenv("TEST_POSTGRES_DSN_FILE", "")
    if not dsn and path:
        dsn = Path(path).read_text().strip()
    if not dsn:
        pytest.skip("Real PostgreSQL not configured; set TEST_POSTGRES_DSN or TEST_POSTGRES_DSN_FILE")
    store = PostgresTaskStore(dsn, "preview_test_" + uuid4().hex)
    store.initialize_schema()
    yield store
    # Only our randomly generated test namespace; never clear another task.
    with store._connection() as conn:
        conn.execute("DELETE FROM fta_observation_tasks WHERE namespace=%s", (store.namespace,))


def create(store):
    return observation.create_task(store, **FORM)


def import_p0(task, tmp_path):
    import csv
    path = tmp_path / "SYNTHETIC_current.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "source", "review_text", "created_at", "rating"])
        for i, text in enumerate(P0_TEXTS):
            writer.writerow(["SYNTHETIC_F" + str(i), "SYNTHETIC", text, "2000-01-05T12:00", 3])
    observation.add_import(task, source_path=path, window_kind="current", observation_hours=48, source="SYNTHETIC")


def test_whole_task_roundtrip_import_action_audit_and_json_contract(pg_store, tmp_path):
    task = create(pg_store)
    import_p0(task, tmp_path)
    workspace = observation.build_workspace(task, 48)
    data = next(c for c in workspace["clusters"] if c["category"] == "账号、隐私与数据问题")
    assert data["risk_level"] == "P0" and data["review_status"] == "待复核"
    observation.apply_cluster_action(
        task, data["cluster_id"], "confirm", selected_window=48,
        changes={"owner": "SYNTHETIC_QA", "work_status": "处理中", "next_action": "SYNTHETIC 核查可恢复性"},
        reason="SYNTHETIC 确认优先核查",
    )
    other = PostgresTaskStore(pg_store.dsn, pg_store.namespace)
    loaded = observation.load_task(other, task["task_id"])
    persisted = observation._read_state(loaded)
    assert len(persisted["imports"]) == 1
    assert len(persisted["cluster_actions"]) == 1
    assert len(persisted["audit_events"]) == 3
    assert loaded["storage_revision"] == 3
    rebuilt = observation.build_workspace(loaded, 48)
    assert rebuilt["clusters"][0]["owner"] == "SYNTHETIC_QA"
    assert rebuilt["clusters"][0]["review_status"] == "已确认"
    assert observation.list_tasks(other)[0]["task_id"] == task["task_id"]
    # New backend does not introduce non-serializable values or DSNs.
    encoded = json.dumps(rebuilt, ensure_ascii=False)
    assert pg_store.dsn not in encoded
    assert all(text in encoded for text in P0_TEXTS)
    assert "历史内容丢失已恢复" not in encoded


def test_simultaneous_writers_conflict_then_explicit_retry_preserves_both_audits(pg_store):
    task = create(pg_store)
    location = observation._task_dir_from_ref(task)
    snapshots = [observation._read_state(location) for _ in range(2)]
    barrier = threading.Barrier(2)
    def writer(i):
        state = snapshots[i]
        observation._audit(state, "SYNTHETIC writer", str(i))
        barrier.wait(timeout=5)
        try:
            observation._write_state(location, state)
            return "saved", i
        except StorageConflict:
            return "conflict", i
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(writer, range(2)))
    assert sorted(r[0] for r in results) == ["conflict", "saved"]
    after = observation._read_state(location)
    assert after["_storage_revision"] == 2 and len(after["audit_events"]) == 2
    loser = next(i for result, i in results if result == "conflict")
    observation._audit(after, "SYNTHETIC writer", str(loser))
    observation._write_state(location, after)
    final = observation._read_state(location)
    assert final["_storage_revision"] == 3
    assert {e["message"] for e in final["audit_events"][1:]} == {"0", "1"}


def test_database_failure_rolls_back_state_revision_and_audit(pg_store):
    task = create(pg_store)
    location = observation._task_dir_from_ref(task)
    before = observation._read_state(location)
    name = "synthetic_fail_" + uuid4().hex
    with pg_store._connection() as conn:
        conn.execute(sql.SQL(
            "CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'SYNTHETIC rollback test'; RETURN NEW; END $$"
        ).format(sql.Identifier(name)))
        conn.execute(sql.SQL(
            "CREATE TRIGGER {} AFTER UPDATE ON fta_observation_tasks "
            "FOR EACH ROW WHEN (NEW.namespace={}) EXECUTE FUNCTION {}()"
        ).format(sql.Identifier(name), sql.Literal(pg_store.namespace), sql.Identifier(name)))
    try:
        changed = deepcopy(before)
        changed["task"]["name"] = "SYNTHETIC uncommitted change"
        observation._audit(changed, "SYNTHETIC uncommitted audit", "rollback")
        with pytest.raises(StorageError):
            observation._write_state(location, changed)
        assert observation._read_state(location) == before
    finally:
        with pg_store._connection() as conn:
            conn.execute(sql.SQL("DROP TRIGGER {} ON fta_observation_tasks").format(sql.Identifier(name)))
            conn.execute(sql.SQL("DROP FUNCTION {}()").format(sql.Identifier(name)))


def test_namespace_isolation_and_atomic_demo_initialization(pg_store, monkeypatch):
    monkeypatch.setattr(web_app, "get_observation_storage", lambda: pg_store)
    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks = list(executor.map(lambda _: web_app.ensure_demo_task(), range(2)))
    first = observation._read_state(tasks[0])
    assert len(first["imports"]) == 3
    assert len(first["cluster_actions"]) == 1
    assert len(first["audit_events"]) == 5
    observation.append_audit_event(tasks[0], "SYNTHETIC retained", "human record")
    assert web_app.ensure_demo_task()["audit_events"][-1]["action"] == "SYNTHETIC retained"
    isolated = PostgresTaskStore(pg_store.dsn, "preview_other_" + uuid4().hex)
    assert observation.list_tasks(isolated) == []
    with pytest.raises(FileNotFoundError):
        observation.load_task(isolated, tasks[0]["task_id"])


def test_split_merge_and_rejected_import_are_persisted_atomically(pg_store, tmp_path):
    task = create(pg_store)
    path = tmp_path / "SYNTHETIC.csv"
    path.write_text("id,review_text\nSYNTHETIC_C1,页面很慢\nSYNTHETIC_C2,加载太慢\n")
    observation.add_import(task, source_path=path, window_kind="current",
                           observation_hours=48, source="SYNTHETIC")
    cluster = next(c for c in observation.build_workspace(task, 48)["clusters"] if c["current_count"] == 2)
    split = observation.apply_cluster_action(
        task, cluster["cluster_id"], "split", changes={"feedback_ids": ["SYNTHETIC_C2"]},
        reason="SYNTHETIC split", selected_window=48,
    )
    observation.apply_cluster_action(
        task, split["changes"]["new_cluster_id"], "merge",
        changes={"target_cluster_id": cluster["cluster_id"]},
        reason="SYNTHETIC merge", selected_window=48,
    )
    before = observation._read_state(task)
    assert len(before["split_rules"]) == len(before["merge_rules"]) == 1
    assert len(before["cluster_actions"]) == 2
    invalid = tmp_path / "SYNTHETIC_invalid.csv"
    invalid.write_text("id,review_text\nSYNTHETIC_DUP,页面很慢\nSYNTHETIC_DUP,页面很慢\n")
    with pytest.raises(ValueError):
        observation.add_import(task, source_path=invalid, window_kind="current",
                               observation_hours=48, source="SYNTHETIC")
    after = observation._read_state(task)
    assert after["imports"][-1]["status"] == "failed"
    assert len(after["audit_events"]) == len(before["audit_events"]) + 1
    assert after["split_rules"] == before["split_rules"]
    assert after["merge_rules"] == before["merge_rules"]
    reread = observation.load_task(PostgresTaskStore(pg_store.dsn, pg_store.namespace), task["task_id"])
    assert observation.build_workspace(reread, 48)["clusters"][0]["current_count"] == 2


def revision(html):
    return re.search(r'name="state_revision" value="(\d+)"', html)[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def two_apps(pg_store, tmp_path):
    root = Path(__file__).resolve().parents[1]
    processes, clients = [], []
    def start(label, port=None):
        port = port or free_port()
        env = os.environ.copy()
        env.update(
            VERCEL="1", VERCEL_ENV="preview", VERCEL_REGION="SYNTHETIC_SAME_REGION",
            VERCEL_GIT_COMMIT_SHA=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
            VERCEL_DEPLOYMENT_ID="dpl_SYNTHETIC_LOCAL_TEST",
            FEEDBACK_RISK_STORAGE_BACKEND="postgresql",
            FEEDBACK_RISK_DATABASE_URL=pg_store.dsn, FEEDBACK_RISK_DB_NAMESPACE=pg_store.namespace,
            FEEDBACK_RISK_TASKS_DIR=str(tmp_path / label / "unused-task-files"),
            FEEDBACK_TRIAGE_WEB_RUNS_DIR=str(tmp_path / label / "legacy-runs"),
            FEEDBACK_TRIAGE_WEB_LLM_ENABLED="false", DEEPSEEK_API_KEY="", PYTHONPATH=str(root),
        )
        log = (tmp_path / (label + ".log")).open("w")
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "feedback_triage_agent.web_app:app",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=root, env=env, stdout=log, stderr=log,
        )
        processes.append((process, log))
        client = httpx.Client(base_url="http://127.0.0.1:" + str(port), timeout=15, trust_env=False)
        clients.append(client)
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail("Synthetic application process failed; inspect its local log.")
            try:
                if client.get("/healthz").status_code == 200:
                    return process, client
            except httpx.TransportError:
                pass
            time.sleep(.05)
        pytest.fail("Synthetic application health did not become ready.")
    try:
        a = start("app_a")
        b = start("app_b")
        yield a, b, start
    finally:
        for client in clients:
            client.close()
        for process, log in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
            log.close()


def test_independent_app_processes_restart_stale_forms_and_shared_audit(two_apps, pg_store, tmp_path):
    (process_a, a), (_, b), start = two_apps
    health_a, health_b = a.get("/healthz").json(), b.get("/healthz").json()
    assert health_a["process_start_id"] != health_b["process_start_id"]
    assert health_a["commit_sha"] == health_b["commit_sha"] != "unknown"
    assert health_a["storage_backend"] == health_b["storage_backend"] == "postgresql"
    created = a.post("/tasks", data=FORM, follow_redirects=False, headers={"X-Request-ID": "synthetic_create_A"})
    assert created.status_code == 303
    path = urlparse(created.headers["location"]).path
    page = b.get(path + "?window=48")
    assert page.status_code == 200 and FORM["name"] in page.text
    csv_text = "id,review_text,created_at,rating\n" + "\n".join(
        f"SYNTHETIC_F{i},{text},2000-01-05T12:00,3" for i, text in enumerate(P0_TEXTS)
    )
    imported = a.post(path + "/imports", data={
        "window_kind": "current", "observation_hours": "48", "source": "SYNTHETIC",
        "state_revision": revision(page.text),
    }, files={"file": ("SYNTHETIC.csv", csv_text.encode(), "text/csv")}, follow_redirects=False)
    assert imported.status_code == 303
    page = b.get(path + "?window=48")
    assert all(text in page.text for text in P0_TEXTS)
    assert "历史内容丢失已恢复" not in page.text
    task_id = path.rsplit("/", 1)[1]
    workspace = observation.build_workspace(observation.load_task(pg_store, task_id), 48)
    cluster = next(c for c in workspace["clusters"] if c["category"] == "账号、隐私与数据问题")
    assert cluster["risk_level"] == "P0" and cluster["review_status"] == "待复核"
    action_url = path + "/clusters/" + cluster["cluster_id"] + "/actions"
    stale_version = revision(page.text)
    confirmed = b.post(action_url, data={
        "action": "confirm", "owner": "SYNTHETIC_QA_B", "work_status": "处理中",
        "next_action": "SYNTHETIC 核查可恢复性", "note": "SYNTHETIC human confirm",
        "selected_window": "48", "state_revision": stale_version,
    }, follow_redirects=False)
    assert confirmed.status_code == 303
    stale = a.post(action_url, data={
        "action": "update", "owner": "SYNTHETIC_STALE_OWNER", "selected_window": "48",
        "state_revision": stale_version,
    }, follow_redirects=False)
    assert stale.status_code == 409 and "本次修改未保存" in stale.text
    process_a.terminate()
    process_a.wait(timeout=10)
    _, restarted = start("app_a_restarted")
    assert restarted.get("/healthz").json()["process_start_id"] != health_a["process_start_id"]
    refreshed = restarted.get(path + "?window=48")
    assert refreshed.status_code == 200
    assert "SYNTHETIC_QA_B" in refreshed.text and "SYNTHETIC_STALE_OWNER" not in refreshed.text
    assert "SYNTHETIC human confirm" in refreshed.text
    current = observation._read_state(observation.load_task(pg_store, task_id))
    assert len(current["cluster_actions"]) == 1 and len(current["audit_events"]) == 3
    assert not list(tmp_path.glob("*/unused-task-files"))
    logs = "\n".join(p.read_text() for p in tmp_path.glob("app_*.log"))
    assert pg_store.dsn not in logs
    assert all(text not in logs for text in P0_TEXTS)
    assert "SYNTHETIC human confirm" not in logs
    events = [json.loads(line) for line in logs.splitlines() if line.startswith('{"commit_sha"')]
    assert any(e["request_id"] == "synthetic_create_A" and e["operation"] == "create" for e in events)
    assert any(e["process_start_id"] == health_b["process_start_id"] and e["operation"] == "save" for e in events)
