"""Direct artifact references and published analytical findings."""

from langchain.tools import tool, ToolRuntime
from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.schemas import FinalAnswer, ResultReference
from data_analytics_agent.visualization.schemas import ChartSpec


def resolve_answer(response, *, thread_id, source_id, results, analyses, runs):
    selected = {}

    def include(key):
        if key in selected:
            return
        result = results.get(key, thread_id, source_id=source_id)
        selected[key] = result
        for parent in result.parent_result_ids:
            include(parent)

    for key in response.supporting_result_ids:
        include(key)
    if response.primary_result_id:
        include(response.primary_result_id)
    analytical = [
        analyses.get(key, thread_id, source_id=source_id).analysis
        for key in response.analysis_ids
    ]
    for analysis in analytical:
        for key in analysis.input_result_ids:
            include(key)
        for execution in analysis.executions:
            for key in [
                *execution.inputs.values(),
                *execution.output_datasets.values(),
            ]:
                include(key)
    charts = []
    available = runs.storage.load("charts", dict)
    for key in response.chart_ids:
        item = available.get(key)
        if not item or item["thread_id"] != thread_id or item["source_id"] != source_id:
            raise ValueError("Chart is outside this conversation.")
        chart = ChartSpec.model_validate(item["spec"])
        charts.append(chart)
        include(chart.result_id)
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
        answer = resolve_answer(
            findings,
            thread_id=context.thread_id,
            source_id=source_id,
            results=results,
            analyses=analyses,
            runs=runs,
        )
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
        runs.publish(context.run_id, answer)
        return {
            "ok": True,
            "message": "Findings are visible. Create their HTML report now.",
        }

    @tool
    def save_investigation(
        objective: str,
        completed_steps: list[str],
        findings: list[str],
        artifact_ids: list[str],
        unresolved_questions: list[str],
        runtime: ToolRuntime,
        assumptions: list[str] | None = None,
    ) -> dict:
        """Save a compact investigation record for continuation and future turns."""
        context = _runtime_context(runtime)
        known = {
            item.result_id
            for item in results.list_for_conversation(
                context.thread_id, source_id=source_id
            )
        }
        known.update(
            item.analysis_id
            for item in analyses.list_for_conversation(
                context.thread_id, source_id=source_id
            )
        )
        known.update(
            key
            for key, item in runs.storage.load("charts", dict).items()
            if item["thread_id"] == context.thread_id and item["source_id"] == source_id
        )
        if not set(artifact_ids) <= known:
            raise ValueError(
                "Investigation references unknown or out-of-scope artifacts."
            )
        conversations.save_investigation(
            context.thread_id,
            dict(
                objective=objective,
                completed_steps=completed_steps,
                findings=findings,
                artifact_ids=artifact_ids,
                unresolved_questions=unresolved_questions,
                assumptions=assumptions or [],
            ),
        )
        return {"ok": True}

    return [publish_findings, save_investigation]
