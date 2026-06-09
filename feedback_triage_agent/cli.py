from pathlib import Path

import pandas as pd
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from feedback_triage_agent import __version__
from feedback_triage_agent.agent import FeedbackTriageAgent


app = typer.Typer(help="Feedback Triage Agent v0.1", no_args_is_help=True)
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
        True,
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
def demo() -> None:
    """Run the demo with bundled sample feedback."""

    root = project_root()
    input_path = root / "data" / "sample_feedback.csv"
    output = root / "data" / "output"
    console.print(Panel("Running bundled sample demo", title="Feedback Triage Agent"))
    agent = FeedbackTriageAgent(input_path=input_path, output_dir=output, llm_requested=True)
    state = agent.run()
    render_run_summary(state)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
