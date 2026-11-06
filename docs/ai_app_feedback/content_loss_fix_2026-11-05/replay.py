"""Capture rules, real legacy CLI exports, synthetic imports/HTML and existing evals.

Run in this repository with --output /tmp/result.json. No real model or deployment.
"""
import argparse
import csv
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.pop('DEEPSEEK_API_KEY', None)
os.environ['FEEDBACK_TRIAGE_WEB_LLM_ENABLED'] = 'false'

from fastapi.testclient import TestClient
from feedback_triage_agent import observation, web_app
from feedback_triage_agent.agent import FeedbackTriageAgent
from feedback_triage_agent.harness import run_evaluation_harness
from feedback_triage_agent.models import FeedbackRecord
from feedback_triage_agent.rules import classify_feedback_record, detect_human_review_reasons


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file))


def classify(id, text, rating):
    result = classify_feedback_record(FeedbackRecord(id=id, source='SYNTHETIC',
        app_name='SYNTHETIC_ONLY', review_text=text, rating=rating))
    return {'category': result.issue_category, 'priority': result.priority,
        'members': result.matched_categories, 'keywords': result.matched_keywords,
        'confidence': result.confidence, 'review_reasons': detect_human_review_reasons(result)}


def input_csv(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=['id', 'source', 'app_name', 'review_text', 'rating'])
    writer.writeheader()
    for row in rows:
        writer.writerow({'id': row['id'], 'source': 'SYNTHETIC', 'app_name': 'SYNTHETIC_ONLY',
            'review_text': row['text'], 'rating': row['rating']})
    return stream.getvalue()


def capture(output):
    cases = json.loads((ROOT/'tests/fixtures/content_loss_cases.json').read_text())['cases']
    cases += json.loads((ROOT/'tests/fixtures/content_loss_regressions.json').read_text())['cases']
    records = {}
    with tempfile.TemporaryDirectory(prefix='content-loss-verification-') as tmp:
        work = Path(tmp)
        web_app.OBSERVATION_TASKS_DIR = work/'tasks'
        web_app.WEB_RUNS_DIR = work/'runs'
        with TestClient(web_app.app) as client:
            for case in cases:
                task = observation.create_task(web_app.OBSERVATION_TASKS_DIR,
                    name='【合成验证，不是真实发版】'+case['id'], product_name='SYNTHETIC_ONLY',
                    baseline_version='SYNTHETIC_BASE', current_version='SYNTHETIC_CURRENT',
                    baseline_window_start='2000-01-01T00:00', baseline_window_end='2000-01-03T00:00',
                    current_window_start='2000-01-04T00:00', current_window_end='2000-01-06T00:00')
                for role, rows in [('baseline',[{'id':'control','text':'很好用，体验顺畅。','rating':5}]),('current',[case])]:
                    result = client.post(f'/tasks/{task["task_id"]}/imports',
                        data={'window_kind':role,'observation_hours':'48','source':'SYNTHETIC'},
                        files={'file':('SYNTHETIC.csv',input_csv(rows).encode(),'text/csv')}, follow_redirects=False)
                    assert result.status_code == 303
                workspace = observation.build_workspace(task, selected_window=48)
                page = client.get(f'/tasks/{task["task_id"]}?window=48')
                assert page.status_code == 200
                assert page.context['workspace']['clusters'] == workspace['clusters']
                clusters = []
                for cluster in workspace['clusters']:
                    assert f'id="cluster-{cluster["cluster_id"]}"' in page.text
                    clusters.append({key: cluster[key] for key in ['issue_category','risk_level','review_status','review_required','evidence_gaps']})
                records[case['id']] = {'rule':classify(case['id'],case['text'],case['rating']),
                    'clusters':clusters,'http_status':page.status_code,'confirmed':workspace['metrics']['confirmed_count']}
        source = work/'contract.csv'; source.write_text(input_csv(cases))
        state = FeedbackTriageAgent(input_path=source, output_dir=work/'cli', llm_requested=False).run()
        assert state.llm_attempted_count == 0 and len(state.classified_feedback) == len(cases)
        cli = {r['id']:{key:r[key] for key in ['issue_category','priority','needs_human_review','human_review_reasons']}
            for r in read_csv(work/'cli/triage_results.csv')}
        public = {row['id']:classify(row['id'],row['review_text'],row['rating'])
            for row in read_csv(ROOT/'data/ai_app_reviews.csv')}
        harness = run_evaluation_harness(work/'harness', skip_pytest=True, root=ROOT)
        evaluation = {name:read_csv(work/'harness'/name/'evaluation_results.csv') for name in ['golden','adversarial']}
        snapshot = {'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'rules_sha256':hashlib.sha256((ROOT/'feedback_triage_agent/rules.py').read_bytes()).hexdigest(),
            'observation_sha256':hashlib.sha256((ROOT/'feedback_triage_agent/observation.py').read_bytes()).hexdigest(),
            'synthetic_windows':True,'llm_attempted_count':0,'contract_cases':records,'legacy_cli':cli,
            'public_30':public,'golden_metrics':harness.golden_metrics,'adversarial_metrics':harness.adversarial_metrics,
            'evaluations':evaluation,'pytest':'run separately; not run by this capture','harness_golden_passed':harness.golden_passed}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:snapshot[key] for key in ['commit','golden_metrics','adversarial_metrics','harness_golden_passed']},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    capture(parser.parse_args().output)
