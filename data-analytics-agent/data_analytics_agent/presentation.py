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
    for key in response.result_ids:
        evidence.result(key)
    analytical = [evidence.analysis(key) for key in response.analysis_ids]
    charts = [evidence.chart(key) for key in response.chart_ids]
    selected = evidence.results
    primary = next(iter(selected), None)
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
            from data_analytics_agent.analytical_scope import (
                check_inputs,
                require_refreshed_input,
            )

            require_refreshed_input(runs, context.run_id)
            keys = list(findings.result_ids)
            for chart_id in findings.chart_ids:
                chart = runs.storage.get("charts", chart_id, dict)
                if chart is None:
                    raise StoreNotFound(chart_id)
                keys.append(chart["spec"]["result_id"])
            for analysis_id in findings.analysis_ids:
                analysis = analyses.get(
                    analysis_id, context.thread_id, source_id=source_id
                ).analysis
                keys.extend(analysis.input_result_ids)
            check_inputs(results, runs, context.run_id, keys)
            answer = resolve_answer(
                findings,
                thread_id=context.thread_id,
                source_id=source_id,
                results=results,
                analyses=analyses,
                runs=runs,
            )
            run = runs.get(context.run_id)
            if run.analytical_input and not run.source_expansion_allowed:
                material = []
                for reference in answer.results:
                    try:
                        check_inputs(
                            results, runs, context.run_id, [reference.result_id]
                        )
                    except ValueError:
                        continue
                    material.append(reference)
                answer = answer.model_copy(
                    update={
                        "results": material,
                        "primary_result_id": material[0].result_id
                        if material
                        else None,
                    }
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
        except (PendingCorrections, ValueError) as exc:
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

    @tool
    def bind_refreshed_input(result_id: str, runtime: ToolRuntime) -> dict:
        """Bind the regenerated equivalent of a refresh's selected base dataset.

        Required for refreshes with a selected input. First retrieve fresh source
        rows and recompute any saved derivation at the same grain and fields.
        This reapplies the previous categorical/date scope and returns its exact
        new input ID. Analyze that input or descendants before publishing.
        """
        from data_analytics_agent.analytical_scope import check_inputs, prepare_input

        context = _runtime_context(runtime)
        run = runs.get(context.run_id)
        if not run.fresh_source_required or not run.analytical_input:
            raise ToolException(
                "Only a refresh with a selected dataset requires this binding."
            )
        try:
            old = results.get(
                run.analytical_input.selected_result_id,
                context.thread_id,
                source_id=source_id,
            )
            new = results.get(result_id, context.thread_id, source_id=source_id)
            check_inputs(results, runs, context.run_id, [result_id])
            import pyarrow.parquet as pq

            old_types = {
                field.name: field.type for field in pq.read_schema(old.parquet_path)
            }
            new_types = {
                field.name: field.type for field in pq.read_schema(new.parquet_path)
            }
            if set(new.columns) != set(old.columns) or any(
                new_types[column] != old_types[column] for column in old.columns
            ):
                raise ValueError(
                    "Refresh must regenerate the selected dataset's fields and types at the same grain; reshape the fresh data before binding."
                )
            scope = run.analytical_input.scope
            if scope:
                scope = scope.model_copy(update={"base_result_id": result_id})
            updated = prepare_input(
                results, context.thread_id, source_id, result_id, scope, refreshed=True
            )
            updated = updated.model_copy(update={"grain": run.analytical_input.grain})
            runs.bind_refreshed_input(context.run_id, updated)
        except (StoreNotFound, ValueError) as exc:
            raise ToolException(str(exc)) from exc
        return {"ok": True, "analytical_input": updated.model_dump(mode="json")}

    publish_findings.handle_tool_error = True
    bind_refreshed_input.handle_tool_error = True
    return [publish_findings, save_investigation, bind_refreshed_input]


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
