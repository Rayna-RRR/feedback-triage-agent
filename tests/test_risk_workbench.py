from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from feedback_triage_agent import observation, web_app


def client_with_tmp_storage(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(web_app, "OBSERVATION_TASKS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(web_app, "WEB_RUNS_DIR", tmp_path / "web_runs")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("FEEDBACK_TRIAGE_WEB_LLM_ENABLED", raising=False)
    return TestClient(web_app.app)


def task_form(**overrides: str) -> dict:
    values = {
        "name": "智能回复 v2.4 发版观察",
        "product_name": "Acme Copilot",
        "baseline_version": "v2.3",
        "current_version": "v2.4",
        "baseline_window_start": "2026-06-01T00:00",
        "baseline_window_end": "2026-06-04T00:00",
        "current_window_start": "2026-07-01T00:00",
        "current_window_end": "2026-07-04T00:00",
        "comparison_basis": "equivalent_window",
        "comparison_note": "",
        "change_summary": "灰度发布智能回复能力。",
    }
    values.update(overrides)
    return values


def create_task(client: TestClient, **overrides: str) -> str:
    response = client.post(
        "/tasks",
        data=task_form(**overrides),
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    path = urlparse(response.headers["location"]).path
    assert path.startswith("/tasks/")
    return path.rsplit("/", 1)[-1]


def import_feedback(
    client: TestClient,
    task_id: str,
    csv_text: str,
    *,
    window_kind: str,
    observation_hours: int = 72,
    source: str = "App Store",
    import_mode: Optional[str] = "cumulative",
    filename: str = "feedback.csv",
):
    data = {
        "window_kind": window_kind,
        "observation_hours": str(observation_hours),
        "source": source,
    }
    if import_mode is not None:
        data["import_mode"] = import_mode
    return client.post(
        f"/tasks/{task_id}/imports",
        data=data,
        files={"file": (filename, csv_text.encode("utf-8"), "text/csv")},
        follow_redirects=False,
    )


def test_workbench_homepage_and_storage_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_storage(tmp_path, monkeypatch)

    response = client.get("/")

    assert response.status_code == 200
    assert "发版后反馈风险工作台" in response.text
    assert "同等窗口" in response.text
    assert "累计快照" in response.text
    assert "还没有观察任务" in response.text
    assert "相关不等于因果" in response.text
    assert str(web_app.OBSERVATION_TASKS_DIR) in response.text
    assert "当前版本不接数据库、账号或付费存储" in response.text

    monkeypatch.setenv("VERCEL", "1")
    online_response = client.get("/")
    assert online_response.status_code == 200
    assert "线上 Demo 使用临时文件存储" in online_response.text
    assert "实例回收后任务可能丢失" in online_response.text
    assert "请勿上传敏感或生产数据" in online_response.text
    assert client.get("/healthz").json()["observation_storage"] == "temporary"


def test_task_creation_enforces_and_labels_comparison_basis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_storage(tmp_path, monkeypatch)

    task_id = create_task(client)
    saved = observation.load_task(web_app.OBSERVATION_TASKS_DIR, task_id)
    assert saved["comparison_basis"] == "equivalent_window"

    workspace = client.get(f"/tasks/{task_id}?window=72")
    assert workspace.status_code == 200
    assert "同等窗口" in workspace.text
    assert "当前不是同等窗口比较" not in workspace.text

    unequal = client.post(
        "/tasks",
        data=task_form(
            name="错误的同等窗口",
            current_window_end="2026-07-03T00:00",
        ),
    )
    assert unequal.status_code == 400
    assert "同等窗口要求基线与当前窗口长度一致" in unequal.text

    missing_note = client.post(
        "/tasks",
        data=task_form(
            name="未说明的其他口径",
            comparison_basis="other",
            comparison_note="",
            current_window_end="2026-07-03T00:00",
        ),
    )
    assert missing_note.status_code == 400
    assert "必须填写口径说明" in missing_note.text

    other_task_id = create_task(
        client,
        name="活动期非同等窗口",
        comparison_basis="other",
        comparison_note="<b>当前窗口处于营销活动期</b>",
        current_window_end="2026-07-03T00:00",
    )
    other_workspace = client.get(f"/tasks/{other_task_id}")
    assert other_workspace.status_code == 200
    assert "非同等口径" in other_workspace.text
    assert "&lt;b&gt;当前窗口处于营销活动期&lt;/b&gt;" in other_workspace.text
    assert "<b>当前窗口处于营销活动期</b>" not in other_workspace.text


def test_missing_rating_cumulative_replacement_and_incremental_deduplication(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_storage(tmp_path, monkeypatch)
    task_id = create_task(client, name="导入模式验证")

    first = import_feedback(
        client,
        task_id,
        "id,review_text\nb1,页面很慢\nb2,登录后闪退\n",
        window_kind="baseline",
    )
    assert first.status_code == 303

    replacement = import_feedback(
        client,
        task_id,
        "id,review_text\nb1,页面很慢\nb3,复制按钮没反应\n",
        window_kind="baseline",
        import_mode=None,
    )
    assert replacement.status_code == 303

    incremental = import_feedback(
        client,
        task_id,
        "id,review_text\nb3,复制按钮没反应\nb4,回答经常不准确\n",
        window_kind="baseline",
        import_mode="incremental",
    )
    assert incremental.status_code == 303

    task = observation.load_task(web_app.OBSERVATION_TASKS_DIR, task_id)
    assert [item["import_mode"] for item in task["imports"]] == [
        "cumulative",
        "cumulative",
        "incremental",
    ]
    assert task["imports"][-1]["accepted_count"] == 1
    assert task["imports"][-1]["duplicate_count"] == 1
    assert task["imports"][-1]["missing_rating_count"] == 2

    workspace = observation.build_workspace(task, selected_window=72)
    assert workspace["metrics"]["baseline_feedback_count"] == 3
    member_ids = {
        member["feedback_id"]
        for cluster in workspace["clusters"]
        for member in cluster["members"]
    }
    assert "b2" not in member_ids
    assert {"b1", "b3", "b4"}.issubset(member_ids)


def test_issue_cluster_keeps_raw_evidence_and_escapes_user_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_storage(tmp_path, monkeypatch)
    task_id = create_task(client, name="问题簇证据验证")

    baseline = import_feedback(
        client,
        task_id,
        (
            "id,review_text\n"
            "b1,旧版本偶发闪退并且草稿丢失\n"
            "b2,旧版本登录验证码收不到\n"
        ),
        window_kind="baseline",
    )
    current = import_feedback(
        client,
        task_id,
        (
            "id,review_text\n"
            "c1,更新后频繁崩溃并且内容丢失\n"
            'c2,"<script>alert(1)</script> 页面闪退，草稿丢失"\n'
        ),
        window_kind="current",
    )
    assert baseline.status_code == 303
    assert current.status_code == 303

    task = observation.load_task(web_app.OBSERVATION_TASKS_DIR, task_id)
    workspace = observation.build_workspace(task, selected_window=72)
    crash_cluster = next(
        cluster
        for cluster in workspace["clusters"]
        if cluster["title"] == "崩溃、闪退或内容丢失"
    )
    assert crash_cluster["baseline_count"] == 1
    assert crash_cluster["current_count"] == 2
    assert len(crash_cluster["members"]) == 3
    assert crash_cluster["change_status"] == "加重"

    page = client.get(f"/tasks/{task_id}?window=72")
    assert page.status_code == 200
    assert "旧版本偶发闪退并且草稿丢失" in page.text
    assert "更新后频繁崩溃并且内容丢失" in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    assert "<script>alert(1)</script>" not in page.text
    assert "3 条成员反馈" in page.text
    assert "6 条成员反馈" not in page.text
    assert "评分 None" not in page.text


def test_confirm_action_populates_owner_summary_and_audit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_storage(tmp_path, monkeypatch)
    task_id = create_task(client, name="人工复核验证")
    import_feedback(
        client,
        task_id,
        "id,review_text\nb1,旧版本偶发闪退\n",
        window_kind="baseline",
    )
    import_feedback(
        client,
        task_id,
        "id,review_text\nc1,当前版本频繁崩溃并且草稿丢失\n",
        window_kind="current",
    )
    task = observation.load_task(web_app.OBSERVATION_TASKS_DIR, task_id)
    cluster = observation.build_workspace(task, selected_window=72)["clusters"][0]

    response = client.post(
        f"/tasks/{task_id}/clusters/{cluster['cluster_id']}/actions",
        data={
            "action": "confirm",
            "risk_level": "P1",
            "owner": "移动端团队",
            "work_status": "处理中",
            "next_action": "排查崩溃堆栈",
            "result": "等待 72h 后复验",
            "note": "已核对三条原始反馈",
        },
        headers={"referer": f"http://testserver/tasks/{task_id}?window=72&source=all"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    refreshed_task = observation.load_task(web_app.OBSERVATION_TASKS_DIR, task_id)
    workspace = observation.build_workspace(refreshed_task, selected_window=72)
    confirmed = next(
        item for item in workspace["clusters"] if item["cluster_id"] == cluster["cluster_id"]
    )
    assert confirmed["review_status"] == "已确认"
    assert confirmed["owner"] == "移动端团队"
    assert "移动端团队" in workspace["owner_summary"]
    assert "排查崩溃堆栈" in workspace["owner_summary"]
    assert any(event["action"] == "确认问题簇" for event in workspace["audit_events"])

    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert "风险结论已确认" in page.text
    assert "已核对三条原始反馈" in page.text
    assert "移动端团队" in page.text


def test_failed_import_is_audited_and_uses_post_redirect_get(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_storage(tmp_path, monkeypatch)
    task_id = create_task(client, name="失败导入审计")

    response = import_feedback(
        client,
        task_id,
        "not a csv",
        window_kind="current",
        filename="notes.txt",
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    task = observation.load_task(web_app.OBSERVATION_TASKS_DIR, task_id)
    assert task["audit_events"][-1]["action"] == "导入失败"
    assert "CSV" in task["audit_events"][-1]["message"]
    error_page = client.get(response.headers["location"])
    assert error_page.status_code == 200
    assert "上传文件必须是 CSV 格式" in error_page.text


def test_legacy_run_route_remains_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_storage(tmp_path, monkeypatch)

    response = client.post(
        "/run",
        data={
            "data_source": "sample",
            "rule_only": "on",
            "generate_html": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/runs/")
    result_page = client.get(response.headers["location"])
    assert result_page.status_code == 200
    assert "运行总览" in result_page.text
    assert "自动化回归测试" in result_page.text


def test_templates_do_not_claim_fixed_test_or_ci_results() -> None:
    rendered_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in web_app.TEMPLATES_DIR.glob("*.html")
    )

    assert "106 tests passed" not in rendered_sources
    assert "GitHub Actions CI passed" not in rendered_sources


def test_web_followup_import_keeps_current_count_and_renders_two_rounds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_storage(tmp_path, monkeypatch)
    task_id = create_task(
        client,
        baseline_window_start="2026-07-01T00:00",
        baseline_window_end="2026-07-03T00:00",
        current_window_start="2026-07-03T00:00",
        current_window_end="2026-07-05T00:00",
        followup_window_start="2026-07-05T00:00",
        followup_window_end="2026-07-07T00:00",
    )
    for kind, rows in (
        ("baseline", "id,created_at,version,review_text\nb1,2026-07-02T01:00+08:00,v2.3,登录失败\n"),
        ("current", "id,created_at,version,review_text\nc1,2026-07-04T01:00+08:00,v2.4,登录还是失败\n"),
        ("followup", "id,created_at,version,review_text\nf1,2026-07-06T01:00+08:00,v2.4,登录失败次数增加\n"),
    ):
        response = import_feedback(
            client,
            task_id,
            rows,
            window_kind=kind,
            observation_hours=48,
            filename=f"{kind}.csv",
        )
        assert response.status_code == 303

    workspace_page = client.get(f"/tasks/{task_id}?window=48")
    assert workspace_page.status_code == 200
    assert "当前相对基线" in workspace_page.text
    assert "后续相对当前" in workspace_page.text
    assert "后续版本窗口" in workspace_page.text
    assert "产品版本：v2.4" in workspace_page.text
    assert "窗口起止（后续窗口）：2026-07-05T00:00 → 2026-07-07T00:00" in workspace_page.text

    workspace = observation.build_workspace(
        observation.load_task(web_app.OBSERVATION_TASKS_DIR, task_id),
        selected_window=48,
    )
    assert workspace["metrics"]["current_feedback_count"] == 1
    assert workspace["metrics"]["followup_feedback_count"] == 1


def test_web_duplicate_import_reports_rejection_and_does_not_write_feedback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_storage(tmp_path, monkeypatch)
    task_id = create_task(client)
    response = import_feedback(
        client,
        task_id,
        "id,created_at,review_text\ndup,2026-07-02T01:00+08:00,第一条\ndup,2026-07-02T02:00+08:00,第二条\n",
        window_kind="current",
        filename="duplicate.csv",
    )
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert "文件内部存在重复反馈 ID" in page.text
    task = observation.load_task(web_app.OBSERVATION_TASKS_DIR, task_id)
    assert task["imports"][0]["status"] == "failed"
    assert observation.build_workspace(task, selected_window=72)["metrics"]["current_feedback_count"] == 0
