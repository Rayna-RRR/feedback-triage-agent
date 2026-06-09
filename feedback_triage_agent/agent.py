from __future__ import annotations

from pathlib import Path
from typing import Callable, List

from feedback_triage_agent.models import AgentRunState, RunStepLog, ToolResult
from feedback_triage_agent.tools import (
    classify_feedback,
    detect_badcases,
    export_report,
    generate_issue_cards,
    load_feedback,
    qa_check,
    validate_schema,
)


AgentTool = Callable[[AgentRunState], ToolResult]


class FeedbackTriageAgent:
    """Fixed-plan runner that makes tool calls and records state."""

    def __init__(self, input_path: Path, output_dir: Path, llm_requested: bool = True):
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.llm_requested = llm_requested
        self.plan: List[AgentTool] = [
            load_feedback,
            validate_schema,
            classify_feedback,
            detect_badcases,
            generate_issue_cards,
            qa_check,
            export_report,
        ]

    def run(self) -> AgentRunState:
        state = AgentRunState(
            input_path=self.input_path,
            output_dir=self.output_dir,
            llm_requested=self.llm_requested,
        )

        for tool in self.plan:
            result = tool(state)
            state.run_log.append(RunStepLog.from_tool_result(result))
            if result.status == "error":
                break

        return state
