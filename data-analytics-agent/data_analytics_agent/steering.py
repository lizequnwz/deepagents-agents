"""Checkpointed correction delivery at supported model/tool boundaries."""

from typing import Annotated
from typing_extensions import NotRequired
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.messages import HumanMessage, ToolMessage
from langchain.tools import tool
from langgraph.types import interrupt


class PendingCorrections(ValueError):
    """The lifecycle must reconcile accepted input before finishing."""


class SteeringState(AgentState):
    correction_ids: NotRequired[Annotated[list[str], PrivateStateAttr]]


class SteeringMiddleware(AgentMiddleware):
    state_schema = SteeringState

    def __init__(self, runs, agent):
        self.runs, self.agent = runs, agent

    def before_model(self, state, runtime):
        run_id = state.get("run_id")
        if not run_id:
            return None
        seen = state.get("correction_ids", [])
        corrections = [
            c for c in self.runs.get(run_id).corrections if c.message_id not in seen
        ]
        if corrections:
            return {
                "messages": [
                    HumanMessage(
                        content="User correction (preserve prior evidence with its original scope): "
                        + c.message,
                        id="correction-" + c.message_id,
                    )
                    for c in corrections
                ],
                "correction_ids": [*seen, *(c.message_id for c in corrections)],
                "question": self.runs.get(run_id).question
                + "\n"
                + "\n".join(
                    "Correction: " + c.message
                    for c in self.runs.get(run_id).corrections
                ),
            }

    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)

    def after_model(self, state, runtime):
        if state.get("run_id"):
            self.runs.mark_corrections_applied(
                state["run_id"], state.get("correction_ids", []), self.agent
            )

    async def aafter_model(self, state, runtime):
        return self.after_model(state, runtime)

    def _stale(self, request):
        if request.tool_call["name"] == "request_clarification":
            return None
        state = request.state
        run_id = state.get("run_id")
        if run_id and any(
            c.message_id not in state.get("correction_ids", [])
            for c in self.runs.get(run_id).corrections
        ):
            return ToolMessage(
                content="A user correction arrived. This proposed step was not executed. Read the correction and revise your next action.",
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        return None

    def wrap_tool_call(self, request, handler):
        return self._stale(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        stale = self._stale(request)
        return stale if stale else await handler(request)


@tool
def request_clarification(question: str, choices: list[str] | None = None) -> str:
    """Ask a necessary business question and pause until the user answers.

    Use when ambiguity materially changes the analysis, including when a specialist
    returns needs_clarification. Optional choices are suggestions; free text is accepted.
    Do not publish empty findings or create a report for an unanswered question.
    """
    answer = interrupt(
        {"kind": "clarification", "question": question, "choices": choices or []}
    )
    return str(answer)
