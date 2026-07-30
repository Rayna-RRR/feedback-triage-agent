import os
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from feedback_triage_agent import web_app
from feedback_triage_agent.models import LLMTaskIntent


def client_with_tmp_runs(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(web_app, "WEB_RUNS_DIR", tmp_path / "web_runs")
    monkeypatch.setattr(
        web_app,
        "OBSERVATION_TASKS_DIR",
        tmp_path / "observation_tasks",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("FEEDBACK_TRIAGE_WEB_LLM_ENABLED", raising=False)
    return TestClient(web_app.app)


def post_builtin_run(client: TestClient, data_source: str):
    return client.post(
        "/run",
        data={
            "data_source": data_source,
            "rule_only": "on",
            "generate_html": "on",
        },
        follow_redirects=False,
    )


def test_web_homepage_is_accessible(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = client.get("/")

    assert response.status_code == 200
    assert "发版反馈风险工作台" in response.text
    assert "v1.0.0" in response.text
    assert "创建版本观察任务" in response.text
    assert "还没有观察任务" in response.text
    assert "同等窗口" in response.text
    assert "累计快照" in response.text
    assert "相关不等于因果" in response.text
    assert "规则引擎 + 人工复核" in response.text
    assert "106 tests passed" not in response.text
    assert "GitHub Actions CI passed" not in response.text
    assert "v0.9.0" not in response.text
    assert "risk_workspace.css" in response.text
    section_ids = ['id="create-task"', 'id="method"']
    section_positions = [response.text.index(section_id) for section_id in section_ids]
    assert section_positions == sorted(section_positions)


def test_healthz_reports_deepseek_key_status_without_exposing_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    response = client.get("/")

    assert response.status_code == 200
    assert "test-key" not in response.text

    health_response = client.get("/healthz")
    payload = health_response.json()
    assert payload["deepseek_api_key_present"] is True
    assert payload["web_llm_flag_enabled"] is False
    assert payload["web_llm_enabled"] is False


def test_web_brand_mark_replaces_old_ft_icons() -> None:
    base_html = (web_app.TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
    app_css = (web_app.STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert "fill='%23111827'" not in base_html
    assert "content: \"FT\"" not in app_css
    assert "radial-gradient(circle at 16px 10px" in app_css


def test_healthz_reports_web_runtime_state(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["sample_feedback_available"] is True
    assert payload["ai_reviews_available"] is True
    assert payload["web_runs_dir"] == str(web_app.WEB_RUNS_DIR)
    assert payload["observation_tasks_dir"] == str(web_app.OBSERVATION_TASKS_DIR)
    assert payload["observation_storage"] == "local_files"
    assert payload["web_llm_enabled"] is False
    assert payload["deepseek_api_key_present"] is False
    assert payload["web_llm_flag_enabled"] is False


def test_resolve_web_runs_dir_prefers_env_and_uses_tmp_on_vercel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    custom_dir = tmp_path / "custom-runs"
    monkeypatch.setenv("FEEDBACK_TRIAGE_WEB_RUNS_DIR", str(custom_dir))
    monkeypatch.setenv("VERCEL", "1")
    assert web_app.resolve_web_runs_dir() == custom_dir

    monkeypatch.delenv("FEEDBACK_TRIAGE_WEB_RUNS_DIR")
    assert web_app.resolve_web_runs_dir() == web_app.DEPLOY_WEB_RUNS_DIR

    monkeypatch.delenv("VERCEL")
    assert web_app.resolve_web_runs_dir() == web_app.LOCAL_WEB_RUNS_DIR


def test_resolve_observation_tasks_dir_prefers_env_and_uses_tmp_on_vercel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    custom_dir = tmp_path / "custom-observations"
    monkeypatch.setenv("FEEDBACK_RISK_TASKS_DIR", str(custom_dir))
    monkeypatch.setenv("VERCEL", "1")
    assert web_app.resolve_observation_tasks_dir() == custom_dir

    monkeypatch.delenv("FEEDBACK_RISK_TASKS_DIR")
    assert (
        web_app.resolve_observation_tasks_dir()
        == web_app.DEPLOY_OBSERVATION_TASKS_DIR
    )

    monkeypatch.delenv("VERCEL")
    assert (
        web_app.resolve_observation_tasks_dir()
        == web_app.LOCAL_OBSERVATION_TASKS_DIR
    )


def test_cleanup_web_runs_removes_expired_runs_and_limits_retention(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runs_dir = tmp_path / "web_runs"
    runs_dir.mkdir()
    monkeypatch.setattr(web_app, "WEB_RUNS_DIR", runs_dir)
    monkeypatch.setattr(web_app, "RUN_RETENTION_HOURS", 24)
    monkeypatch.setattr(web_app, "MAX_WEB_RUNS", 2)
    now = 1_700_000_000
    old_dir = runs_dir / "run_20200101_000000"
    first_recent = runs_dir / "run_20260101_000000"
    second_recent = runs_dir / "run_20260101_000001"
    third_recent = runs_dir / "run_20260101_000002"
    unrelated = runs_dir / "keep-me"
    for path in [old_dir, first_recent, second_recent, third_recent, unrelated]:
        path.mkdir()
    os.utime(old_dir, (now - 90_000, now - 90_000))
    os.utime(first_recent, (now - 300, now - 300))
    os.utime(second_recent, (now - 200, now - 200))
    os.utime(third_recent, (now - 100, now - 100))
    os.utime(unrelated, (now - 90_000, now - 90_000))

    web_app.cleanup_web_runs(now=now)

    assert not old_dir.exists()
    assert not first_recent.exists()
    assert second_recent.exists()
    assert third_recent.exists()
    assert unrelated.exists()


def test_web_run_sample_feedback_success(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = post_builtin_run(client, "sample")

    assert response.status_code == 303
    result_url = response.headers["location"]
    result_response = client.get(result_url)
    assert result_response.status_code == 200
    assert "运行总览" in result_response.text
    assert "问题卡片摘要" in result_response.text
    assert "质量验证 / Validation" in result_response.text
    assert "自动化回归测试" in result_response.text
    assert "通过数以实际 pytest 运行结果为准" in result_response.text
    assert "106 tests passed" not in result_response.text
    run_id = result_url.rsplit("/", 1)[-1]
    run_dir = web_app.WEB_RUNS_DIR / run_id
    assert (run_dir / "triage_results.csv").exists()
    assert (run_dir / "weekly_summary.md").exists()
    assert (run_dir / "review_decisions.csv").exists()
    assert (run_dir / "report.html").exists()
    assert (run_dir / "outputs.zip").exists()


def test_web_run_ai_reviews_success(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = post_builtin_run(client, "ai_reviews")

    assert response.status_code == 303
    result_response = client.get(response.headers["location"])
    assert result_response.status_code == 200
    assert "人工复核队列" in result_response.text
    assert "下载区" in result_response.text


def test_web_run_ignores_llm_checkbox_when_web_llm_is_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class UnexpectedDeepSeekClient:
        def __init__(self):
            raise AssertionError("DeepSeek should not be called")

    monkeypatch.setattr(
        "feedback_triage_agent.tools.DeepSeekClient",
        UnexpectedDeepSeekClient,
    )

    response = client.post(
        "/run",
        data={
            "data_source": "sample",
            "use_llm": "on",
            "generate_html": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    qa_report = (web_app.WEB_RUNS_DIR / run_id / "qa_report.md").read_text(
        encoding="utf-8"
    )
    assert "是否使用 LLM: False" in qa_report


def test_web_ask_runs_same_agent_and_generates_html(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = client.post(
        "/ask",
        data={"task": "分析 data/sample_feedback.csv，只用规则，生成 HTML 报告"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    assert run_id.endswith("_ask")
    run_dir = web_app.WEB_RUNS_DIR / run_id
    assert (run_dir / "triage_results.csv").exists()
    assert (run_dir / "report.html").exists()
    assert (run_dir / "outputs.zip").exists()


def test_web_ask_uses_deepseek_to_parse_natural_language(
    tmp_path: Path, monkeypatch
) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FEEDBACK_TRIAGE_WEB_LLM_ENABLED", "true")

    class FakeDeepSeekClient:
        model = "deepseek-v4-pro"
        last_usage = {
            "prompt_tokens": 70,
            "completion_tokens": 20,
            "total_tokens": 90,
        }

        def parse_task(self, task: str, uploaded_filename: str = "") -> LLMTaskIntent:
            assert uploaded_filename == "feedback.csv"
            return LLMTaskIntent(
                use_llm_for_triage=False,
                generate_html_report=True,
                normalize_input=False,
            )

    monkeypatch.setattr(
        "feedback_triage_agent.task_parser.DeepSeekClient", FakeDeepSeekClient
    )
    csv_content = (
        b"id,source,app_name,review_text,rating\n"
        b'a001,test,ChatMate,"page is slow",2\n'
    )

    response = client.post(
        "/ask",
        data={"task": "照之前约定的交付形式处理一下"},
        files={"upload_file": ("feedback.csv", csv_content, "text/csv")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    run_dir = web_app.WEB_RUNS_DIR / run_id
    assert (run_dir / "report.html").exists()
    qa_report = (run_dir / "qa_report.md").read_text(encoding="utf-8")
    assert "解析来源: deepseek" in qa_report
    assert "解析模型: deepseek-v4-pro" in qa_report
    assert "解析总 tokens: 90" in qa_report


def test_web_ask_skips_deepseek_when_web_llm_is_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class UnexpectedDeepSeekClient:
        def __init__(self):
            raise AssertionError("DeepSeek should not be called")

    monkeypatch.setattr(
        "feedback_triage_agent.task_parser.DeepSeekClient",
        UnexpectedDeepSeekClient,
    )

    response = client.post(
        "/ask",
        data={"task": "分析 data/sample_feedback.csv，生成 HTML 报告"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    qa_report = (web_app.WEB_RUNS_DIR / run_id / "qa_report.md").read_text(
        encoding="utf-8"
    )
    assert "解析来源: rules" in qa_report


def test_web_ask_rule_parser_option_skips_deepseek(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    class UnexpectedDeepSeekClient:
        def __init__(self):
            raise AssertionError("DeepSeek should not be called")

    monkeypatch.setattr(
        "feedback_triage_agent.task_parser.DeepSeekClient",
        UnexpectedDeepSeekClient,
    )

    response = client.post(
        "/ask",
        data={
            "task": "分析 data/sample_feedback.csv，只用规则",
            "rule_parser": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    qa_report = (web_app.WEB_RUNS_DIR / run_id / "qa_report.md").read_text(
        encoding="utf-8"
    )
    assert "解析来源: rules" in qa_report


def test_web_ask_rejects_non_csv_before_deepseek_parse(
    tmp_path: Path, monkeypatch
) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    class UnexpectedDeepSeekClient:
        def __init__(self):
            raise AssertionError("DeepSeek should not be called")

    monkeypatch.setattr(
        "feedback_triage_agent.task_parser.DeepSeekClient",
        UnexpectedDeepSeekClient,
    )

    response = client.post(
        "/ask",
        data={"task": "处理这份文件"},
        files={"upload_file": ("notes.txt", b"not csv", "text/plain")},
    )

    assert response.status_code == 400
    assert "上传文件必须是 CSV 格式" in response.text


def test_web_ask_can_upload_csv_before_describing_task(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)
    csv_content = (
        b"id,source,app_name,review_text,rating\n"
        b'a001,test,ChatMate,"page is slow",2\n'
    )

    response = client.post(
        "/ask",
        data={"task": "只用规则，生成 HTML 报告"},
        files={"upload_file": ("feedback.csv", csv_content, "text/csv")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    run_dir = web_app.WEB_RUNS_DIR / run_id
    assert (run_dir / "input.csv").read_bytes() == csv_content
    assert (run_dir / "triage_results.csv").exists()
    assert (run_dir / "report.html").exists()


def test_web_ask_normalizes_uploaded_google_play_csv(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)
    csv_content = (
        b"reviewId,userName,content,score,thumbsUpCount\n"
        b'r001,Alice,"page is slow",2,3\n'
    )

    response = client.post(
        "/ask",
        data={"task": "转换为符合格式，只用规则，生成 HTML 报告"},
        files={
            "upload_file": (
                "chatgpt_reviews_latest_5000.csv",
                csv_content,
                "text/csv",
            )
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    run_dir = web_app.WEB_RUNS_DIR / run_id
    normalized = pd.read_csv(run_dir / "normalized_feedback.csv").fillna("")
    assert list(normalized.columns[:5]) == [
        "id",
        "source",
        "app_name",
        "review_text",
        "rating",
    ]
    assert normalized.loc[0, "source"] == "google_play"
    assert normalized.loc[0, "app_name"] == "ChatGPT"
    assert (run_dir / "triage_results.csv").exists()
    assert (run_dir / "outputs.zip").exists()


def test_web_ask_reports_unrecognized_normalization_fields(
    tmp_path: Path, monkeypatch
) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = client.post(
        "/ask",
        data={"task": "转换为符合格式，只用规则"},
        files={"upload_file": ("unknown.csv", b"reviewId,userName\nr001,Alice\n", "text/csv")},
    )

    assert response.status_code == 400
    assert "未识别到字段" in response.text
    assert "review_text" in response.text
    assert "rating" in response.text


def test_web_ask_without_csv_path_shows_clear_error(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = client.post("/ask", data={"task": "分析评论并生成报告"})

    assert response.status_code == 400
    assert "无法识别输入文件" in response.text
    assert "先上传 CSV 文件" in response.text
    assert not web_app.WEB_RUNS_DIR.exists()


def test_web_upload_non_csv_shows_clear_error(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = client.post(
        "/run",
        data={"data_source": "upload", "rule_only": "on"},
        files={"upload_file": ("notes.txt", b"not a csv", "text/plain")},
    )

    assert response.status_code == 400
    assert "上传文件必须是 CSV 格式" in response.text
    assert "Traceback" not in response.text
    assert list(web_app.WEB_RUNS_DIR.iterdir()) == []


def test_web_post_without_data_source_shows_clear_error(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = client.post("/run", data={"rule_only": "on"})

    assert response.status_code == 400
    assert "请选择一个数据源" in response.text
    assert "Traceback" not in response.text


def test_web_upload_csv_missing_review_text_shows_clear_error(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = client.post(
        "/run",
        data={"data_source": "upload", "rule_only": "on"},
        files={"upload_file": ("feedback.csv", b"id,source,rating\nx001,test,5\n", "text/csv")},
    )

    assert response.status_code == 400
    assert "CSV 缺少必填字段" in response.text
    assert "review_text" in response.text
    assert "Traceback" not in response.text
    assert list(web_app.WEB_RUNS_DIR.iterdir()) == []


def test_web_results_page_download_links_work(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)
    response = post_builtin_run(client, "sample")
    run_id = response.headers["location"].rsplit("/", 1)[-1]

    result_response = client.get(f"/runs/{run_id}")
    assert result_response.status_code == 200
    assert "issue_cards.md" in result_response.text
    assert "weekly_summary.md" in result_response.text

    download_response = client.get(f"/runs/{run_id}/download/triage_results.csv")
    assert download_response.status_code == 200
    assert "id,source,app_name,review_text" in download_response.text

    summary_response = client.get(f"/runs/{run_id}/download/weekly_summary.md")
    assert summary_response.status_code == 200
    assert "Weekly Product Summary" in summary_response.text


def test_web_can_apply_uploaded_review_decisions(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)
    response = post_builtin_run(client, "sample")
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    run_dir = web_app.WEB_RUNS_DIR / run_id
    decisions = pd.read_csv(run_dir / "review_decisions.csv").fillna("")
    decisions.loc[0, "decision"] = "confirm"
    content = decisions.to_csv(index=False).encode("utf-8")

    apply_response = client.post(
        f"/runs/{run_id}/reviews/apply",
        files={"decisions_file": ("review_decisions.csv", content, "text/csv")},
        follow_redirects=False,
    )

    assert apply_response.status_code == 303
    assert (run_dir / "triage_results_reviewed.csv").exists()
    assert (run_dir / "review_summary.md").exists()
    result_response = client.get(apply_response.headers["location"])
    assert "人工复核决策已应用" in result_response.text
