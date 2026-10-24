"""Application-owned specialist receipts and successful tool completion."""

from typing import Annotated
from uuid import uuid4
from typing_extensions import NotRequired
from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.messages import HumanMessage


class AssignmentState(AgentState):
    assignment_id: NotRequired[Annotated[str, PrivateStateAttr]]


class AssignmentMiddleware(AgentMiddleware):
    state_schema = AssignmentState

    def __init__(self, runs, specialist):
        self.runs, self.specialist = runs, specialist

    def before_agent(self, state, runtime):
        assignment_id = state.get("assignment_id") or str(uuid4())
        brief = next(
            (m.text for m in state.get("messages", []) if isinstance(m, HumanMessage)),
            "",
        )
        update = {"assignment_id": assignment_id}
        self.runs.begin_assignment(
            state["run_id"], assignment_id, self.specialist, brief
        )
        return update

    async def abefore_agent(self, state, runtime):
        return self.before_agent(state, runtime)

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        record = self.runs.assignment(state["run_id"], state["assignment_id"])
        if record.completion is not None:
            if any(
                c.message_id not in record.correction_ids
                for c in self.runs.get(state["run_id"]).corrections
            ):
                self.runs.finish_assignment(
                    state["run_id"], state["assignment_id"], None
                )
            else:
                return {"structured_response": record.completion, "jump_to": "end"}

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)

    def after_agent(self, state, runtime):
        record = self.runs.assignment(state["run_id"], state["assignment_id"])
        if record.completion is not None:
            return {"structured_response": record.completion}
        # SQL's model writes only interpretation. Code attaches every saved result.
        response = state.get("structured_response")
        narrative = (
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else dict(response or {})
        )
        if not narrative:
            narrative = {
                "answer": "Assignment ended before completing its findings.",
                "outcome": "partial",
            }
        receipt = {
            **narrative,
            "datasets": [d.model_dump(mode="json") for d in record.datasets.values()],
        }
        self.runs.finish_assignment(
            state["run_id"],
            state["assignment_id"],
            receipt,
            state.get("correction_ids", []),
        )
        return {"structured_response": receipt}

    async def aafter_agent(self, state, runtime):
        return self.after_agent(state, runtime)


def record_dataset(runs, runtime, payload, label):
    """Record exact tool-produced identity, scoped to the executing assignment."""
    assignment_id = runtime.state.get("assignment_id")
    if assignment_id:
        runs.record_assignment_dataset(
            runtime.state["run_id"],
            assignment_id,
            {
                "result_id": payload["result_id"],
                "label": label,
                "columns": payload["columns"],
                "row_count": payload["row_count"],
                "truncated": payload["truncated"],
            },
        )


class ReportCompletionMiddleware(AgentMiddleware):
    """End the coordinator after an accepted report without re-authoring findings."""

    def __init__(self, runs, dashboards=None):
        self.runs, self.dashboards = runs, dashboards

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        run_id = state["run_id"]
        if self.runs.report_reference(run_id) and self.runs.get(run_id).findings:
            if self.runs.cancel_event(run_id).is_set():
                raise InterruptedError("Run stopped before completion.")
            requested = self.runs.storage.get("dashboard_requests", run_id, dict)
            action = self.dashboards.action_for_run(run_id) if self.dashboards else None
            if (requested or action) and (
                not self.dashboards or not self.dashboards.candidate_for_run(run_id)
            ):
                return {
                    "messages": [
                        HumanMessage(
                            content="The required saved dashboard is missing. Load dashboard-design and call create_dashboard using the already published evidence. Preserve the existing report; do not rerun analysis."
                        )
                    ]
                }
            return {"jump_to": "end"}

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)


def assignment_call_id(runtime):
    """Journal identity also separates sequential SQL assignments with repeated call IDs."""
    return f"{runtime.state.get('assignment_id', 'direct')}:{runtime.tool_call_id}"
