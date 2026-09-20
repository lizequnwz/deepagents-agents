"""Local file review, full-population checks and source-isolated analysis."""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import hashlib
import io
import json
import re

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from streamlit.testing.v1 import AppTest

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.uploads import (
    stage_upload,
    confirm_upload,
    get_upload,
    UploadReview,
)
from data_analytics_agent.ui.api_client import AgentAPIClient, APIError
from data_analytics_agent.agents.text_to_sql.tools import (
    create_query_saved_results_tool,
)
from tests.test_agent_workflow import AnalystModel
from data_analytics_agent.agents.data_analysis.tools import create_analysis_tools


def reviewed(services, content=b"id,amount\n001,2\n002,4\n003,6\n", **changes):
    upload = stage_upload(services, content, "sales.csv")
    review = UploadReview(
        types={c.name: c.suggested_type for c in upload.columns}, **changes
    )
    return confirm_upload(services, upload.thread_id, review)


def test_file_review_preserves_identifiers_dates_nulls_and_provenance(test_settings):
    s = Services(settings=test_settings)
    content = b'id,date,amount,code\n001,02/03/2026,1.25,NA\n002,03/04/2026,2.75,""\n003,04/05/2026,3.50,\n'
    u = stage_upload(s, content, "../../sales.csv")
    assert u.filename == "sales.csv" and not u.confirmed
    assert u.sha256 == hashlib.sha256(content).hexdigest()
    assert {c.name: c.suggested_type for c in u.columns}["date"] == "text"
    rows = s.results.get(u.result_id, u.thread_id).rows
    assert rows[0]["id"] == "001" and rows[0]["code"] == "NA"
    assert rows[1]["code"] == "" and rows[2]["code"] is None
    with pytest.raises(ValueError, match="Review the file"):
        s.require_ready_source(u.source_id)
    confirmed = confirm_upload(
        s,
        u.thread_id,
        UploadReview(
            types={
                "id": "text",
                "date": "date_dmy",
                "amount": "number",
                "code": "text",
            },
            grain="One sale",
            key_columns=["id"],
        ),
    )
    result = s.results.get(confirmed.result_id, u.thread_id)
    assert result.rows[0]["date"] == date(2026, 3, 2)
    assert result.rows[0]["id"] == "001" and result.rows[0]["amount"] == 1.25
    assert result.parent_result_ids == [u.original_result_id]
    assert result.upload_provenance.schema_reviewed
    assert result.upload_provenance.grain == "One sale"
    assert s.results.get(u.original_result_id, u.thread_id).rows == rows
    reopened = Services(settings=test_settings)
    assert get_upload(reopened.storage, u.source_id) == confirmed
    assert reopened.source_summary(u.source_id).ready
    assert confirm_upload(reopened, u.thread_id, confirmed.review) == confirmed
    with pytest.raises(ValueError, match="already confirmed"):
        confirm_upload(
            reopened,
            u.thread_id,
            UploadReview(types=confirmed.review.types, grain="Other"),
        )


def test_parquet_retains_decimal_timestamp_and_identifier_types(test_settings):
    table = pa.table(
        {
            "id": ["0007"],
            "amount": pa.array([Decimal("12.3400")], type=pa.decimal128(12, 4)),
            "at": [datetime(2026, 9, 19, tzinfo=timezone.utc)],
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    s = Services(settings=test_settings)
    upload = stage_upload(s, buf.getvalue(), "sales.parquet")
    result = confirm_upload(
        s,
        upload.thread_id,
        UploadReview(types={c.name: "original" for c in upload.columns}),
    )
    stored = pq.read_table(
        s.results.get(result.result_id, result.thread_id).parquet_path
    )
    assert stored.schema == table.schema
    assert stored.to_pylist() == table.to_pylist()


@pytest.mark.parametrize(
    "content,message",
    [
        (b"a,A\n1,2\n", "unique"),
        (b"a,b\n1,2,3\n", "could not be read"),
        (b"a\n", "at least one"),
        (b"a\n\xff\n", "UTF-8"),
    ],
)
def test_bad_files_do_not_create_conversations(test_settings, content, message):
    s = Services(settings=test_settings)
    with pytest.raises(ValueError, match=message):
        stage_upload(s, content, "bad.csv")
    assert not s.conversations.list()
    assert not s.storage.load("datasets", dict)


def test_limits_reject_full_upload_instead_of_saving_partial(test_settings):
    s = Services(
        settings=replace(test_settings, max_result_rows=2, upload_max_bytes=64)
    )
    with pytest.raises(ValueError, match="row or byte"):
        stage_upload(s, b"n\n1\n2\n3\n", "rows.csv")
    with pytest.raises(ValueError, match="UPLOAD_MAX_BYTES"):
        stage_upload(s, b"x" * 65, "large.csv")
    with TestClient(create_app(s)) as api:
        assert (
            api.post("/api/uploads?filename=large.csv", content=b"x" * 65).status_code
            == 413
        )
    assert not s.conversations.list()


def test_invalid_dates_and_duplicate_keys_use_complete_population(test_settings):
    s = Services(settings=test_settings)
    u = stage_upload(s, b"id,date\n1,2026-02-30\n", "bad-date.csv")
    with pytest.raises(ValueError, match="Invalid calendar"):
        confirm_upload(
            s, u.thread_id, UploadReview(types={"id": "text", "date": "date_iso"})
        )
    assert not get_upload(s.storage, u.source_id).confirmed
    content = "id,value\n" + "\n".join(f"{i},1" for i in range(15)) + "\n14,2\n"
    u = stage_upload(s, content.encode(), "duplicates.csv")
    with pytest.raises(ValueError, match="duplicated"):
        confirm_upload(
            s,
            u.thread_id,
            UploadReview(types={"id": "text", "value": "integer"}, key_columns=["id"]),
        )
    assert s.results.get(u.result_id, u.thread_id).row_count == 16
    assert not get_upload(s.storage, u.source_id).confirmed


def test_registry_optional_uploads_not_exposed_as_reusable_sources_and_deletion(
    test_settings,
):
    settings = replace(
        test_settings,
        data_sources_config_path=test_settings.project_root / "missing.yaml",
    )
    s = Services(settings=settings)
    with TestClient(create_app(s)) as api:
        assert api.get("/health").json()["status"] == "ok"
        listing = api.get("/api/data-sources").json()
        assert listing["sources"] == [] and listing["errors"]
        response = api.post(
            "/api/uploads?filename=sales.csv", content=b"id,amount\n001,2\n002,4\n"
        )
        assert response.status_code == 201, response.text
        u = response.json()
        assert "original_path" not in u and len(u["sample_rows"]) <= 10
        thread = u["thread_id"]
        assert (
            api.post(
                f"/api/conversations/{thread}/messages", json={"message": "Sum amount"}
            ).status_code
            == 503
        )
        assert (
            api.post(
                "/api/conversations", json={"source_id": u["source_id"]}
            ).status_code
            == 422
        )
        confirmed = api.post(
            f"/api/conversations/{thread}/upload/confirm",
            json={"types": {"id": "text", "amount": "integer"}},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert api.get("/api/data-sources").json()["sources"] == []
        assert api.get(f"/api/conversations/{thread}/source").json()["ready"]
        original_path = Path(get_upload(s.storage, u["source_id"]).original_path)
        assert original_path.exists()
        assert api.delete(f"/api/conversations/{thread}").status_code == 200
        assert not original_path.exists() and not s.storage.load("uploads", dict)
        assert not s.storage.load("datasets", dict)


def test_saved_data_queries_cannot_cross_upload_or_warehouse_scope(test_settings):
    s = Services(settings=test_settings)
    one, two = reviewed(s), reviewed(s)
    run = s.runs.create(one.thread_id, one.source_id, "Sum amount")
    runtime = SimpleNamespace(
        state={
            "thread_id": one.thread_id,
            "run_id": run,
            "source_id": one.source_id,
            "question": "Sum amount",
        },
        tool_call_id="sum",
    )
    tool = create_query_saved_results_tool(s.results, s.runs, source_id=one.source_id)
    result = tool.func(
        query="SELECT SUM(amount) AS total FROM uploaded",
        bindings={"uploaded": one.result_id},
        purpose="Sum",
        runtime=runtime,
    )
    assert s.results.get(result["result_id"], one.thread_id).rows == [{"total": 12}]
    runtime.tool_call_id = "foreign"
    with pytest.raises(KeyError):
        tool.func(
            query="SELECT SUM(amount) AS total FROM uploaded",
            bindings={"uploaded": two.result_id},
            purpose="Invalid",
            runtime=runtime,
        )
    with pytest.raises(ValueError, match="no warehouse"):
        s.backend_for_source(one.source_id)
    with pytest.raises(ValueError, match="not a curated"):
        s.semantic_catalog_for_source(one.source_id)


class UploadAnalyst(AnalystModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = " ".join(
            str(m.content) for m in messages if isinstance(m, SystemMessage)
        )
        tools = [m for m in messages if isinstance(m, ToolMessage)]

        def call(name, args, ident):
            return AIMessage(
                content="", tool_calls=[{"name": name, "args": args, "id": ident}]
            )

        if "You are the text-to-SQL specialist" in system:
            found = next((m for m in tools if m.name == "query_saved_results"), None)
            if not found:
                source = re.search(r'"saved_result_id": "([a-f0-9-]+)"', system).group(
                    1
                )
                message = call(
                    "query_saved_results",
                    {
                        "query": "SELECT SUM(amount) AS total FROM uploaded",
                        "bindings": {"uploaded": source},
                        "purpose": "Sum reviewed amounts",
                    },
                    "sum-upload",
                )
            else:
                payload = json.loads(found.content)
                message = call(
                    "SQLAnalysisResponse",
                    {"answer": "The total is 12.", "result_id": payload["result_id"]},
                    "sql-answer",
                )
        else:
            task = next((m for m in tools if m.name == "task"), None)
            if not task:
                message = call(
                    "task",
                    {
                        "description": "Sum all amounts in the reviewed uploaded file.",
                        "subagent_type": "text-to-sql",
                    },
                    "retrieve-upload",
                )
            else:
                result = re.search(
                    r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", str(task.content)
                ).group()
                findings = {
                    "answer": "The total is 12.",
                    "primary_result_id": result,
                    "supporting_result_ids": [result],
                }
                if not any(m.name == "publish_findings" for m in tools):
                    message = call(
                        "publish_findings", {"findings": findings}, "publish"
                    )
                elif not any(m.name == "create_report" for m in tools):
                    message = call(
                        "create_report",
                        {
                            "report_json": json.dumps(
                                {
                                    "title": "Uploaded sales",
                                    "blocks": [
                                        {
                                            "type": "metrics",
                                            "metrics": [
                                                {
                                                    "label": "Total amount",
                                                    "result_id": result,
                                                    "column": "total",
                                                }
                                            ],
                                        }
                                    ],
                                }
                            )
                        },
                        "report",
                    )
                else:
                    assert json.loads(
                        next(m.content for m in tools if m.name == "create_report")
                    )["ok"]
                    message = call("CoordinatorResponse", findings, "final-answer")
        return ChatResult(generations=[ChatGeneration(message=message)])


class RecoveringUploadAnalyst(UploadAnalyst):
    """Reproduce a dropped character in publication, then follow recovery feedback."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = " ".join(
            str(m.content) for m in messages if isinstance(m, SystemMessage)
        )
        outputs = [m for m in messages if isinstance(m, ToolMessage)]
        task = next((m for m in outputs if m.name == "task"), None)
        if "You are the text-to-SQL specialist" not in system and task:
            publications = [m for m in outputs if m.name == "publish_findings"]
            call = None
            if not publications:
                result = re.search(
                    r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", str(task.content)
                ).group()
                call = (
                    "publish_findings",
                    {
                        "findings": {
                            "answer": "The total is 12.",
                            "primary_result_id": result[:-1],
                        }
                    },
                    "typo",
                )
            elif publications[-1].status == "error":
                if outputs[-1].name == "list_conversation_results":
                    results = json.loads(outputs[-1].content)["results"]
                    result = next(
                        r["result_id"] for r in results if r["kind"] == "saved_sql"
                    )
                    call = (
                        "publish_findings",
                        {
                            "findings": {
                                "answer": "The total is 12.",
                                "primary_result_id": result,
                            }
                        },
                        "corrected-id",
                    )
                else:
                    assert "list_conversation_results" in publications[-1].content
                    call = ("list_conversation_results", {}, "recover-id")
            if call:
                name, args, ident = call
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=AIMessage(
                                content="",
                                tool_calls=[{"name": name, "args": args, "id": ident}],
                            )
                        )
                    ]
                )
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.parametrize(
    "model_type,require_review",
    [(UploadAnalyst, False), (UploadAnalyst, True), (RecoveringUploadAnalyst, False)],
)
async def test_uploaded_file_through_real_agent_harness_and_report(
    test_settings, monkeypatch, require_review, model_type
):
    import shutil
    from data_analytics_agent import coordinator

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setattr(
        coordinator, "_build_chat_model", lambda *args, **kwargs: model_type()
    )
    root = Path(__file__).parents[1]
    shutil.copy(root / "AGENTS.md", test_settings.project_root / "AGENTS.md")
    shutil.copytree(root / "skills", test_settings.project_root / "skills")
    s = Services(
        settings=replace(
            test_settings,
            require_sql_approval=require_review,
            require_python_approval=False,
        )
    )
    upload = reviewed(s)

    def forbidden(*args):
        raise AssertionError(
            "Upload analysis must not touch a warehouse or curated catalog"
        )

    monkeypatch.setattr(s, "backend_for_source", forbidden)
    monkeypatch.setattr(s, "semantic_catalog_for_source", forbidden)
    run = s.runs.create(upload.thread_id, upload.source_id, "Sum all amounts")
    s.conversations.begin_run(upload.thread_id, run)
    await s.manager().start(run)
    if require_review:
        from data_analytics_agent.approvals import decisions_to_command
        from data_analytics_agent.schemas import Decision

        paused = s.runs.get(run)
        assert paused.status == "approval_required", paused.error
        assert paused.approval.action_name == "query_saved_results"
        assert not any(
            r.kind == "saved_sql"
            for r in s.results.list_for_conversation(
                upload.thread_id, source_id=upload.source_id
            )
        )
        command = decisions_to_command(paused.approval, [Decision(action="approve")])
        s.runs.claim_approval(run, paused.approval)
        await s.manager().resume(run, command)
    state = s.runs.get(run)
    assert state.status == "completed", state.error
    assert state.answer.answer == "The total is 12."
    assert state.answer.report and state.findings
    html = Path(
        s.reports.get(state.answer.report.report_id, upload.thread_id).html_path
    ).read_text()
    assert upload.sha256 in html and "Uploaded evidence" in html
    assert "Source freshness is unknown" in html
    result = s.results.get(state.answer.primary_result_id, upload.thread_id)
    assert result.rows == [{"total": 12}] and result.parent_result_ids == [
        upload.result_id
    ]
    assert s.reports.get(
        state.answer.report.report_id, upload.thread_id
    ).input_result_ids == [
        result.result_id,
        upload.result_id,
        upload.original_result_id,
    ]
    calls = {e.tool.name for e in state.events if e.tool}
    assert "query_saved_results" in calls and "execute_sql" not in calls
    assert state.run_diagnostics.model_calls > 0
    if model_type is RecoveringUploadAnalyst:
        assert "list_conversation_results" in calls
        assert (
            len(
                [
                    r
                    for r in s.results.list_for_conversation(
                        upload.thread_id, source_id=upload.source_id
                    )
                    if r.kind == "saved_sql"
                ]
            )
            == 1
        )


def test_upload_ui_review_and_reopen_without_configured_sources(
    test_settings, monkeypatch
):
    s = Services(
        settings=replace(
            test_settings,
            data_sources_config_path=test_settings.project_root / "missing.yaml",
        )
    )
    upload = stage_upload(s, b"id,amount\n001,2\n002,4\n", "sales.csv")
    with TestClient(create_app(s)) as api:

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise APIError(
                    str(response.json().get("detail")), status_code=response.status_code
                )
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        app.run(timeout=15)
        assert not app.exception
        assert not app.chat_input
        app.query_params["thread_id"] = upload.thread_id
        app.run(timeout=15)
        assert not app.exception
        assert not app.chat_input
        next(
            b for b in app.button if b.label == "Confirm schema and start conversation"
        ).click().run(timeout=15)
        assert not app.exception
        assert len(app.chat_input) == 1
        assert get_upload(s.storage, upload.source_id).confirmed


def test_upload_api_serializes_decimal_dates_and_nonfinite_preview(test_settings):
    table = pa.table(
        {
            "amount": pa.array(
                [Decimal("123456789.123456789")], type=pa.decimal128(20, 9)
            ),
            "date": [date(2026, 9, 19)],
            "missing": [float("nan")],
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    s = Services(settings=test_settings)
    with TestClient(create_app(s)) as api:
        response = api.post(
            "/api/uploads?filename=typed.parquet", content=buf.getvalue()
        )
        assert response.status_code == 201, response.text
        assert response.json()["sample_rows"] == [
            {"amount": "123456789.123456789", "date": "2026-09-19", "missing": None}
        ]


def test_upload_blocks_deletion_and_duplicate_confirmation_during_review(
    test_settings, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from data_analytics_agent import api as api_module

    s = Services(settings=test_settings)
    upload = stage_upload(s, b"n\n1\n2\n", "numbers.csv")
    started, release = Event(), Event()

    def slow_review(*args):
        started.set()
        assert release.wait(10)
        return confirm_upload(*args)

    monkeypatch.setattr(api_module, "confirm_upload", slow_review)
    with TestClient(create_app(s)) as api, ThreadPoolExecutor() as executor:
        path = f"/api/conversations/{upload.thread_id}/upload/confirm"
        work = executor.submit(api.post, path, json={"types": {"n": "integer"}})
        try:
            assert started.wait(5)
            assert (
                api.delete(f"/api/conversations/{upload.thread_id}").status_code == 409
            )
            assert api.delete("/api/conversations").status_code == 409
            assert api.post(path, json={"types": {"n": "integer"}}).status_code == 409
        finally:
            release.set()
        assert work.result().status_code == 200
        assert not s.uploading_conversations
        assert api.delete(f"/api/conversations/{upload.thread_id}").status_code == 200


def test_failed_original_write_rolls_back_new_workspace(test_settings, monkeypatch):
    s = Services(settings=test_settings)

    def fail(*args):
        raise OSError("Disk full")

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(OSError, match="Disk full"):
        stage_upload(s, b"n\n1\n", "numbers.csv")
    assert not s.conversations.list()
    assert not s.uploading_conversations
    assert not s.storage.load("uploads", dict)


def test_python_reuses_uploaded_evidence_and_preserves_lineage(test_settings):
    s = Services(settings=test_settings)
    upload = reviewed(s)
    run = s.runs.create(upload.thread_id, upload.source_id, "Analyze amounts")
    runtime = SimpleNamespace(
        state={
            "thread_id": upload.thread_id,
            "run_id": run,
            "source_id": upload.source_id,
            "question": "Analyze amounts",
        },
        tool_call_id="python-upload",
    )
    execute, _ = create_analysis_tools(
        s.results,
        s.runs,
        s.analyses,
        source_id=upload.source_id,
        limits=s.settings.python_execution_limits(),
    )
    step = execute.func(
        inputs={"sales": upload.result_id},
        code="analysis_outputs={'mean': datasets['sales']['amount'].mean()}; output_datasets={'copy':datasets['sales'].copy()}",
        runtime=runtime,
    )
    assert step["ok"], step
    derived = s.results.get(
        step["output_datasets"]["copy"], upload.thread_id, source_id=upload.source_id
    )
    assert derived.row_count == 3 and not derived.truncated
    assert derived.parent_result_ids == [upload.result_id]
    assert derived.rows[0]["id"] == "001"
