"""Dashboard state, evidence, and action boundaries over real saved artifacts."""

from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from data_analytics_agent.dashboard.schemas import (
    ChartComponent,
    DashboardAction,
    DashboardFilter,
    DashboardSpec,
    DashboardViewEdit,
    MetricComponent,
    TableComponent,
)
from data_analytics_agent.dashboard.service import DashboardService
from data_analytics_agent.dashboard.store import DashboardConflict, DashboardStore
from data_analytics_agent.dashboard.tools import create_dashboard_tool
from data_analytics_agent.datasets import StoreNotFound
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.handoff import ReportCompletionMiddleware
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import (
    create_create_report_tool,
    generate_report,
)
from data_analytics_agent.run_manager import RunManager
from data_analytics_agent.schemas import ChatTurn, CoordinatorResponse, RunStatus
from data_analytics_agent.steering import PendingCorrections
from tests.test_run_manager import Graph, Stream
from data_analytics_agent.visualization.schemas import ChartSpec
from data_analytics_agent.visualization.tools import create_chart_tool


@pytest.fixture
def dashboard(workspace):
    w = workspace
    w.dataset = w.results.save(
        columns=["region", "day", "sales"],
        rows=[
            {"region": "North", "day": date(2026, 1, 1), "sales": 10},
            {"region": "South", "day": date(2026, 1, 2), "sales": 20},
        ],
        thread_id=w.thread,
        source_id="test",
        executed_sql="SELECT region, day, sales FROM facts",
    )
    output = create_chart_tool(w.results, w.runs, source_id="test").func(
        spec=ChartSpec(
            result_id=w.dataset.result_id,
            chart_type="bar",
            title="Sales by region",
            x="region",
            y=["sales"],
            notes=["Source completeness is unknown."],
        ),
        runtime=w.runtime("chart"),
    )
    assert output["ok"], output
    w.chart = ChartSpec.model_validate(output["chart"])
    findings = resolve_answer(
        CoordinatorResponse(
            answer="Sales by region in source units.",
            result_ids=[w.dataset.result_id],
            chart_ids=[w.chart.chart_id],
        ),
        thread_id=w.thread,
        source_id="test",
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
    )
    w.runs.publish(w.run, findings)
    w.report = generate_report(
        ReportSpec(
            title="Sales dashboard",
            blocks=[
                {
                    "type": "metrics",
                    "metrics": [
                        {
                            "label": "Sales",
                            "result_id": w.dataset.result_id,
                            "column": "sales",
                        }
                    ],
                },
                {
                    "type": "chart",
                    "chart_id": w.chart.chart_id,
                    "summary": "Sales by region",
                },
                {
                    "type": "table",
                    "result_id": w.dataset.result_id,
                    "title": "Saved sales",
                },
            ],
        ),
        thread_id=w.thread,
        source_id="test",
        result_store=w.results,
        analysis_store=w.analyses,
        run_store=w.runs,
        report_store=w.reports,
        findings=findings,
    )
    w.runs.attach_report(w.run, w.report.reference())
    w.runs.complete(w.run, findings.model_copy(update={"report": w.report.reference()}))
    w.conversations.complete_run(
        w.thread,
        w.run,
        ChatTurn(
            run_id=w.run, user_message="Analyze sales", answer=w.runs.get(w.run).answer
        ),
    )
    w.dashboards = DashboardStore(w.storage)
    w.service = DashboardService(w.results, w.analyses, w.runs, w.reports, w.dashboards)
    w.spec = DashboardSpec(
        title="Sales by region",
        components=[
            MetricComponent(
                id="sales",
                metric={
                    "label": "Sales",
                    "result_id": w.dataset.result_id,
                    "column": "sales",
                },
            ),
            ChartComponent(id="trend", chart_id=w.chart.chart_id),
            TableComponent(id="detail", result_id=w.dataset.result_id),
        ],
        filters=[
            DashboardFilter(
                id="region",
                label="Region",
                bindings=[
                    {"component_id": key, "column": "region"}
                    for key in ("sales", "trend", "detail")
                ],
            ),
            DashboardFilter(
                id="day",
                label="Day",
                kind="date_range",
                bindings=[
                    {"component_id": key, "column": "day"}
                    for key in ("sales", "trend", "detail")
                ],
            ),
        ],
    )
    w.revision = w.service.create_from_report(
        w.run,
        thread_id=w.thread,
        source_id="test",
        spec=w.spec,
        request_id="save-board",
    )
    return w


def test_saved_dashboard_resolves_values_and_survives_restart(dashboard):
    w = dashboard
    view = w.service.view(w.revision.dashboard_id, w.thread, source_id="test")
    assert view.components[0].value == 10
    assert view.components[0].formatted_value == "10.00"
    assert view.components[1].figure["data"]
    assert view.components[1].analysis_result_id == w.dataset.result_id
    assert "Source completeness is unknown." in view.components[1].warnings
    assert view.components[2].row_count == 2
    assert len(view.components[2].rows) == 2
    assert {r.completeness for r in view.freshness} == {"unknown"}
    assert set(view.filters[0].options) == {"North", "South"}
    restarted = DashboardStore(w.storage)
    assert (
        restarted.get(w.revision.dashboard_id, w.thread, source_id="test") == w.revision
    )
    assert restarted.list_for_conversation(w.thread, source_id="test") == [w.revision]
    with pytest.raises(StoreNotFound):
        restarted.get(w.revision.dashboard_id, "another-thread", source_id="test")


def test_view_edit_is_atomic_idempotent_and_keeps_data(dashboard):
    w = dashboard
    before = w.storage.load("datasets", dict)
    edit = DashboardViewEdit(
        expected_revision=w.revision.revision_id,
        request_id="rename",
        title="Regional sales",
        component_order=["detail", "sales", "trend"],
        component_spans={"trend": 3},
        saved_filter_values={"region": ["South"]},
    )
    revised = w.service.edit_view(
        w.revision.dashboard_id, w.thread, source_id="test", edit=edit
    )
    assert revised.version == 2 and revised.report_id == w.report.report_id
    assert revised.applied_filters == {}
    assert revised.saved_filter_values == {"region": ["South"]}
    assert revised.spec.components[2].span == 3
    assert (
        w.service.edit_view(
            w.revision.dashboard_id, w.thread, source_id="test", edit=edit
        )
        == revised
    )
    assert w.storage.load("datasets", dict) == before
    assert (
        w.dashboards.get_revision(w.revision.revision_id, w.thread, source_id="test")
        == w.revision
    )
    with pytest.raises(DashboardConflict, match="changed"):
        w.service.edit_view(
            w.revision.dashboard_id,
            w.thread,
            source_id="test",
            edit=edit.model_copy(update={"request_id": "stale"}),
        )
    with pytest.raises(DashboardConflict, match="reused"):
        w.service.edit_view(
            w.revision.dashboard_id,
            w.thread,
            source_id="test",
            edit=edit.model_copy(update={"title": "Another title"}),
        )


def test_rejects_unselected_sampled_and_unknown_filter_evidence(dashboard):
    w = dashboard
    findings = w.runs.get(w.run).findings
    with pytest.raises(ValueError, match="selected published"):
        bad = w.spec.model_copy(deep=True)
        bad.components[0].metric.result_id = "invented"
        w.service.validate_spec(
            bad, thread_id=w.thread, source_id="test", findings=findings
        )
    with pytest.raises(ValueError, match="absent"):
        bad = w.spec.model_copy(deep=True)
        bad.filters[0].bindings[
            0
        ].column = "same_name_does_not_establish_a_relationship"
        w.service.validate_spec(
            bad, thread_id=w.thread, source_id="test", findings=findings
        )
    with pytest.raises(ValidationError, match="component IDs"):
        DashboardSpec(
            title="Bad", components=[w.spec.components[0], w.spec.components[0]]
        )
    with pytest.raises(ValueError, match="finite stored"):
        bad = w.spec.model_copy(deep=True)
        bad.components[0].metric.column = "region"
        w.service.validate_spec(
            bad, thread_id=w.thread, source_id="test", findings=findings
        )
    sample = w.results.save(
        columns=w.dataset.columns,
        rows=w.dataset.rows[:1],
        thread_id=w.thread,
        source_id="test",
        kind="presentation",
        parent_result_ids=[w.dataset.result_id],
    )
    selected = resolve_answer(
        CoordinatorResponse(
            answer="Saved chart sample.",
            result_ids=[sample.result_id],
            chart_ids=[w.chart.chart_id],
        ),
        thread_id=w.thread,
        source_id="test",
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
    )
    bad = w.spec.model_copy(deep=True)
    bad.components[0].metric.result_id = sample.result_id
    with pytest.raises(ValueError, match="not a display sample"):
        w.service.validate_spec(
            bad, thread_id=w.thread, source_id="test", findings=selected
        )


def test_candidate_needs_report_and_stale_candidate_never_replaces_view(dashboard):
    w = dashboard
    candidate = w.dashboards.create_candidate(
        w.spec,
        thread_id=w.thread,
        source_id="test",
        run_id="new-run",
        question="Update sales",
        dashboard_id=w.revision.dashboard_id,
        expected_revision=w.revision.revision_id,
    )
    assert (
        w.dashboards.get(w.revision.dashboard_id, w.thread, source_id="test")
        == w.revision
    )
    with pytest.raises(ValueError, match="report"):
        w.dashboards.finalize_for_run("new-run", None)
    w.service.edit_view(
        w.revision.dashboard_id,
        w.thread,
        source_id="test",
        edit=DashboardViewEdit(
            expected_revision=w.revision.revision_id,
            request_id="new-view",
            title="Saved view",
        ),
    )
    with pytest.raises(DashboardConflict, match="while this action"):
        w.dashboards.finalize_for_run("new-run", w.report.report_id)
    assert (
        w.dashboards.get(w.revision.dashboard_id, w.thread, source_id="test").spec.title
        == "Saved view"
    )
    assert (
        w.storage.load("dashboard_candidates", dict)[candidate.revision_id]["status"]
        == "failed"
    )


def test_action_reservation_is_idempotent_and_scoped(dashboard):
    w = dashboard
    action = DashboardAction(
        action="filter",
        expected_revision=w.revision.revision_id,
        request_id="region-filter",
        filter_values={"region": ["South"]},
    )
    plan = w.service.action_plan(
        w.revision.dashboard_id, w.thread, source_id="test", action=action
    )
    assert set(plan.affected_component_ids) == {"sales", "trend", "detail"}
    assert "configured code reviews" in plan.question
    record = w.dashboards.begin_action(
        w.revision.dashboard_id, w.thread, source_id="test", action=action
    )
    assert (
        w.dashboards.begin_action(
            w.revision.dashboard_id, w.thread, source_id="test", action=action
        )
        == record
    )
    with pytest.raises(DashboardConflict, match="reused"):
        w.dashboards.begin_action(
            w.revision.dashboard_id,
            w.thread,
            source_id="test",
            action=action.model_copy(update={"filter_values": {"region": ["North"]}}),
        )
    w.dashboards.attach_action_run(record.action_id, "new-run")
    w.dashboards.fail_for_run("new-run", "SQL execution failed")
    assert (
        w.service.view(
            w.revision.dashboard_id, w.thread, source_id="test"
        ).pending_action.error
        == "SQL execution failed"
    )
    assert (
        w.dashboards.get(w.revision.dashboard_id, w.thread, source_id="test")
        == w.revision
    )


def test_action_refuses_old_evidence_and_checks_full_population(dashboard):
    w = dashboard
    action = DashboardAction(
        action="filter",
        expected_revision=w.revision.revision_id,
        request_id="region-filter",
        filter_values={"region": ["South"]},
    )
    record = w.dashboards.begin_action(
        w.revision.dashboard_id, w.thread, source_id="test", action=action
    )
    with pytest.raises(ValueError, match="newly saved evidence"):
        w.service.validate_action_spec(
            w.spec, record, thread_id=w.thread, source_id="test"
        )
    # The first ten displayed rows match. A later row still violates the filter.
    mixed = w.results.save(
        columns=w.dataset.columns,
        rows=[{"region": "South", "day": date(2026, 1, 2), "sales": 20}] * 10
        + [{"region": "North", "day": date(2026, 1, 2), "sales": 10}],
        thread_id=w.thread,
        source_id="test",
    )
    w.service._validate_population(mixed, [])
    with pytest.raises(ValueError, match="does not satisfy applied filter"):
        w.service._validate_population(
            mixed, [(w.spec.filters[0], "region", ["South"])]
        )
    with pytest.raises(ValueError, match="does not satisfy applied filter"):
        w.service._validate_population(
            w.dataset, [(w.spec.filters[1], "day", ["2026-01-02", "2026-01-02"])]
        )


def test_full_action_commits_new_evidence_and_keeps_original(dashboard):
    w = dashboard
    action = DashboardAction(
        action="filter",
        expected_revision=w.revision.revision_id,
        request_id="region-filter",
        filter_values={"region": ["South"]},
    )
    record = w.dashboards.begin_action(
        w.revision.dashboard_id, w.thread, source_id="test", action=action
    )
    w.dashboards.attach_action_run(record.action_id, "filtered-run")
    data = w.results.save(
        columns=w.dataset.columns,
        rows=[{"region": "South", "day": date(2026, 1, 2), "sales": 20}],
        thread_id=w.thread,
        source_id="test",
        parent_result_ids=[w.dataset.result_id],
        kind="saved_sql",
    )
    chart = w.chart.model_copy(
        update={
            "chart_id": "new-chart",
            "result_id": data.result_id,
            "source_result_id": data.result_id,
        }
    )
    w.storage.put(
        "charts",
        chart.chart_id,
        {
            "thread_id": w.thread,
            "source_id": "test",
            "spec": chart.model_dump(mode="json"),
        },
    )
    spec = w.spec.model_copy(deep=True)
    spec.components[0].metric.result_id = data.result_id
    spec.components[1].chart_id = chart.chart_id
    spec.components[2].result_id = data.result_id
    previous, applied = w.service.validate_action_spec(
        spec, record, thread_id=w.thread, source_id="test"
    )
    w.dashboards.create_candidate(
        spec,
        thread_id=w.thread,
        source_id="test",
        run_id="filtered-run",
        question=previous.question,
        dashboard_id=previous.dashboard_id,
        expected_revision=previous.revision_id,
        applied_filters=applied,
    )
    [revised] = w.dashboards.finalize_for_run("filtered-run", w.report.report_id)
    assert revised.applied_filters == {"region": ["South"]}
    assert w.dashboards.finalize_for_run("filtered-run", w.report.report_id) == [
        revised
    ]
    assert (
        w.service.view(revised.dashboard_id, w.thread, source_id="test")
        .components[0]
        .value
        == 20
    )
    assert set(
        w.service.view(revised.dashboard_id, w.thread, source_id="test")
        .filters[0]
        .options
    ) == {"North", "South"}
    assert (
        w.dashboards.get_revision(
            previous.revision_id, w.thread, source_id="test"
        ).applied_filters
        == {}
    )
    assert (
        w.dashboards.latest_action(
            revised.dashboard_id, w.thread, source_id="test"
        ).status
        == "completed"
    )


def test_empty_population_is_explicit_and_never_reuses_old_chart(dashboard):
    w = dashboard
    empty = w.results.save(
        columns=w.dataset.columns,
        rows=[],
        thread_id=w.thread,
        source_id="test",
        parent_result_ids=[w.dataset.result_id],
        kind="saved_sql",
    )
    spec = w.spec.model_copy(deep=True)
    spec.components[0].metric.result_id = empty.result_id
    spec.components[1] = ChartComponent(
        id="trend", empty_result_id=empty.result_id, title="Sales by region"
    )
    spec.components[2].result_id = empty.result_id
    answer = resolve_answer(
        CoordinatorResponse(answer="No rows match.", result_ids=[empty.result_id]),
        thread_id=w.thread,
        source_id="test",
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
    )
    w.service.validate_spec(spec, thread_id=w.thread, source_id="test", findings=answer)
    draft = w.dashboards.create_candidate(
        spec,
        thread_id=w.thread,
        source_id="test",
        run_id="empty-run",
        question="No matching rows",
    )
    w.dashboards.finalize_for_run("empty-run", w.report.report_id)
    view = w.service.view(draft.dashboard_id, w.thread, source_id="test")
    assert (
        view.components[0].value is None and view.components[0].formatted_value == "—"
    )
    assert view.components[1].figure is None and view.components[1].row_count == 0
    assert view.components[2].rows == []


def test_filter_definition_changes_do_not_relabel_applied_facts(dashboard):
    w = dashboard
    previous = w.revision.model_copy(update={"applied_filters": {"region": ["South"]}})
    w.storage.put("dashboard_revisions", previous.revision_id, previous)
    with pytest.raises(ValueError, match="Reset an applied filter"):
        w.service.edit_view(
            previous.dashboard_id,
            w.thread,
            source_id="test",
            edit=DashboardViewEdit(
                expected_revision=previous.revision_id,
                request_id="remove-applied",
                filters=[],
            ),
        )
    with pytest.raises(ValueError, match="ISO dates"):
        w.service.action_plan(
            previous.dashboard_id,
            w.thread,
            source_id="test",
            action=DashboardAction(
                action="filter",
                expected_revision=previous.revision_id,
                request_id="bad-day",
                filter_values={"day": ["01/02/2026", "01/03/2026"]},
            ),
        )
    with pytest.raises(ValueError, match="undeclared"):
        w.service.action_plan(
            previous.dashboard_id,
            w.thread,
            source_id="test",
            action=DashboardAction(
                action="filter",
                expected_revision=previous.revision_id,
                request_id="bad-field",
                filter_values={"tenant": ["foreign"]},
            ),
        )


def test_recovery_and_history_deletion_cover_reservations(dashboard):
    w = dashboard
    action = DashboardAction(
        action="refresh", expected_revision=w.revision.revision_id, request_id="refresh"
    )
    w.dashboards.begin_action(
        w.revision.dashboard_id, w.thread, source_id="test", action=action
    )
    w.dashboards.recover(w.runs)
    assert (
        w.dashboards.latest_action(
            w.revision.dashboard_id, w.thread, source_id="test"
        ).status
        == "failed"
    )
    w.dashboards.forget_conversations({w.thread})
    assert w.dashboards.list_for_conversation(w.thread, source_id="test") == []
    assert w.storage.load("dashboard_actions", dict) == {}
    assert w.storage.load("dashboard_candidates", dict) == {}


def test_refresh_rejects_newly_wrapped_stale_warehouse_snapshot(dashboard):
    w = dashboard
    action = DashboardAction(
        action="refresh",
        expected_revision=w.revision.revision_id,
        request_id="fresh-data",
    )
    record = w.dashboards.begin_action(
        w.revision.dashboard_id, w.thread, source_id="test", action=action
    )
    data = w.results.save(
        columns=w.dataset.columns,
        rows=w.dataset.rows,
        thread_id=w.thread,
        source_id="test",
        kind="saved_sql",
        parent_result_ids=[w.dataset.result_id],
    )
    chart = w.chart.model_copy(
        update={
            "chart_id": "copied-chart",
            "result_id": data.result_id,
            "source_result_id": data.result_id,
        }
    )
    w.storage.put(
        "charts",
        chart.chart_id,
        {
            "thread_id": w.thread,
            "source_id": "test",
            "spec": chart.model_dump(mode="json"),
        },
    )
    spec = w.spec.model_copy(deep=True)
    spec.components[0].metric.result_id = data.result_id
    spec.components[1].chart_id = chart.chart_id
    spec.components[2].result_id = data.result_id
    with pytest.raises(ValueError, match="fresh source observations"):
        w.service.validate_action_spec(
            spec, record, thread_id=w.thread, source_id="test"
        )


def test_coordinator_tool_requires_publication_and_is_idempotent(dashboard):
    w = dashboard
    run_id = w.runs.create(w.thread, "test", "Build a sales dashboard")
    runtime = SimpleNamespace(
        state={
            "thread_id": w.thread,
            "run_id": run_id,
            "source_id": "test",
            "question": "Build a sales dashboard",
        },
        tool_call_id="dashboard-call",
    )
    tool = create_dashboard_tool(
        w.results, w.analyses, w.runs, w.reports, w.dashboards, source_id="test"
    )
    result = tool.func(dashboard_json=w.spec.model_dump_json(), runtime=runtime)
    assert not result["ok"] and "publish_findings" in result["error"]
    w.runs.publish(run_id, w.runs.get(w.run).findings)
    first = tool.func(dashboard_json=w.spec.model_dump_json(), runtime=runtime)
    assert first["ok"], first
    assert tool.func(dashboard_json=w.spec.model_dump_json(), runtime=runtime) == first
    assert w.dashboards.candidate_for_run(run_id).revision_id == first["revision_id"]
    with pytest.raises(StoreNotFound):
        w.dashboards.get(first["dashboard_id"], w.thread, source_id="test")


@pytest.mark.parametrize("reason", ["correction", "stop"])
def test_completion_guard_keeps_candidate_unpublished(dashboard, reason):
    w = dashboard
    run_id = w.runs.create(w.thread, "test", "Build revised dashboard")
    candidate = w.dashboards.create_candidate(
        w.spec,
        thread_id=w.thread,
        source_id="test",
        run_id=run_id,
        question="Revised dashboard",
    )
    manager = RunManager(
        conversations=w.conversations,
        runs=w.runs,
        results=w.results,
        analyses=w.analyses,
        reports=w.reports,
        dashboards=w.dashboards,
    )
    if reason == "correction":
        assert w.runs.accept_correction(run_id, "Use a different reporting population.")
        failure = PendingCorrections
    else:
        w.runs.cancel_event(run_id).set()
        failure = InterruptedError
    with pytest.raises(failure):
        manager._finish(run_id, w.runs.get(w.run).answer)
    with pytest.raises(StoreNotFound):
        w.dashboards.get(candidate.dashboard_id, w.thread, source_id="test")
    assert (
        w.dashboards.get(w.revision.dashboard_id, w.thread, source_id="test")
        == w.revision
    )


async def test_report_completion_and_manager_publish_dashboard_without_provider(
    dashboard,
):
    w = dashboard
    run_id = w.runs.create(w.thread, "test", "Build a saved sales dashboard")
    w.conversations.begin_run(w.thread, run_id)
    w.storage.put(
        "dashboard_requests",
        run_id,
        {"run_id": run_id, "thread_id": w.thread, "source_id": "test"},
    )
    w.runs.publish(run_id, w.runs.get(w.run).findings)
    runtime = SimpleNamespace(
        state={
            "thread_id": w.thread,
            "run_id": run_id,
            "source_id": "test",
            "question": "Build a saved sales dashboard",
        },
        tool_call_id="report-before-dashboard",
    )
    report_tool = create_create_report_tool(
        w.results, w.analyses, w.runs, w.reports, source_id="test"
    )
    assert report_tool.func(
        report_json=w.report.spec.model_dump_json(), runtime=runtime
    )["ok"]
    middleware = ReportCompletionMiddleware(w.runs, w.dashboards)
    assert "jump_to" not in middleware.before_model({"run_id": run_id}, None)
    runtime.tool_call_id = "prepare-dashboard"
    dashboard_tool = create_dashboard_tool(
        w.results, w.analyses, w.runs, w.reports, w.dashboards, source_id="test"
    )
    prepared = dashboard_tool.func(
        dashboard_json=w.spec.model_dump_json(), runtime=runtime
    )
    assert prepared["ok"], prepared
    assert middleware.before_model({"run_id": run_id}, None) == {"jump_to": "end"}
    graph = Graph([Stream(CoordinatorResponse(answer="Already published findings."))])
    manager = RunManager(
        conversations=w.conversations,
        runs=w.runs,
        results=w.results,
        analyses=w.analyses,
        reports=w.reports,
        dashboards=w.dashboards,
        agent=graph,
    )
    await manager.start(run_id)
    run = w.runs.get(run_id)
    assert run.status == RunStatus.COMPLETED and run.answer.report
    revision = w.dashboards.get(prepared["dashboard_id"], w.thread, source_id="test")
    assert revision.report_id == run.answer.report.report_id
    assert w.conversations.get(w.thread).turns[-1].run_id == run_id


async def test_paused_action_blocks_view_mutation_but_preserves_retry_and_resume(
    dashboard,
):
    w = dashboard
    edit = DashboardViewEdit(
        expected_revision=w.revision.revision_id,
        request_id="saved-before-action",
        title="Saved regional sales",
    )
    current = w.service.edit_view(
        w.revision.dashboard_id, w.thread, source_id="test", edit=edit
    )
    action = w.dashboards.begin_action(
        current.dashboard_id,
        w.thread,
        source_id="test",
        action=DashboardAction(
            action="drill",
            expected_revision=current.revision_id,
            request_id="explain-saved-metric",
            component_id="sales",
            question="Explain the saved Sales metric using its existing evidence.",
        ),
    )
    run_id = w.runs.create(w.thread, "test", action.action.question)
    w.dashboards.attach_action_run(action.action_id, run_id)
    w.conversations.begin_run(w.thread, run_id)
    w.runs.mark_started(run_id)
    w.runs.start_active(run_id)
    w.runs.publish(run_id, w.runs.get(w.run).findings)
    runtime = SimpleNamespace(
        state={
            "thread_id": w.thread,
            "run_id": run_id,
            "source_id": "test",
            "question": action.action.question,
        },
        tool_call_id="paused-action-dashboard",
    )
    prepared = create_dashboard_tool(
        w.results, w.analyses, w.runs, w.reports, w.dashboards, source_id="test"
    ).func(dashboard_json=current.spec.model_dump_json(), runtime=runtime)
    assert prepared["ok"], prepared
    runtime.tool_call_id = "paused-action-report"
    rendered = create_create_report_tool(
        w.results, w.analyses, w.runs, w.reports, source_id="test"
    ).func(report_json=w.report.spec.model_dump_json(), runtime=runtime)
    assert rendered["ok"], rendered
    manager = RunManager(
        conversations=w.conversations,
        runs=w.runs,
        results=w.results,
        analyses=w.analyses,
        reports=w.reports,
        dashboards=w.dashboards,
        agent=Graph(
            [Stream(CoordinatorResponse(answer="Already published findings."))]
        ),
    )
    await manager.stop(run_id)
    assert w.runs.get(run_id).status == RunStatus.PAUSED
    assert w.conversations.get(w.thread).active_run_id is None
    assert w.dashboards.action_for_run(run_id).status == "running"
    with pytest.raises(DashboardConflict, match="pending dashboard action"):
        w.service.edit_view(
            current.dashboard_id,
            w.thread,
            source_id="test",
            edit=DashboardViewEdit(
                expected_revision=current.revision_id,
                request_id="mutate-paused-view",
                title="Would invalidate the paused action",
            ),
        )
    assert (
        w.service.edit_view(current.dashboard_id, w.thread, source_id="test", edit=edit)
        == current
    )
    assert w.dashboards.get(current.dashboard_id, w.thread, source_id="test") == current

    w.conversations.begin_run(w.thread, run_id)
    await manager.resume(run_id)
    run = w.runs.get(run_id)
    assert run.status == RunStatus.COMPLETED, run.error
    revised = w.dashboards.get(current.dashboard_id, w.thread, source_id="test")
    assert revised.revision_id == prepared["revision_id"]
    assert revised.version == current.version + 1
    assert revised.spec == current.spec
    assert revised.report_id == run.answer.report.report_id
    assert w.dashboards.action_for_run(run_id).status == "completed"
