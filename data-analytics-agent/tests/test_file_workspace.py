"""Reviewed multi-table inputs and cited documents without warehouse access."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.documents import (
    create_document_tools,
    get_document,
    import_document_table,
    stage_document,
)
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import CoordinatorResponse
from data_analytics_agent.uploads import (
    confirm_upload,
    stage_upload,
    UploadReview,
    uploads_for_thread,
)
from data_analytics_agent.agents.text_to_sql.tools import (
    create_query_saved_results_tool,
)


def confirm(services, upload):
    return confirm_upload(
        services,
        upload.thread_id,
        UploadReview(types={c.name: c.suggested_type for c in upload.columns}),
        upload.upload_id,
    )


def test_several_reviewed_tables_reuse_one_scope_and_survive_restart(
    test_settings, monkeypatch
):
    services = Services(settings=test_settings)
    first = confirm(
        services, stage_upload(services, b"id,sales\n1,10\n2,20\n", "sales.csv")
    )
    version = services.source_version(first.source_id)
    second = stage_upload(
        services, b"id,returns\n1,2\n2,3\n", "returns.csv", thread_id=first.thread_id
    )
    assert second.source_id == first.source_id and second.upload_id != first.upload_id
    with pytest.raises(ValueError, match="Review the file"):
        services.require_ready_source(first.source_id)
    with pytest.raises(ValueError, match="Confirm the pending"):
        stage_upload(
            services, b"id,value\n1,3\n", "third.csv", thread_id=first.thread_id
        )
    second = confirm(services, second)
    assert services.source_version(first.source_id) != version
    reopened = Services(settings=test_settings)
    monkeypatch.setattr(
        reopened,
        "source_catalog",
        lambda: pytest.fail("file workspace accessed warehouse catalog"),
    )
    assert reopened.require_ready_source(first.source_id).backend_type == "upload"
    context = json.loads(reopened.source(first.source_id).context.split("\n", 1)[1])
    assert {table["saved_result_id"] for table in context["tables"]} == {
        first.result_id,
        second.result_id,
    }
    run = reopened.runs.create(
        first.thread_id, first.source_id, "Reconcile sales and returns"
    )
    runtime = SimpleNamespace(
        state={
            "thread_id": first.thread_id,
            "source_id": first.source_id,
            "run_id": run,
            "question": "Reconcile",
        },
        tool_call_id="join",
    )
    query = create_query_saved_results_tool(
        reopened.results, reopened.runs, source_id=first.source_id
    )
    result = query.func(
        bindings={"sales": first.result_id, "returns": second.result_id},
        query="SELECT s.id, s.sales-r.returns AS net FROM sales s JOIN returns r ON s.id=r.id ORDER BY s.id",
        purpose="Net sales",
        runtime=runtime,
    )
    saved = reopened.results.get(
        result["result_id"], first.thread_id, source_id=first.source_id
    )
    assert saved.rows == [{"id": "1", "net": 8}, {"id": "2", "net": 17}]
    assert set(saved.parent_result_ids) == {first.result_id, second.result_id}
    answer = resolve_answer(
        CoordinatorResponse(
            answer="Net sales is 25 source units", result_ids=[saved.result_id]
        ),
        thread_id=first.thread_id,
        source_id=first.source_id,
        results=reopened.results,
        analyses=reopened.analyses,
        runs=reopened.runs,
    )
    report = generate_report(
        ReportSpec(
            title="Net sales",
            blocks=[
                {"type": "table", "title": "Net sales", "result_id": saved.result_id}
            ],
        ),
        thread_id=first.thread_id,
        source_id=first.source_id,
        result_store=reopened.results,
        analysis_store=reopened.analyses,
        run_store=reopened.runs,
        report_store=reopened.reports,
        findings=answer,
    )
    assert "sales.csv" in report.html and "returns.csv" in report.html


def test_cross_conversation_upload_review_and_active_attachment_are_rejected(
    test_settings,
):
    services = Services(settings=test_settings)
    first = confirm(services, stage_upload(services, b"x\n1\n", "first.csv"))
    other = stage_upload(services, b"x\n2\n", "other.csv")
    with TestClient(create_app(services)) as client:
        response = client.post(
            f"/api/conversations/{first.thread_id}/uploads/{other.upload_id}/confirm",
            json={"types": {"x": "integer"}},
        )
        assert response.status_code == 404
    run = services.runs.create(first.thread_id, first.source_id, "Analyze")
    services.conversations.begin_run(first.thread_id, run)
    with pytest.raises(ValueError, match="Finish active work"):
        stage_upload(services, b"x\n2\n", "second.csv", thread_id=first.thread_id)
    assert len(uploads_for_thread(services, first.thread_id)) == 1


def test_upload_routes_select_exact_table_without_primary_alias(test_settings):
    services = Services(settings=test_settings)
    first = confirm(services, stage_upload(services, b"x\n1\n", "first.csv"))
    second = stage_upload(services, b"y\n2\n", "second.csv", thread_id=first.thread_id)
    other = stage_upload(services, b"z\n3\n", "other.csv")
    base = f"/api/conversations/{first.thread_id}"
    with TestClient(create_app(services)) as client:
        listed = client.get(f"{base}/uploads").json()["uploads"]
        assert {item["upload_id"] for item in listed} == {
            first.upload_id,
            second.upload_id,
        }
        exact = client.get(f"{base}/uploads/{second.upload_id}")
        assert exact.status_code == 200
        assert exact.json()["filename"] == "second.csv"
        assert not exact.json()["confirmed"]
        assert client.get(f"{base}/uploads/{other.upload_id}").status_code == 404
        assert client.get(f"{base}/upload").status_code == 404
        assert (
            client.post(
                f"{base}/upload/confirm", json={"types": {"x": "integer"}}
            ).status_code
            == 404
        )
        confirmed = client.post(
            f"{base}/uploads/{second.upload_id}/confirm",
            json={"types": {"y": "integer"}},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["upload_id"] == second.upload_id


def test_markdown_context_table_review_citations_and_deletion(
    test_settings, monkeypatch, tmp_path
):
    services = Services(settings=test_settings)
    content = b"# Results\nAmounts are in source units.\n\n| Year | Amount |\n| --- | --- |\n| 2024 | 100 |\n| 2025 | 120 |\n"
    doc = stage_document(services, content, "results.md")
    monkeypatch.setattr(
        services,
        "source_catalog",
        lambda: pytest.fail("document workspace accessed warehouse"),
    )
    assert services.source_summary(doc.source_id).ready
    tools = {
        tool.name: tool
        for tool in create_document_tools(services.storage, source_id=doc.source_id)
    }
    runtime = SimpleNamespace(
        state={
            "thread_id": doc.thread_id,
            "source_id": doc.source_id,
            "run_id": "unused",
            "question": "Read results",
        }
    )
    assert (
        tools["search_documents"].func(query="source units", runtime=runtime)[
            "matches"
        ][0]["page"]
        == 1
    )
    assert (
        len(
            tools["read_document"].func(document_id=doc.document_id, runtime=runtime)[
                "lines"
            ]
        )
        <= 10
    )
    with TestClient(create_app(services)) as client:
        inspected = client.get(
            f"/api/conversations/{doc.thread_id}/documents/{doc.document_id}"
        ).json()
        assert inspected["tables"][0]["row_count"] == 3
        imported = client.post(
            f"/api/conversations/{doc.thread_id}/documents/{doc.document_id}/tables",
            params={"table_index": 0},
        )
        assert imported.status_code == 201, imported.text
        table = imported.json()
        assert not table["confirmed"]
        reviewed = client.post(
            f"/api/conversations/{doc.thread_id}/uploads/{table['upload_id']}/confirm",
            json={
                "types": {"Year": "integer", "Amount": "integer"},
                "grain": "One year",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        result_id = reviewed.json()["result_id"]
        answer = resolve_answer(
            CoordinatorResponse(
                answer="The extracted figures are 100 and 120 source units",
                result_ids=[result_id],
            ),
            thread_id=doc.thread_id,
            source_id=doc.source_id,
            results=services.results,
            analyses=services.analyses,
            runs=services.runs,
        )
        assert answer.documents[0].sha256 == hashlib.sha256(content).hexdigest()
        result = services.results.get(result_id, doc.thread_id, source_id=doc.source_id)
        assert result.upload_provenance.document_reference["page"] == 1
        report = generate_report(
            ReportSpec(
                title="Annual figures",
                blocks=[
                    {
                        "type": "table",
                        "title": "Reviewed figures",
                        "result_id": result_id,
                    }
                ],
            ),
            thread_id=doc.thread_id,
            source_id=doc.source_id,
            result_store=services.results,
            analysis_store=services.analyses,
            run_store=services.runs,
            report_store=services.reports,
            findings=answer,
        )
        assert "Document sources" in report.html and "results.md" in report.html
        from data_analytics_agent.exports import write_bundle
        from data_analytics_agent.export_replay import load_manifest
        from data_analytics_agent.schemas import ChatTurn
        from zipfile import ZipFile

        answer = answer.model_copy(update={"report": report.reference()})
        run = services.runs.create(
            doc.thread_id, doc.source_id, "Summarize annual figures"
        )
        services.conversations.begin_run(doc.thread_id, run)
        services.runs.publish(run, answer)
        services.runs.attach_report(run, report.reference())
        services.runs.complete(run, answer)
        services.conversations.complete_run(
            doc.thread_id,
            run,
            ChatTurn(
                run_id=run, user_message="Summarize annual figures", answer=answer
            ),
        )
        target = tmp_path / "documents.zip"
        write_bundle(services, run, report.report_id, target)
        extracted = tmp_path / "exported documents"
        with ZipFile(target) as archive:
            archive.extractall(extracted)
        manifest = load_manifest(extracted)
        reference = manifest["documents"][0]
        assert (extracted / reference["path"]).read_bytes() == content
        assert json.loads((extracted / reference["extracted_path"]).read_text())[
            "tables"
        ][0]["rows"][-1] == ["2025", "120"]
        other = stage_document(services, b"Other context", "other.txt")
        assert (
            client.get(
                f"/api/conversations/{other.thread_id}/documents/{doc.document_id}"
            ).status_code
            == 404
        )
        assert client.delete(f"/api/conversations/{doc.thread_id}").status_code == 200
    assert (
        not Path(doc.original_path).exists() and not Path(doc.extracted_path).exists()
    )
    with pytest.raises(KeyError):
        get_document(services.storage, doc.document_id, doc.thread_id, doc.source_id)


def _pdf_table():
    commands = ["BT /F1 12 Tf 80 750 Td (Annual results - source units) Tj ET"]
    for y in [720, 680, 640, 600]:
        commands.append(f"70 {y} m 300 {y} l S")
    for x in [70, 200, 300]:
        commands.append(f"{x} 600 m {x} 720 l S")
    for y, left, right in [
        (695, "Year", "Revenue"),
        (655, "2024", "100"),
        (615, "2025", "120"),
    ]:
        commands.extend(
            [
                f"BT /F1 12 Tf 80 {y} Td ({left}) Tj ET",
                f"BT /F1 12 Tf 210 {y} Td ({right}) Tj ET",
            ]
        )
    stream = "\n".join(commands).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    pdf, offsets = b"%PDF-1.4\n", [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    return (
        pdf
        + f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )


def test_pdf_extracts_real_page_text_and_full_table(test_settings):
    services = Services(settings=test_settings)
    doc = stage_document(services, _pdf_table(), "annual.pdf")
    payload = json.loads(Path(doc.extracted_path).read_text())
    assert doc.page_count == 1 and doc.table_count == 1
    assert "Annual results" in payload["pages"][0]["text"]
    assert payload["tables"][0]["rows"] == [
        ["Year", "Revenue"],
        ["2024", "100"],
        ["2025", "120"],
    ]


def test_message_cannot_overlap_adding_a_table(test_settings, monkeypatch):
    from threading import Event, Thread

    services = Services(settings=test_settings, agent=object())
    first = confirm(services, stage_upload(services, b"x\n1\n", "first.csv"))
    entered, release = Event(), Event()
    save = services.results.save_batches

    def delayed_save(*args, **kwargs):
        if kwargs.get("purpose") == "Uploaded file: second.csv":
            entered.set()
            assert release.wait(10)
        return save(*args, **kwargs)

    monkeypatch.setattr(services.results, "save_batches", delayed_save)
    responses = []
    with TestClient(create_app(services)) as client:
        thread = Thread(
            target=lambda: responses.append(
                client.post(
                    "/api/uploads",
                    params={"filename": "second.csv", "thread_id": first.thread_id},
                    content=b"x\n2\n",
                )
            )
        )
        thread.start()
        try:
            assert entered.wait(10)
            response = client.post(
                f"/api/conversations/{first.thread_id}/messages",
                json={"message": "Explore all data"},
            )
            assert response.status_code == 409
            assert not services.conversations.get(first.thread_id).run_ids
        finally:
            release.set()
            thread.join(10)
        assert responses[0].status_code == 201


def test_failed_confirmation_discards_uncommitted_reviewed_dataset(
    test_settings, monkeypatch
):
    services = Services(settings=test_settings)
    upload = stage_upload(services, b"id,amount\n1,10\n", "sales.csv")
    original_paths = set(services.storage.artifacts.iterdir())
    put = services.storage.put

    def fail_review(kind, key, value, *args, **kwargs):
        if kind == "uploads" and value.confirmed:
            raise OSError("Failed review metadata commit")
        return put(kind, key, value, *args, **kwargs)

    monkeypatch.setattr(services.storage, "put", fail_review)
    with pytest.raises(OSError, match="review metadata"):
        confirm(services, upload)
    assert set(services.storage.artifacts.iterdir()) == original_paths
    assert services.results.list_for_conversation(
        upload.thread_id, source_id=upload.source_id
    ) == [
        services.results.get(
            upload.original_result_id, upload.thread_id, source_id=upload.source_id
        )
    ]
    monkeypatch.setattr(services.storage, "put", put)
    confirmed = confirm(services, upload)
    assert confirmed.confirmed
    assert (
        len(
            services.results.list_for_conversation(
                upload.thread_id, source_id=upload.source_id
            )
        )
        == 2
    )


def test_markdown_table_preserves_empty_cells_and_escaped_pipes(test_settings):
    services = Services(settings=test_settings)
    doc = stage_document(
        services,
        b"|Name|Amount|Note|\n|---|---|---|\n||10|a\\|b|\n|Beta|20||\n",
        "compact.md",
    )
    payload = json.loads(Path(doc.extracted_path).read_text())
    assert payload["tables"][0]["rows"] == [
        ["Name", "Amount", "Note"],
        ["", "10", "a|b"],
        ["Beta", "20", ""],
    ]
    upload = import_document_table(services, doc, 0)
    reviewed = confirm(services, upload)
    rows = services.results.get(
        reviewed.result_id, doc.thread_id, source_id=doc.source_id
    ).rows
    assert rows[0]["Amount"] == 10 and rows[0]["Note"] == "a|b"
    assert rows[0]["Name"] is None
    assert rows[1]["Name"] == "Beta" and rows[1]["Note"] is None


def test_long_document_filename_still_allows_reviewing_extracted_table(test_settings):
    services = Services(settings=test_settings)
    filename = "r" * 252 + ".md"
    doc = stage_document(services, b"|Year|Amount|\n|---|---|\n|2025|10|\n", filename)
    upload = import_document_table(services, doc, 0)
    assert len(upload.filename) <= 255
    assert upload.filename.endswith("-page-1-table-1.csv")
    result = services.results.get(
        upload.result_id, doc.thread_id, source_id=doc.source_id
    )
    assert result.upload_provenance.document_reference["filename"] == filename


def test_warehouse_document_table_import_preserves_context_without_adding_source(
    test_settings,
):
    services = Services(settings=test_settings)
    thread = services.conversations.create("warehouse")
    doc = stage_document(
        services,
        b"|Year|Amount|\n|---|---|\n|2025|10|\n",
        "context.md",
        thread_id=thread,
    )
    with TestClient(create_app(services)) as client:
        response = client.post(
            f"/api/conversations/{thread}/documents/{doc.document_id}/tables",
            params={"table_index": 0},
        )
        assert response.status_code == 422
        assert client.get(f"/api/conversations/{thread}/documents").json()[
            "documents"
        ] == [doc.reference()]
        assert (
            client.get(f"/api/conversations/{thread}/uploads").json()["uploads"] == []
        )
    assert services.conversations.get(thread).source_id == "warehouse"
    assert not services.results.list_for_conversation(thread, source_id="warehouse")


def test_resume_cannot_overlap_file_import_or_bypass_pending_review(
    test_settings, monkeypatch
):
    from threading import Event, Thread
    from unittest.mock import AsyncMock

    services = Services(settings=test_settings, agent=object())
    first = confirm(services, stage_upload(services, b"x\n1\n", "first.csv"))
    run = services.runs.create(first.thread_id, first.source_id, "Paused analysis")
    services.conversations.begin_run(first.thread_id, run)
    services.runs.pause(run)
    services.conversations.fail_run(first.thread_id, run)
    resumed = AsyncMock()
    monkeypatch.setattr(services.manager(), "resume", resumed)
    entered, release = Event(), Event()
    save = services.results.save_batches

    def delayed_save(*args, **kwargs):
        if kwargs.get("purpose") == "Uploaded file: second.csv":
            entered.set()
            assert release.wait(10)
        return save(*args, **kwargs)

    monkeypatch.setattr(services.results, "save_batches", delayed_save)
    responses = []
    with TestClient(create_app(services)) as client:
        worker = Thread(
            target=lambda: responses.append(
                client.post(
                    "/api/uploads",
                    params={"filename": "second.csv", "thread_id": first.thread_id},
                    content=b"y\n2\n",
                )
            )
        )
        worker.start()
        try:
            assert entered.wait(10)
            assert client.post(f"/api/runs/{run}/resume").status_code == 409
            resumed.assert_not_called()
            assert services.conversations.get(first.thread_id).active_run_id is None
        finally:
            release.set()
            worker.join(10)
        assert responses[0].status_code == 201
        assert client.post(f"/api/runs/{run}/resume").status_code == 409
        resumed.assert_not_called()
        reviewed = client.post(
            f"/api/conversations/{first.thread_id}/uploads/{responses[0].json()['upload_id']}/confirm",
            json={"types": {"y": "integer"}},
        )
        assert reviewed.status_code == 200
        assert client.post(f"/api/runs/{run}/resume").status_code == 202
        resumed.assert_awaited_once_with(run)
