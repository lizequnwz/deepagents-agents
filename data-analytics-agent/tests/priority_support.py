"""Scripted local workflow for UI checks; never claims live-model accuracy."""

from types import SimpleNamespace

from data_analytics_agent.agents.text_to_sql.tools import (
    create_query_saved_results_tool,
)
from data_analytics_agent.presentation import create_presentation_tools
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import create_create_report_tool
from data_analytics_agent.schemas import CoordinatorResponse
from data_analytics_agent.visualization.schemas import ChartRequest
from data_analytics_agent.visualization.tools import create_chart_tool
from tests.test_run_manager import Stream


class SavedPopulationGraph:
    def __init__(self, services, base_result_id):
        self.services, self.base_result_id = services, base_result_id

    async def astream_events(self, state, **kwargs):
        s = self.services
        run = s.runs.get(state["run_id"])
        if run.fresh_source_required:
            raise RuntimeError(
                "Synthetic warehouse refresh failed; previous report is preserved."
            )
        return await self.answer(state)

    async def answer(self, state):
        s = self.services
        run = s.runs.get(state["run_id"])
        selected = (
            run.analytical_input.input_result_id
            if run.analytical_input
            else self.base_result_id
        )
        query = create_query_saved_results_tool(
            s.results, s.runs, source_id=run.source_id
        )

        def runtime(call):
            return SimpleNamespace(state=state, tool_call_id=call)

        total = query.func(
            query="SELECT count(*) AS records FROM snapshot",
            bindings={"snapshot": selected},
            purpose="Population count",
            runtime=runtime("total"),
        )
        grouped = query.func(
            query='SELECT "Name" AS artist, count(*) AS records FROM snapshot GROUP BY "Name" ORDER BY "Name"',
            bindings={"snapshot": selected},
            purpose="Records by artist",
            runtime=runtime("grouped"),
        )
        chart_ids = []
        if grouped["row_count"]:
            chart = create_chart_tool(s.results, s.runs, source_id=run.source_id).func(
                spec=ChartRequest(
                    result_id=grouped["result_id"],
                    chart_type="bar",
                    title="Records by artist",
                    x="artist",
                    y=["records"],
                ),
                runtime=runtime("chart"),
            )
            chart_ids.append(chart["chart_id"])
        count = s.results.get_unscoped(total["result_id"]).rows[0]["records"]
        response = CoordinatorResponse(
            answer=f"The selected population contains {count} records.",
            result_ids=[total["result_id"], grouped["result_id"]],
            chart_ids=chart_ids,
        )
        publish = next(
            t
            for t in create_presentation_tools(
                s.results, s.analyses, s.runs, s.conversations, source_id=run.source_id
            )
            if t.name == "publish_findings"
        )
        publish.func(findings=response, runtime=runtime("publish"))
        create_create_report_tool(
            s.results, s.analyses, s.runs, s.reports, source_id=run.source_id
        ).func(
            report_json=ReportSpec(
                title="Artist population",
                blocks=[
                    {
                        "type": "metrics",
                        "metrics": [
                            {
                                "label": "Records",
                                "result_id": total["result_id"],
                                "column": "records",
                                "number_format": ",.0f",
                            }
                        ],
                    }
                ],
            ).model_dump_json(),
            runtime=runtime("report"),
        )
        return Stream(response)


class FreshPopulationGraph(SavedPopulationGraph):
    """Refresh with real local source SQL, then follow the shared scope path."""

    async def astream_events(self, state, **kwargs):
        from data_analytics_agent.agents.text_to_sql.tools import (
            create_execute_sql_tool,
        )

        s = self.services
        run = s.runs.get(state["run_id"])
        if run.fresh_source_required:
            runtime = SimpleNamespace(state=state, tool_call_id="fresh-source")
            source = create_execute_sql_tool(
                s.source(run.source_id),
                s.backend_for_source(run.source_id),
                s.results,
                s.runs,
                catalog=s.semantic_catalog_for_source(run.source_id),
            )
            result = source.func(
                query="SELECT ArtistId, Name FROM Artist",
                purpose="Fresh complete artists",
                runtime=runtime,
            )
            bind = next(
                t
                for t in create_presentation_tools(
                    s.results,
                    s.analyses,
                    s.runs,
                    s.conversations,
                    source_id=run.source_id,
                )
                if t.name == "bind_refreshed_input"
            )
            bind.func(result_id=result["result_id"], runtime=runtime)
        return await self.answer(state)
