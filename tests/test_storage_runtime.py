from fastapi.testclient import TestClient

from feedback_triage_agent import web_app
import json
import pytest
import psycopg
from feedback_triage_agent.task_storage import configured_storage, StorageConfigurationError
from feedback_triage_agent import storage_runtime


def test_vercel_unconfigured_storage_does_not_claim_success(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "production")
    for name in ("FEEDBACK_RISK_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(web_app, "OBSERVATION_TASKS_DIR", tmp_path / "tasks")
    client = TestClient(web_app.app)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["storage_backend"] == "postgresql"
    assert response.json()["storage_available"] is False
    assert not (tmp_path / "tasks").exists()


def test_vercel_missing_commit_is_explicitly_unknown(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setattr(web_app, "OBSERVATION_TASKS_DIR", tmp_path / "tasks")
    payload = TestClient(web_app.app).get("/healthz").json()
    assert payload["commit_sha"] == "unknown"


def test_vercel_json_override_is_rejected(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("FEEDBACK_RISK_STORAGE_BACKEND", "json")
    with pytest.raises(StorageConfigurationError):
        configured_storage("/tmp/unused")


def test_preview_namespace_is_stable_isolated_and_fail_closed(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("FEEDBACK_RISK_DATABASE_URL", "postgresql://synthetic")
    monkeypatch.delenv("FEEDBACK_RISK_DB_NAMESPACE", raising=False)
    monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", "synthetic-branch-a")
    first = configured_storage("/tmp/unused").namespace
    assert first.startswith("preview_")
    assert first == configured_storage("/tmp/another-instance").namespace
    monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", "synthetic-branch-b")
    assert configured_storage("/tmp/unused").namespace != first
    monkeypatch.setenv("FEEDBACK_RISK_DB_NAMESPACE", "production")
    with pytest.raises(StorageConfigurationError):
        configured_storage("/tmp/unused")


def test_diagnostics_allowlist_and_unavailable_database_are_redacted(monkeypatch, caplog):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "a" * 40)
    monkeypatch.setenv("VERCEL_DEPLOYMENT_ID", "dpl_SYNTHETIC")
    secret = "postgresql://user:DO_NOT_LOG_PASSWORD@synthetic/database"
    monkeypatch.setenv("FEEDBACK_RISK_DATABASE_URL", secret)
    def fail(*args, **kwargs):
        raise psycopg.OperationalError(secret + " PRIVATE_FEEDBACK_SENTINEL")
    monkeypatch.setattr(psycopg, "connect", fail)
    storage_runtime.logger.addHandler(caplog.handler)
    try:
        client = TestClient(web_app.app)
        health = client.get("/healthz", headers={"X-Request-ID": "synthetic_request"})
        creation = client.post("/tasks", data={
            "name": "SYNTHETIC", "product_name": "SYNTHETIC", "baseline_version": "base",
            "current_version": "current", "baseline_window_start": "2000-01-01T00:00",
            "baseline_window_end": "2000-01-03T00:00", "current_window_start": "2000-01-04T00:00",
            "current_window_end": "2000-01-06T00:00", "change_summary": "PRIVATE_FEEDBACK_SENTINEL",
        })
        listing = client.get("/")
    finally:
        storage_runtime.logger.removeHandler(caplog.handler)
    assert health.status_code == 503
    assert listing.status_code == 503
    assert creation.status_code == 503
    payload = health.json()
    assert payload["commit_sha"] == "a" * 40
    assert payload["deployment_id"] == "dpl_SYNTHETIC"
    assert payload["storage_available"] is False
    assert secret not in health.text + listing.text + caplog.text
    assert "PRIVATE_FEEDBACK_SENTINEL" not in caplog.text
    events = [json.loads(r.message) for r in caplog.records if r.name == storage_runtime.logger.name]
    event = next(e for e in events if e["operation"] == "health")
    assert any(e["operation"] == "create" and e["result"] == "unavailable" and e["task_id"] for e in events)
    assert event["request_id"] == "synthetic_request"
    assert set(event) == {"commit_sha", "process_start_id", "deployment_id", "request_id",
                          "operation", "storage_backend", "task_id", "result"}
