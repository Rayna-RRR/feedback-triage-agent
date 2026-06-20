from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from feedback_triage_agent.evaluation import (
    DEFAULT_EVALUATION_GATES,
    EvaluationSummary,
    evaluate_rules,
)


@dataclass(frozen=True)
class HarnessResult:
    pytest_passed: bool
    pytest_skipped: bool
    golden_passed: bool
    adversarial_completed: bool
    harness_passed: bool
    golden_metrics: Dict[str, Union[float, int]]
    adversarial_metrics: Dict[str, Union[float, int]]
    output_paths: Dict[str, str]
    pytest_returncode: Optional[int] = None
    golden_error: str = ""
    adversarial_error: str = ""

    def to_json_dict(self) -> Dict[str, object]:
        return {
            "pytest_passed": self.pytest_passed,
            "pytest_skipped": self.pytest_skipped,
            "pytest_returncode": self.pytest_returncode,
            "golden_passed": self.golden_passed,
            "adversarial_completed": self.adversarial_completed,
            "harness_passed": self.harness_passed,
            "golden_metrics": self.golden_metrics,
            "adversarial_metrics": self.adversarial_metrics,
            "output_paths": self.output_paths,
            "golden_error": self.golden_error,
            "adversarial_error": self.adversarial_error,
        }


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def summary_metrics(summary: EvaluationSummary) -> Dict[str, Union[float, int]]:
    return {
        "samples": summary.total_samples,
        "category_accuracy": summary.category_accuracy,
        "priority_accuracy": summary.priority_accuracy,
        "human_review_accuracy": summary.human_review_accuracy,
        "p0_precision": summary.p0_precision,
        "p0_recall": summary.p0_recall,
    }


def metrics_pass_gates(metrics: Dict[str, Union[float, int]]) -> bool:
    return all(
        float(metrics.get(name, 0)) >= threshold
        for name, threshold in DEFAULT_EVALUATION_GATES.items()
    )


def status_label(passed: bool, skipped: bool = False) -> str:
    if skipped:
        return "skipped"
    return "passed" if passed else "failed"


def render_metrics(metrics: Dict[str, Union[float, int]], report_path: str) -> List[str]:
    if not metrics:
        return [
            "- samples: n/a",
            "- category_accuracy: n/a",
            "- priority_accuracy: n/a",
            "- human_review_accuracy: n/a",
            "- p0_precision: n/a",
            "- p0_recall: n/a",
            f"- report path: {report_path or 'n/a'}",
        ]
    return [
        f"- samples: {metrics['samples']}",
        f"- category_accuracy: {float(metrics['category_accuracy']):.2%}",
        f"- priority_accuracy: {float(metrics['priority_accuracy']):.2%}",
        f"- human_review_accuracy: {float(metrics['human_review_accuracy']):.2%}",
        f"- p0_precision: {float(metrics['p0_precision']):.2%}",
        f"- p0_recall: {float(metrics['p0_recall']):.2%}",
        f"- report path: {report_path}",
    ]


def render_harness_report(result: HarnessResult) -> str:
    lines = [
        "# Evaluation Harness Report",
        "",
        "## 总览",
        "",
        f"- Pytest: {status_label(result.pytest_passed, result.pytest_skipped)}",
        f"- Golden set: {'passed' if result.golden_passed else 'failed'}",
        (
            "- Adversarial set: "
            + ("completed" if result.adversarial_completed else "failed")
        ),
        f"- Harness result: {'passed' if result.harness_passed else 'failed'}",
        "",
        "## Golden Set Metrics",
        "",
    ]
    lines.extend(render_metrics(result.golden_metrics, result.output_paths.get("golden_report", "")))
    if result.golden_error:
        lines.append(f"- error: {result.golden_error}")
    lines.extend(["", "## Adversarial Set Metrics", ""])
    lines.extend(
        render_metrics(
            result.adversarial_metrics,
            result.output_paths.get("adversarial_report", ""),
        )
    )
    lines.append("- 说明：adversarial set 是探索性评测集，不参与默认质量门槛")
    if result.adversarial_error:
        lines.append(f"- error: {result.adversarial_error}")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- pytest 覆盖 output contract 和基础回归测试",
            "- golden set 用于稳定回归",
            "- adversarial set 用于暴露规则边界和失败模式",
            "- scenario breakdown 可在 adversarial evaluation report 中查看",
            "",
        ]
    )
    return "\n".join(lines)


def run_pytest(root: Path) -> Tuple[bool, int]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return completed.returncode == 0, completed.returncode


def run_evaluation_harness(
    output_dir: Path,
    *,
    skip_pytest: bool = False,
    root: Optional[Path] = None,
) -> HarnessResult:
    root = Path(root) if root else project_root()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pytest_returncode: Optional[int] = None
    if skip_pytest:
        pytest_passed = True
        pytest_skipped = True
    else:
        pytest_passed, pytest_returncode = run_pytest(root)
        pytest_skipped = False

    golden_output = output_dir / "golden"
    adversarial_output = output_dir / "adversarial"
    golden_metrics: Dict[str, Union[float, int]] = {}
    adversarial_metrics: Dict[str, Union[float, int]] = {}
    golden_error = ""
    adversarial_error = ""

    try:
        golden_summary = evaluate_rules(root / "data" / "evaluation_feedback.csv", golden_output)
        golden_metrics = summary_metrics(golden_summary)
        golden_passed = metrics_pass_gates(golden_metrics)
    except ValueError as exc:
        golden_passed = False
        golden_error = str(exc)

    try:
        adversarial_summary = evaluate_rules(
            root / "data" / "adversarial_feedback.csv",
            adversarial_output,
        )
        adversarial_metrics = summary_metrics(adversarial_summary)
        adversarial_completed = True
    except ValueError as exc:
        adversarial_completed = False
        adversarial_error = str(exc)

    harness_passed = pytest_passed and golden_passed and adversarial_completed
    report_path = output_dir / "harness_report.md"
    summary_path = output_dir / "harness_summary.json"
    output_paths = {
        "harness_report": str(report_path),
        "harness_summary": str(summary_path),
        "golden_report": str(golden_output / "evaluation_report.md"),
        "golden_results": str(golden_output / "evaluation_results.csv"),
        "adversarial_report": str(adversarial_output / "evaluation_report.md"),
        "adversarial_results": str(adversarial_output / "evaluation_results.csv"),
    }
    result = HarnessResult(
        pytest_passed=pytest_passed,
        pytest_skipped=pytest_skipped,
        pytest_returncode=pytest_returncode,
        golden_passed=golden_passed,
        adversarial_completed=adversarial_completed,
        harness_passed=harness_passed,
        golden_metrics=golden_metrics,
        adversarial_metrics=adversarial_metrics,
        output_paths=output_paths,
        golden_error=golden_error,
        adversarial_error=adversarial_error,
    )

    report_path.write_text(render_harness_report(result), encoding="utf-8")
    summary_path.write_text(
        json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
