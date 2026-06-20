from pathlib import Path
from typing import Optional

import pandas as pd
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from feedback_triage_agent import __version__
from feedback_triage_agent.agent import FeedbackTriageAgent
from feedback_triage_agent.evaluation import DEFAULT_EVALUATION_GATES, evaluate_rules
from feedback_triage_agent.harness import run_evaluation_harness
from feedback_triage_agent.html_report import ReportInputError, generate_html_report
from feedback_triage_agent.review import apply_review_decisions
from feedback_triage_agent.task_parser import (
    infer_input_path,
    parse_ask_task,
)


app = typer.Typer(help=f"Feedback Triage Agent v{__version__}", no_args_is_help=True)
console = Console()


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def render_run_summary(state) -> None:
    table = Table(title="Feedback Triage Agent Run Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Version", __version__)
    table.add_row("Total samples", str(state.qa_summary.get("total_samples", len(state.raw_records))))
    table.add_row("Valid samples", str(state.qa_summary.get("valid_samples", len(state.records))))
    table.add_row("Issue cards", str(len(state.issue_cards)))
    table.add_row("Human review queue", str(len(state.human_review_queue)))
    table.add_row("Ask parser", str(state.ask_parser_source))
    table.add_row("LLM used", str(state.llm_used))
    table.add_row("LLM fallback", str(state.llm_fallback_used))
    table.add_row("Output dir", str(state.output_dir))
    console.print(table)

    if state.output_paths:
        output_table = Table(title="Generated Files")
        output_table.add_column("Name", style="cyan")
        output_table.add_column("Path", style="white")
        for name, path in state.output_paths.items():
            output_table.add_row(name, str(path))
        console.print(output_table)


@app.command()
def run(
    input_path: Path = typer.Option(
        Path("data/sample_feedback.csv"),
        "--input",
        "-i",
        help="Path to feedback CSV.",
    ),
    output: Path = typer.Option(
        Path("data/output"),
        "--output",
        "-o",
        help="Directory for exported reports.",
    ),
    llm: bool = typer.Option(
        False,
        "--llm/--no-llm",
        help="Use DeepSeek when DEEPSEEK_API_KEY is available.",
    ),
) -> None:
    """Run the fixed-plan triage agent."""

    agent = FeedbackTriageAgent(input_path=input_path, output_dir=output, llm_requested=llm)
    state = agent.run()
    render_run_summary(state)

    if state.run_log and state.run_log[-1].status == "error":
        raise typer.Exit(code=1)


@app.command()
def ask(
    task: str = typer.Argument(..., help="Natural language triage task."),
    rule_parser: bool = typer.Option(
        False,
        "--rule-parser",
        help="Parse the Ask task locally without calling DeepSeek.",
    ),
) -> None:
    """Run triage from a small natural-language task description."""

    parsed = parse_ask_task(task, use_deepseek=not rule_parser)
    input_path = parsed.input_path
    if input_path is None:
        console.print(
            "[red]无法识别输入文件，请在任务中写明 CSV 路径，例如 "
            "data/ai_app_reviews.csv。[/red]"
        )
        raise typer.Exit(code=1)

    if not input_path.exists():
        console.print(f"[red]识别到输入文件 {input_path}，但文件不存在。请检查路径后重试。[/red]")
        raise typer.Exit(code=1)

    output = parsed.output_dir

    console.print(
        Panel(
            (
                f"input={input_path}\n"
                f"output={output}\n"
                f"task_parser={parsed.parser_source}\n"
                f"task_parser_model={parsed.parser_model or 'local'}\n"
                f"task_parser_fallback={parsed.parser_fallback_reason or 'none'}\n"
                f"task_parser_tokens={parsed.parser_total_tokens}\n"
                f"llm_requested={parsed.llm_requested}\n"
                f"html_report={parsed.html_requested}\n"
                f"normalize_input={parsed.normalize_input}"
            ),
            title="Parsed Ask Task",
        )
    )

    agent = FeedbackTriageAgent(
        input_path=input_path,
        output_dir=output,
        llm_requested=parsed.llm_requested,
        normalize_input=parsed.normalize_input,
        input_name=input_path.name,
        ask_parser_source=parsed.parser_source,
        ask_parser_model=parsed.parser_model,
        ask_parser_fallback_reason=parsed.parser_fallback_reason,
        ask_parser_prompt_tokens=parsed.parser_prompt_tokens,
        ask_parser_completion_tokens=parsed.parser_completion_tokens,
        ask_parser_total_tokens=parsed.parser_total_tokens,
    )
    state = agent.run()
    render_run_summary(state)

    if state.run_log and state.run_log[-1].status == "error":
        raise typer.Exit(code=1)

    if parsed.html_requested:
        try:
            report_path = generate_html_report(output)
        except ReportInputError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)
        console.print(f"[green]HTML report generated:[/green] {report_path}")


@app.command()
def inspect(
    output: Path = typer.Option(
        Path("data/output"),
        "--output",
        "-o",
        help="Directory containing triage_results.csv.",
    ),
) -> None:
    """Inspect the latest exported triage results."""

    results_path = output / "triage_results.csv"
    if not results_path.exists():
        console.print(f"[red]No triage_results.csv found at {results_path}[/red]")
        raise typer.Exit(code=1)

    dataframe = pd.read_csv(results_path).fillna("")
    table = Table(title=f"Triage Results: {results_path}")
    for column in [
        "id",
        "issue_category",
        "priority",
        "confidence",
        "classification_source",
        "needs_human_review",
        "human_review_reasons",
    ]:
        table.add_column(column)

    for _, row in dataframe.head(20).iterrows():
        table.add_row(
            str(row.get("id", "")),
            str(row.get("issue_category", "")),
            str(row.get("priority", "")),
            str(row.get("confidence", "")),
            str(row.get("classification_source", "")),
            str(row.get("needs_human_review", "")),
            str(row.get("human_review_reasons", "")),
        )
    console.print(table)


@app.command()
def evaluate(
    input_path: Path = typer.Option(
        Path("data/evaluation_feedback.csv"),
        "--input",
        "-i",
        help="Labeled evaluation CSV.",
    ),
    output: Path = typer.Option(
        Path("data/evaluation_output"),
        "--output",
        "-o",
        help="Directory for evaluation artifacts.",
    ),
    min_category_accuracy: float = typer.Option(
        DEFAULT_EVALUATION_GATES["category_accuracy"],
        min=0,
        max=1,
    ),
    min_priority_accuracy: float = typer.Option(
        DEFAULT_EVALUATION_GATES["priority_accuracy"],
        min=0,
        max=1,
    ),
    min_human_review_accuracy: float = typer.Option(
        DEFAULT_EVALUATION_GATES["human_review_accuracy"],
        min=0,
        max=1,
    ),
    min_p0_precision: float = typer.Option(
        DEFAULT_EVALUATION_GATES["p0_precision"],
        min=0,
        max=1,
    ),
    min_p0_recall: float = typer.Option(
        DEFAULT_EVALUATION_GATES["p0_recall"],
        min=0,
        max=1,
    ),
) -> None:
    """Evaluate rules.py against a labeled local dataset."""

    try:
        summary = evaluate_rules(input_path, output)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    table = Table(title="Rule Evaluation Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("Samples", str(summary.total_samples))
    table.add_row("Category accuracy", f"{summary.category_accuracy:.2%}")
    table.add_row("Priority accuracy", f"{summary.priority_accuracy:.2%}")
    table.add_row("Human review accuracy", f"{summary.human_review_accuracy:.2%}")
    table.add_row("P0 precision", f"{summary.p0_precision:.2%}")
    table.add_row("P0 recall", f"{summary.p0_recall:.2%}")
    console.print(table)

    failed_gates = []
    if summary.category_accuracy < min_category_accuracy:
        failed_gates.append("category_accuracy")
    if summary.priority_accuracy < min_priority_accuracy:
        failed_gates.append("priority_accuracy")
    if summary.human_review_accuracy < min_human_review_accuracy:
        failed_gates.append("human_review_accuracy")
    if summary.p0_precision < min_p0_precision:
        failed_gates.append("p0_precision")
    if summary.p0_recall < min_p0_recall:
        failed_gates.append("p0_recall")
    if failed_gates:
        console.print("[red]Quality gates failed:[/red] " + ", ".join(failed_gates))
        raise typer.Exit(code=1)


@app.command()
def harness(
    output: Path = typer.Option(
        Path("data/harness_output"),
        "--output",
        "-o",
        help="Directory for evaluation harness artifacts.",
    ),
    skip_pytest: bool = typer.Option(
        False,
        "--skip-pytest",
        help="Skip nested pytest run. Useful when testing the harness command itself.",
    ),
) -> None:
    """Run pytest, golden evaluation, and adversarial evaluation together."""

    result = run_evaluation_harness(output, skip_pytest=skip_pytest)
    table = Table(title="Evaluation Harness Summary")
    table.add_column("Stage", style="cyan")
    table.add_column("Status")
    table.add_row(
        "Pytest",
        "skipped" if result.pytest_skipped else ("passed" if result.pytest_passed else "failed"),
    )
    table.add_row("Golden set", "passed" if result.golden_passed else "failed")
    table.add_row(
        "Adversarial set",
        "completed" if result.adversarial_completed else "failed",
    )
    table.add_row("Harness result", "passed" if result.harness_passed else "failed")
    console.print(table)
    console.print(f"[green]harness_report:[/green] {result.output_paths['harness_report']}")
    console.print(f"[green]harness_summary:[/green] {result.output_paths['harness_summary']}")

    if not result.harness_passed:
        raise typer.Exit(code=1)


@app.command()
def report(
    output: Path = typer.Option(
        Path("data/output"),
        "--output",
        "-o",
        help="Directory containing exported triage files.",
    ),
) -> None:
    """Generate a static HTML report from an existing output directory."""

    try:
        report_path = generate_html_report(output)
    except ReportInputError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]HTML report generated:[/green] {report_path}")


@app.command("review-apply")
def review_apply(
    output: Path = typer.Option(
        Path("data/output"),
        "--output",
        "-o",
        help="Directory containing triage_results.csv and review_decisions.csv.",
    ),
    decisions: Optional[Path] = typer.Option(
        None,
        "--decisions",
        "-d",
        help="Edited review decisions CSV. Defaults to <output>/review_decisions.csv.",
    ),
) -> None:
    """Apply local human-review decisions without overwriting raw triage results."""

    decisions_path = decisions or output / "review_decisions.csv"
    try:
        summary = apply_review_decisions(
            output / "triage_results.csv",
            decisions_path,
            output,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    table = Table(title="Human Review Apply Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("Decision rows", str(summary.total_decisions))
    table.add_row("Reviewed", str(summary.reviewed_count))
    table.add_row("Open", str(summary.open_count))
    table.add_row("Pending", str(summary.pending_count))
    console.print(table)
    for name, path in summary.output_paths.items():
        console.print(f"[green]{name}:[/green] {path}")


@app.command()
def demo() -> None:
    """Run the demo with bundled sample feedback."""

    root = project_root()
    input_path = root / "data" / "sample_feedback.csv"
    output = root / "data" / "output"
    console.print(Panel("Running bundled sample demo", title="Feedback Triage Agent"))
    agent = FeedbackTriageAgent(input_path=input_path, output_dir=output, llm_requested=False)
    state = agent.run()
    render_run_summary(state)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
