from pathlib import Path

from fastapi.testclient import TestClient

from feedback_triage_agent import web_app


def client_with_tmp_runs(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(web_app, "WEB_RUNS_DIR", tmp_path / "web_runs")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
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
    assert "Feedback Triage Agent" in response.text
    assert "开始分诊" in response.text


def test_web_run_sample_feedback_success(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)

    response = post_builtin_run(client, "sample")

    assert response.status_code == 303
    result_url = response.headers["location"]
    result_response = client.get(result_url)
    assert result_response.status_code == 200
    assert "运行总览" in result_response.text
    assert "问题卡片摘要" in result_response.text
    run_id = result_url.rsplit("/", 1)[-1]
    run_dir = web_app.WEB_RUNS_DIR / run_id
    assert (run_dir / "triage_results.csv").exists()
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
    assert "CSV 缺少 review_text 字段" in response.text
    assert "Traceback" not in response.text


def test_web_results_page_download_links_work(tmp_path: Path, monkeypatch) -> None:
    client = client_with_tmp_runs(tmp_path, monkeypatch)
    response = post_builtin_run(client, "sample")
    run_id = response.headers["location"].rsplit("/", 1)[-1]

    result_response = client.get(f"/runs/{run_id}")
    assert result_response.status_code == 200
    assert "issue_cards.md" in result_response.text

    download_response = client.get(f"/runs/{run_id}/download/triage_results.csv")
    assert download_response.status_code == 200
    assert "id,source,app_name,review_text" in download_response.text
