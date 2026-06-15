from pathlib import Path

import pandas as pd
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
    assert "自然语言 Ask 入口" in response.text
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

    download_response = client.get(f"/runs/{run_id}/download/triage_results.csv")
    assert download_response.status_code == 200
    assert "id,source,app_name,review_text" in download_response.text


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
