"""Direct artifact references and published analytical findings."""

from langchain.tools import tool, ToolRuntime
from langchain_core.tools import ToolException
from data_analytics_agent.steering import PendingCorrections
from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.schemas import FinalAnswer, ResultReference
from data_analytics_agent.evidence import EvidenceResolver
from data_analytics_agent.datasets import StoreNotFound


def resolve_answer(response, *, thread_id, source_id, results, analyses, runs):
    evidence = EvidenceResolver(
        thread_id=thread_id,
        source_id=source_id,
        results=results,
        analyses=analyses,
        runs=runs,
    )
    for key in response.supporting_result_ids:
        evidence.result(key)
    if response.primary_result_id:
        evidence.result(response.primary_result_id)
    analytical = [evidence.analysis(key) for key in response.analysis_ids]
    charts = [evidence.chart(key) for key in response.chart_ids]
    selected = evidence.results
    primary = response.primary_result_id or next(iter(selected), None)
    ordered = ([primary] if primary else []) + [
        key for key in selected if key != primary
    ]
    return FinalAnswer(
        answer=response.answer,
        primary_result_id=primary,
        results=[
            ResultReference(
                result_id=key,
                executed_sql=selected[key].executed_sql,
                originating_question=selected[key].originating_question,
                short_label=selected[key].short_label,
            )
            for key in ordered
        ],
        analyses=analytical,
        charts=charts,
        assumptions=response.assumptions,
        interpretation=response.interpretation,
        partial=response.partial,
        unresolved_questions=response.unresolved_questions,
    )


def create_presentation_tools(results, analyses, runs, conversations, *, source_id):
    from data_analytics_agent.schemas import CoordinatorResponse

    @tool
    def publish_findings(findings: CoordinatorResponse, runtime: ToolRuntime) -> dict:
        """Publish final supported findings before building the required report.

        Include ordered chart_ids and analysis_ids, all material dataset IDs,
        and explicit partial/unresolved_questions if analysis is incomplete.
        """
        context = _runtime_context(runtime)
        try:
            answer = resolve_answer(
                findings,
                thread_id=context.thread_id,
                source_id=source_id,
                results=results,
                analyses=analyses,
                runs=runs,
            )
        except (StoreNotFound, ValueError) as exc:
            raise ToolException(
                "Findings were not published: a referenced artifact is unknown, "
                f"invalid, or outside this conversation ({exc}). Use list_conversation_results "
                "or list_conversation_analyses or list_conversation_charts. "
                "Correct the references and retry; reuse saved evidence "
                "without repeating successful analysis."
            ) from exc
        if (
            runs.diagnostics(context.run_id).active_ms
            >= getattr(runs, "analysis_budget_seconds", 900) * 1000
        ):
            answer = answer.model_copy(
                update={
                    "partial": True,
                    "unresolved_questions": answer.unresolved_questions
                    or [
                        "The analysis budget ended before the investigation was finished."
                    ],
                }
            )
        try:
            runs.publish(context.run_id, answer)
        except PendingCorrections as exc:
            raise ToolException(str(exc)) from exc
        return {
            "ok": True,
            "message": "Findings are visible. Create their HTML report now.",
        }

    @tool
    def save_investigation(
        objective: str,
        completed_steps: list[str],
        findings: list[str],
        unresolved_questions: list[str],
        runtime: ToolRuntime,
        assumptions: list[str] | None = None,
    ) -> dict:
        """Save a compact investigation record for continuation and future turns."""
        context = _runtime_context(runtime)
        conversations.save_investigation(
            context.thread_id,
            dict(
                objective=objective,
                completed_steps=completed_steps,
                findings=findings,
                unresolved_questions=unresolved_questions,
                assumptions=assumptions or [],
            ),
        )
        return {"ok": True}

    publish_findings.handle_tool_error = True
    return [publish_findings, save_investigation]


def create_list_conversation_charts_tool(runs, *, source_id):
    @tool
    def list_conversation_charts(
        runtime: ToolRuntime, offset: int = 0, limit: int = 20
    ) -> dict:
        """Discover exact saved chart references and versions for this conversation."""
        context = _runtime_context(runtime)
        charts = [
            {
                key: entry["spec"].get(key)
                for key in (
                    "chart_id",
                    "title",
                    "chart_type",
                    "result_id",
                    "source_result_id",
                    "version",
                    "previous_chart_id",
                )
            }
            for entry in runs.storage.load("charts", dict).values()
            if entry["thread_id"] == context.thread_id
            and entry["source_id"] == source_id
        ]
        offset, limit = max(0, offset), max(1, min(limit, 50))
        return {"total": len(charts), "charts": charts[offset : offset + limit]}

    return list_conversation_charts
