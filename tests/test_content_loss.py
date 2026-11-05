"""Approved event contract, checked independently at rule, CLI and import/HTML layers."""
import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from feedback_triage_agent import observation, web_app
from feedback_triage_agent.cli import app
from feedback_triage_agent.models import FeedbackRecord
from feedback_triage_agent.rules import classify_feedback_record, detect_human_review_reasons

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'tests/fixtures/content_loss_cases.json').read_text())["cases"]
CASES += json.loads((ROOT / 'tests/fixtures/content_loss_regressions.json').read_text())["cases"]
LOSS_CATEGORY = "账号、隐私与数据问题"
LOSS_REASON = "疑似内容丢失、可恢复性待核查"


def check_case(case, category, priority, reasons, members=None):
    if case["priority"] == "not_P0":
        assert priority != "P0"
    else:
        assert priority == case["priority"]
    if case.get("category"):
        assert category == case["category"]
    if case.get("review"):
        assert reasons
    if case.get("review_reason"):
        assert case["review_reason"] in reasons
    if case.get("no_active_data_reason"):
        assert LOSS_REASON not in reasons
    if members is not None:
        assert set(case.get("members", [])) <= set(members)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c['id'])
def test_content_loss_rule_contract(case):
    result = classify_feedback_record(FeedbackRecord(
        id=case['id'], source='SYNTHETIC', app_name='SYNTHETIC',
        review_text=case['text'], rating=case['rating'],
    ))
    check_case(case, result.issue_category, result.priority,
               detect_human_review_reasons(result), result.matched_categories)


def csv_input(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=['id', 'source', 'app_name', 'review_text', 'rating'])
    writer.writeheader()
    for case in rows:
        writer.writerow({'id': case['id'], 'source': 'SYNTHETIC_CONTRACT',
            'app_name': 'SYNTHETIC_NO_REAL_VERSION', 'review_text': case['text'], 'rating': case['rating']})
    return buffer.getvalue()


def test_content_loss_contract_through_legacy_cli(tmp_path, monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    source = tmp_path / 'SYNTHETIC_feedback.csv'
    source.write_text(csv_input(CASES))
    output = tmp_path / 'cli'
    response = CliRunner().invoke(app, ['run', '--input', str(source), '--output', str(output), '--no-llm'])
    assert response.exit_code == 0, response.output
    with (output / 'triage_results.csv').open() as file:
        actual = {row['id']: row for row in csv.DictReader(file)}
    for case in CASES:
        row = actual[case['id']]
        check_case(case, row['issue_category'], row['priority'], row['human_review_reasons'])
        if case.get('review'):
            assert row['needs_human_review'] == 'True'


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_content_loss_contract_through_import_workspace_and_html(case, tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, 'OBSERVATION_TASKS_DIR', tmp_path / 'tasks')
    monkeypatch.setattr(web_app, 'WEB_RUNS_DIR', tmp_path / 'runs')
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    with TestClient(web_app.app) as client:
        response = client.post('/tasks', data={
            'name': '【合成验收，非真实发版】内容事件', 'product_name': 'SYNTHETIC_NO_REAL_VERSION',
            'baseline_version': 'SYNTHETIC_BASE', 'current_version': 'SYNTHETIC_CURRENT',
            'baseline_window_start': '2000-01-01T00:00', 'baseline_window_end': '2000-01-03T00:00',
            'current_window_start': '2000-01-04T00:00', 'current_window_end': '2000-01-06T00:00',
            'comparison_basis': 'equivalent_window', 'change_summary': 'Synthetic transport only',
        }, follow_redirects=False)
        assert response.status_code == 303
        task_id = response.headers['location'].split('?')[0].rsplit('/', 1)[-1]
        for role, rows in [('baseline', [{'id': 'control', 'text': '很好用，体验顺畅。', 'rating': 5}]), ('current', [case])]:
            response = client.post(f'/tasks/{task_id}/imports',
                data={'window_kind': role, 'observation_hours': '48', 'source': 'SYNTHETIC_CONTRACT', 'import_mode': 'cumulative'},
                files={'file': ('SYNTHETIC.csv', csv_input(rows).encode(), 'text/csv')}, follow_redirects=False)
            assert response.status_code == 303, response.text
        workspace = observation.build_workspace(web_app.OBSERVATION_TASKS_DIR / task_id, selected_window=48)
        clusters = workspace['clusters']
        categories = {c['issue_category'] for c in clusters}
        assert set(case.get('members', [])) <= categories
        if case.get('no_data_cluster'):
            assert LOSS_CATEGORY not in categories
        if case['priority'] == 'not_P0':
            assert all(c['risk_level'] != 'P0' for c in clusters)
        if case['priority'] == 'P0':
            assert any(c['risk_level'] == 'P0' and c['review_status'] == '待复核' for c in clusters)
        if case.get('review_reason'):
            assert any(case['review_reason'] in m['review_reasons'] for c in clusters for m in c['current_evidence'])
        assert workspace['metrics']['confirmed_count'] == 0
        assert not workspace['owner_summary']
        page = client.get(f'/tasks/{task_id}?window=48')
        assert page.status_code == 200
        assert page.context['workspace']['clusters'] == clusters
        for cluster in clusters:
            assert f'id="cluster-{cluster["cluster_id"]}"' in page.text
        if case['priority'] == 'P0':
            assert '>P0</span>' in page.text and '待复核' in page.text
