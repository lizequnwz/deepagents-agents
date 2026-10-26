"""Coordinator-owned dashboard composition after evidence publication."""

import json

from langchain.tools import ToolRuntime, tool

from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.dashboard.schemas import DashboardSpec, MetricComponent
from data_analytics_agent.dashboard.service import DashboardService
from data_analytics_agent.reporting.formats import validate_number_format


def create_dashboard_tool(results, analyses, runs, reports, dashboards, *, source_id):
    service = DashboardService(results, analyses, runs, reports, dashboards)

    @tool
    def create_dashboard(dashboard_json: str, runtime: ToolRuntime) -> dict:
        """Prepare a persistent dashboard from DashboardSpec JSON after publish_findings.

        Compose metric components with ReportMetric saved column/row bindings,
        chart components with chart_id, tables with result_id and text notes.
        Each component has a stable id and span 1, 2 or 3. Filters declare id,
        label, kind category/date_range and explicit component_id/column bindings.
        Do not invent numerical values, HTML, scripts or warehouse queries.
        For dashboard actions, preserve component IDs/types and filter definitions.
        The dashboard becomes current only after its required report succeeds.
        Call create_report after this tool succeeds.
        """
        context = _runtime_context(runtime)
        if saved := runs.storage.committed(context.run_id, runtime.tool_call_id):
            return json.loads(saved)
        try:
            run = runs.get(context.run_id)
            if run.findings is None:
                raise ValueError("Call publish_findings before creating the dashboard.")
            spec = DashboardSpec.model_validate_json(dashboard_json)
            for component in spec.components:
                if isinstance(component, MetricComponent):
                    validate_number_format(component.metric.number_format)
            service.validate_spec(
                spec,
                thread_id=context.thread_id,
                source_id=source_id,
                findings=run.findings,
            )
            action = dashboards.action_for_run(context.run_id)
            options = {}
            if action:
                previous, applied = service.validate_action_spec(
                    spec, action, thread_id=context.thread_id, source_id=source_id
                )
                options = dict(
                    dashboard_id=previous.dashboard_id,
                    expected_revision=previous.revision_id,
                    applied_filters=applied,
                    saved_filter_values=applied,
                )
                question = previous.question
            else:
                question = context.question
            revision = dashboards.create_candidate(
                spec,
                thread_id=context.thread_id,
                source_id=source_id,
                run_id=context.run_id,
                question=question,
                request_id=runtime.tool_call_id,
                **options,
            )
            response = {
                "ok": True,
                "dashboard_id": revision.dashboard_id,
                "revision_id": revision.revision_id,
                "version": revision.version,
                "message": "Dashboard prepared. Create its HTML report to publish the revision.",
            }
            runs.storage.commit(
                context.run_id, runtime.tool_call_id, json.dumps(response)
            )
            return response
        except (ValueError, KeyError, IndexError, OSError) as exc:
            return {"ok": False, "error": str(exc), "retryable": True}

    return create_dashboard
