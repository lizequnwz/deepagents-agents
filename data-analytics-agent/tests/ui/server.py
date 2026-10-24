"""Run the real API against isolated fixtures, without a model provider.

This module is test infrastructure. It is never selected by the product launcher.
Use ``python -m tests.ui.server --storage /tmp/analytics-ui-check --port 8765``.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import io
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import wave


SALES = [
    {"month": "2026-01", "region": "North", "sales": 100.0},
    {"month": "2026-01", "region": "South", "sales": 50.0},
    {"month": "2026-02", "region": "North", "sales": 120.0},
    {"month": "2026-02", "region": "South", "sales": 80.0},
]


def create_settings(storage: Path, frontend_root: Path | None = None):
    from data_analytics_agent.config import PROJECT_ROOT, Settings

    fixture_root = storage / "fixture-source"
    fixture_root.mkdir(parents=True, exist_ok=True)
    (fixture_root / "db").mkdir(exist_ok=True)
    (fixture_root / "semantic").mkdir(exist_ok=True)
    frontend = fixture_root / "frontend"
    if not frontend.exists():
        frontend.symlink_to(
            frontend_root or PROJECT_ROOT / "frontend", target_is_directory=True
        )
    database = fixture_root / "db" / "sales.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS Sales (month TEXT, region TEXT, sales REAL)"
        )
        connection.execute("DELETE FROM Sales")
        connection.executemany(
            "INSERT INTO Sales VALUES (:month,:region,:sales)", SALES
        )
    semantic = fixture_root / "semantic" / "sales.osi.yaml"
    semantic.write_text(
        """version: "0.1.1"
semantic_model:
  - name: ui_test_sales
    description: Isolated deterministic browser test data. Units are source units.
    datasets:
      - name: sales
        source: Sales
        primary_key: [month, region]
        description: One row per month and region.
        fields:
          - name: month
            expression: {dialects: [{dialect: ANSI_SQL, expression: month}]}
            description: Calendar month as YYYY-MM.
          - name: region
            expression: {dialects: [{dialect: ANSI_SQL, expression: region}]}
            description: Declared sales region.
          - name: sales
            expression: {dialects: [{dialect: ANSI_SQL, expression: sales}]}
            description: Observed sales in source units.
    relationships: []
    metrics:
      - name: total_sales
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(sales.sales)
        description: Total observed sales in source units.
""",
        encoding="utf-8",
    )
    registry = fixture_root / "data_sources.yaml"
    registry.write_text(
        f"""version: 1
default_source: ui_sales
backends:
  sqlite:
    type: sqlite
sources:
  ui_sales:
    name: Browser test sales
    description: Isolated fixture data; no model provider is used.
    backend: sqlite
    semantic_model: {json.dumps(str(semantic))}
    dialect: sqlite
    target:
      path: {json.dumps(str(database))}
    examples: []
""",
        encoding="utf-8",
    )
    return Settings(
        project_root=fixture_root,
        data_sources_config_path=registry,
        api_base_url="http://127.0.0.1:8765",
    )


def save_sales_answer(
    services, run_id: str, rows=None, *, action_payload=None, scenario=False
):
    """Commit a real dataset, chart, published findings and HTML report."""
    from data_analytics_agent.presentation import resolve_answer
    from data_analytics_agent.reporting.schemas import ReportSpec
    from data_analytics_agent.reporting.tools import generate_report
    from data_analytics_agent.schemas import CoordinatorResponse
    from data_analytics_agent.visualization.schemas import ChartRequest
    from data_analytics_agent.visualization.tools import create_chart_tool

    run = services.runs.get(run_id)
    rows = SALES if rows is None else rows
    runtime = SimpleNamespace(
        state={
            "thread_id": run.thread_id,
            "run_id": run_id,
            "source_id": run.source_id,
            "question": run.question,
        },
        tool_call_id=f"ui-chart-{run_id}",
    )
    is_upload = services.source(run.source_id).backend_type == "upload"
    query = "SELECT month, region, sales FROM " + (
        "input_rows" if is_upload else "Sales"
    )
    if rows != SALES:
        regions = sorted({row["region"] for row in rows})
        if not set(regions) <= {"North", "South"}:
            raise ValueError("The browser fixture has an unsupported region.")
        query += (
            " WHERE region IN ("
            + ",".join("'" + region + "'" for region in regions)
            + ")"
            if regions
            else " WHERE 1=0"
        )
    query += " ORDER BY month, region"
    if scenario:
        query = (
            "SELECT month, SUM(sales) AS sales, SUM(sales) * 0.9 AS lower_sales, "
            "SUM(sales) * 1.1 AS upper_sales FROM Sales GROUP BY month ORDER BY month"
        )
    if is_upload:
        from data_analytics_agent.agents.text_to_sql.tools import (
            create_query_saved_results_tool,
        )
        from data_analytics_agent.uploads import uploads_for_thread

        uploads = [
            item
            for item in uploads_for_thread(services, run.thread_id)
            if item.confirmed
        ]
        if not uploads:
            raise ValueError(
                "Review the file before running the browser fixture query."
            )
        result = create_query_saved_results_tool(
            services.results, services.runs, source_id=run.source_id
        ).func(
            query=query,
            bindings={"input_rows": uploads[0].result_id},
            purpose="Monthly sales rows from the reviewed file.",
            runtime=SimpleNamespace(
                state=runtime.state, tool_call_id=f"ui-query-{run_id}"
            ),
        )
        dataset = services.results.get(result["result_id"], run.thread_id)
    else:
        from data_analytics_agent.agents.text_to_sql.tools import (
            create_execute_sql_tool,
        )

        source = services.require_ready_source(run.source_id)
        result = create_execute_sql_tool(
            source,
            services.backend_for_source(run.source_id),
            services.results,
            services.runs,
            catalog=services.semantic_catalog_for_source(run.source_id),
        ).func(
            query=query,
            purpose="Monthly sales by region; source completeness is unknown.",
            runtime=SimpleNamespace(
                state=runtime.state, tool_call_id=f"ui-query-{run_id}"
            ),
        )
        dataset = services.results.get(result["result_id"], run.thread_id)
    output = {"chart": {"chart_id": None}}
    chart_id = None
    if dataset.row_count:
        output = create_chart_tool(
            services.results, services.runs, source_id=run.source_id
        ).func(
            spec=ChartRequest(
                result_id=dataset.result_id,
                chart_type="line",
                title="Monthly total sales scenario"
                if scenario
                else "Monthly sales by region",
                x="month",
                y=["sales"],
                color=None if scenario else "region",
                lower_bound="lower_sales" if scenario else None,
                upper_bound="upper_sales" if scenario else None,
                interval={
                    "kind": "scenario",
                    "method": "Illustrative plus or minus 10 percent; no probability is assigned.",
                }
                if scenario
                else None,
                notes=["Observed monthly sales use source units."],
            ),
            runtime=runtime,
        )
        if not output.get("ok"):
            raise RuntimeError(output)
        chart_id = output["chart"]["chart_id"]
    response = CoordinatorResponse(
        answer=(
            "The saved evidence contains monthly sales by region. Values use source units. Source completeness is unknown."
            if dataset.row_count
            else "No rows match the declared filters. Source completeness is unknown."
        ),
        result_ids=[dataset.result_id],
        chart_ids=[chart_id] if chart_id else [],
        assumptions=["Source completeness is unknown."],
    )
    findings = resolve_answer(
        response,
        thread_id=run.thread_id,
        source_id=run.source_id,
        results=services.results,
        analyses=services.analyses,
        runs=services.runs,
    )
    services.runs.publish(run_id, findings)
    dashboard_requested = services.storage.get("dashboard_requests", run_id, dict)
    if action_payload or dashboard_requested:
        from data_analytics_agent.dashboard.schemas import DashboardSpec
        from data_analytics_agent.dashboard.store import DashboardStore
        from data_analytics_agent.dashboard.tools import create_dashboard_tool

        definition = (
            action_payload["dashboard_spec"]
            if action_payload
            else {
                "title": "Monthly sales dashboard",
                "components": [
                    {"id": "sales-chart", "type": "chart", "chart_id": chart_id},
                    {
                        "id": "sales-table",
                        "type": "table",
                        "result_id": dataset.result_id,
                        "title": "Monthly sales rows",
                    },
                ],
                "filters": [],
            }
        )
        affected = (
            set(action_payload["affected_component_ids"]) if action_payload else set()
        )
        revised = []
        for original in definition["components"]:
            component = dict(original)
            if component["id"] in affected:
                if component["type"] == "chart":
                    component["chart_id"] = chart_id
                    component["empty_result_id"] = (
                        None if chart_id else dataset.result_id
                    )
                    if not chart_id:
                        component["title"] = "Monthly sales by region"
                elif component["type"] == "table":
                    component["result_id"] = dataset.result_id
                elif component["type"] == "metric":
                    component["metric"] = {
                        **component["metric"],
                        "result_id": dataset.result_id,
                    }
            revised.append(component)
        definition = DashboardSpec.model_validate({**definition, "components": revised})
        dashboard_store = getattr(services, "dashboards", None) or DashboardStore(
            services.storage
        )
        prepared = create_dashboard_tool(
            services.results,
            services.analyses,
            services.runs,
            services.reports,
            dashboard_store,
            source_id=run.source_id,
        ).func(
            dashboard_json=definition.model_dump_json(),
            runtime=SimpleNamespace(
                state=runtime.state, tool_call_id=f"ui-dashboard-{run_id}"
            ),
        )
        if not prepared.get("ok"):
            raise RuntimeError(prepared)
    spec = ReportSpec(
        title="Monthly sales scenario" if scenario else "Monthly sales evidence",
        blocks=[
            {
                "type": "narrative",
                "body": findings.answer,
            },
            *(
                [
                    {
                        "type": "chart",
                        "chart_id": chart_id,
                        "summary": "One observed value per month and region.",
                    }
                ]
                if chart_id
                else []
            ),
            {
                "type": "table",
                "title": "Monthly sales rows",
                "result_id": dataset.result_id,
                "row_limit": 10,
            },
        ],
    )
    services.runs.save_report_spec(run_id, spec.model_dump(mode="json"))
    report = generate_report(
        spec,
        thread_id=run.thread_id,
        source_id=run.source_id,
        result_store=services.results,
        analysis_store=services.analyses,
        run_store=services.runs,
        report_store=services.reports,
        findings=findings,
    )
    services.runs.attach_report(run_id, report.reference())
    return (
        findings.model_copy(update={"report": report.reference()}),
        dataset,
        output["chart"],
    )


class FixtureStream:
    def __init__(self, response=None, *, interrupt=None):
        self.response, self.interrupt = response, interrupt

    async def __aiter__(self):
        await asyncio.sleep(0.05)
        if False:
            yield {}

    async def interrupted(self):
        return self.interrupt is not None

    async def interrupts(self):
        return [self.interrupt]

    async def output(self):
        return {"structured_response": self.response}


class FixtureAgent:
    """Exercise the normal run manager with deterministic tool artifacts."""

    def __init__(self):
        self.services = None

    async def astream_events(self, agent_input, *, config, **_kwargs):
        from data_analytics_agent.schemas import CoordinatorResponse

        run_id = config["configurable"]["thread_id"]
        run = self.services.runs.get(run_id)
        if getattr(agent_input, "resume", None) is not None:
            self.services.storage.put(
                "ui_review_commands", run_id, {"resume": agent_input.resume}
            )
        corrections = self.services.runs.pending_corrections(run_id)
        if corrections:
            self.services.runs.mark_corrections_applied(
                run_id, [item.message_id for item in corrections], "coordinator"
            )
        question = run.question.lower()
        if "simulate failure" in question:
            raise RuntimeError(
                "Intentional browser-test failure. Previous evidence remains available."
            )
        if "hello" in question:
            return FixtureStream(
                CoordinatorResponse(
                    answer="Hello. The browser test workspace is ready."
                )
            )
        payload = None
        action_context = self.services.storage.get(
            "dashboard_run_context", run_id, dict
        )
        brief = action_context["brief"] if action_context else run.question
        if action_context:
            # Leave the committed view observable and allow a user to submit a
            # follow-up while a typed action is still running.
            await asyncio.sleep(2.0)
        if "Dashboard action data:\n" in brief:
            payload = json.loads(brief.split("Dashboard action data:\n", 1)[1])
        rows = SALES
        if corrections and corrections[-1].message in {"North", "South"}:
            rows = [row for row in rows if row["region"] == corrections[-1].message]
        if payload:
            for filter_definition in payload.get("filter_definitions", []):
                values = payload.get("applied_filters", {}).get(
                    filter_definition["id"], []
                )
                columns = {
                    binding["column"] for binding in filter_definition["bindings"]
                }
                if values and columns == {"region"}:
                    rows = [row for row in rows if row["region"] in values]
        save_sales_answer(self.services, run_id, rows, action_payload=payload)
        return FixtureStream()


def seed_services(storage: Path, frontend_root: Path | None = None):
    from data_analytics_agent.api import Services
    from data_analytics_agent.schemas import (
        ApprovalAction,
        ApprovalRequest,
        ChatTurn,
        ClarificationRequest,
        PythonReviewInput,
    )
    from data_analytics_agent.uploads import stage_upload

    settings = create_settings(storage, frontend_root)
    agent = FixtureAgent()
    services = Services(settings=settings, agent=agent)
    agent.services = services
    inputs = storage / "ui-inputs"
    inputs.mkdir(exist_ok=True)
    csv_path = inputs / "browser-sales.csv"
    csv_path.write_bytes(b"month,region,sales\n2026-01,North,100\n2026-02,South,80\n")
    import pyarrow as pa
    import pyarrow.parquet as pq
    from openpyxl import Workbook

    parquet_path = inputs / "browser-sales.parquet"
    pq.write_table(pa.Table.from_pylist(SALES), parquet_path)
    workbook_path = inputs / "browser-sales.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Sales"
    sheet.append(["month", "region", "sales"])
    for row in SALES:
        sheet.append([row["month"], row["region"], row["sales"]])
    book.save(workbook_path)
    book.close()
    document_path = inputs / "sales-context.txt"
    document_path.write_text(
        "Sales values use declared source units. The reporting grain is one month and region. Source completeness is unknown.",
        encoding="utf-8",
    )
    thread_id = services.conversations.create("ui_sales")
    run_id = services.runs.create(thread_id, "ui_sales", "Show monthly sales by region")
    services.conversations.begin_run(thread_id, run_id)
    answer, dataset, chart = save_sales_answer(services, run_id)
    services.runs.complete(run_id, answer)
    services.conversations.complete_run(
        thread_id,
        run_id,
        ChatTurn(
            run_id=run_id, user_message="Show monthly sales by region", answer=answer
        ),
    )
    scenario_thread = services.conversations.create("ui_sales")
    scenario_run = services.runs.create(
        scenario_thread,
        "ui_sales",
        "Show monthly total sales with an illustrative 10 percent scenario range",
    )
    services.conversations.begin_run(scenario_thread, scenario_run)
    scenario_answer, _, _ = save_sales_answer(services, scenario_run, scenario=True)
    services.runs.complete(scenario_run, scenario_answer)
    services.conversations.complete_run(
        scenario_thread,
        scenario_run,
        ChatTurn(
            run_id=scenario_run,
            user_message="Show monthly total sales with an illustrative 10 percent scenario range",
            answer=scenario_answer,
        ),
    )
    upload = stage_upload(
        services,
        filename="review-sales.csv",
        content=b"month,region,sales\n2026-01,North,100\n2026-02,South,80\n",
    )
    review_thread = services.conversations.create("ui_sales")
    review_run = services.runs.create(
        review_thread, "ui_sales", "Review the monthly sales query"
    )
    services.conversations.begin_run(review_thread, review_run)
    services.runs.mark_started(review_run)
    services.runs.require_approval(
        review_run,
        ApprovalRequest(
            interrupt_id="browser-sql-review",
            actions=[
                ApprovalAction(
                    action_name="execute_sql",
                    query="SELECT month, region, sales FROM Sales ORDER BY month, region",
                    arguments={
                        "query": "SELECT month, region, sales FROM Sales ORDER BY month, region",
                        "purpose": "Review monthly sales rows.",
                    },
                    allowed_decisions=["approve", "edit", "reject"],
                    source_id="ui_sales",
                )
            ],
        ),
    )
    python_thread = services.conversations.create("ui_sales")
    python_run = services.runs.create(
        python_thread, "ui_sales", "Review the saved-data Python analysis"
    )
    services.conversations.begin_run(python_thread, python_run)
    services.runs.mark_started(python_run)
    from data_analytics_agent.agents.text_to_sql.tools import create_execute_sql_tool

    saved_input = create_execute_sql_tool(
        services.require_ready_source("ui_sales"),
        services.backend_for_source("ui_sales"),
        services.results,
        services.runs,
        catalog=services.semantic_catalog_for_source("ui_sales"),
    ).func(
        query="SELECT month, region, sales FROM Sales ORDER BY month, region",
        purpose="Complete input for the Python review fixture.",
        runtime=SimpleNamespace(
            state={
                "run_id": python_run,
                "thread_id": python_thread,
                "source_id": "ui_sales",
                "question": "Review the saved-data Python analysis",
            },
            tool_call_id="python-review-input",
        ),
    )
    saved_input = services.results.get(saved_input["result_id"], python_thread)
    python_code = "summary = datasets['sales'].groupby('region', as_index=False)['sales'].sum()\noutput_datasets = {'summary': summary}"
    services.runs.require_approval(
        python_run,
        ApprovalRequest(
            interrupt_id="browser-python-review",
            actions=[
                ApprovalAction(
                    action_name="execute_analysis_python",
                    review_type="python",
                    query=python_code,
                    arguments={
                        "code": python_code,
                        "inputs": {"sales": saved_input.result_id},
                        "purpose": "Summarize complete saved sales by region.",
                    },
                    allowed_decisions=["approve", "edit", "reject"],
                    source_id="ui_sales",
                    description="Review the generated Python and its bound complete input before execution.",
                    input_datasets={
                        "sales": PythonReviewInput(
                            result_id=saved_input.result_id,
                            originating_question=saved_input.originating_question,
                            executed_sql=saved_input.executed_sql,
                            columns=saved_input.columns,
                            sample_rows=saved_input.preview,
                            profile=saved_input.profile,
                            row_count=saved_input.row_count,
                            truncated=saved_input.truncated,
                            parent_result_ids=[],
                        )
                    },
                )
            ],
        ),
    )
    clarify_thread = services.conversations.create("ui_sales")
    clarify_run = services.runs.create(
        clarify_thread, "ui_sales", "Clarify the sales population"
    )
    services.conversations.begin_run(clarify_thread, clarify_run)
    services.runs.mark_started(clarify_run)
    services.runs.require_clarification(
        clarify_run,
        ClarificationRequest(
            interrupt_id="browser-clarification",
            question="Which declared region should the analysis cover?",
            choices=["North", "South", "All regions"],
        ),
    )
    manifest = {
        "thread_id": thread_id,
        "run_id": run_id,
        "result_id": dataset.result_id,
        "chart_id": chart["chart_id"],
        "report_id": answer.report.report_id,
        "scenario_thread_id": scenario_thread,
        "upload_thread_id": upload.thread_id,
        "upload_id": upload.upload_id,
        "review_thread_id": review_thread,
        "review_run_id": review_run,
        "python_review_thread_id": python_thread,
        "python_review_run_id": python_run,
        "clarification_thread_id": clarify_thread,
        "clarification_run_id": clarify_run,
        "input_paths": {
            "csv": str(csv_path),
            "parquet": str(parquet_path),
            "excel": str(workbook_path),
            "document": str(document_path),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (storage / "ui-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return services, manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--frontend-root", type=Path)
    args = parser.parse_args()
    args.storage.mkdir(parents=True, exist_ok=True)
    os.environ["ANALYTICS_STORAGE_DIR"] = str(args.storage)
    os.environ["OPENAI_API_KEY"] = "browser-test-no-provider"
    os.environ["MODEL_PROVIDER"] = "openai"
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["REQUIRE_SQL_APPROVAL"] = "false"
    os.environ["REQUIRE_PYTHON_APPROVAL"] = "false"
    from data_analytics_agent.api import create_app
    import uvicorn

    services, manifest = seed_services(args.storage, args.frontend_root)
    from langchain_core.runnables import RunnableLambda
    from data_analytics_agent import transcription

    async def fixture_transcription(content: bytes, *, model: str):
        del model
        with wave.open(io.BytesIO(content), "rb") as recording:
            if (
                recording.getnchannels() != 1
                or recording.getsampwidth() != 2
                or not recording.getnframes()
            ):
                raise ValueError(
                    "The browser must submit a nonempty mono PCM WAV recording."
                )
        (args.storage / "recorded-question.wav").write_bytes(content)
        return "Show monthly sales for the North region."

    transcription.whisper_transcriber = RunnableLambda(fixture_transcription)
    print(
        json.dumps(
            {"fixture_manifest": str(args.storage / "ui-manifest.json"), **manifest}
        ),
        flush=True,
    )
    uvicorn.run(
        create_app(services), host="127.0.0.1", port=args.port, access_log=False
    )


if __name__ == "__main__":
    main()
