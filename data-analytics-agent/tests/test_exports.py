"""Portable replay agrees with typed saved evidence, without a source or model."""

from datetime import date
from decimal import Decimal
from io import BytesIO
import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import nbformat
from nbclient import NotebookClient
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.exports import write_bundle, ExportConflict
from data_analytics_agent.agents.data_analysis.tools import create_analysis_tools
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import ChatTurn, FinalAnswer, ResultReference
from data_analytics_agent.uploads import stage_upload, confirm_upload, UploadReview


def complete(s, thread, run, results, analysis=None, partial=False):
    answer = FinalAnswer(
        answer="The complete snapshot has total 24.6800."
        if analysis
        else "Saved snapshot.",
        primary_result_id=results[-1].result_id,
        results=[
            ResultReference(
                result_id=r.result_id,
                executed_sql=r.executed_sql,
                originating_question=r.originating_question,
                short_label=r.short_label,
            )
            for r in results
        ],
        analyses=[analysis] if analysis else [],
        partial=partial,
        unresolved_questions=["Source completeness is unknown."] if partial else [],
    )
    report = generate_report(
        ReportSpec(
            title="Portable analysis",
            blocks=[{"type": "narrative", "body": answer.answer}],
        ),
        thread_id=thread,
        source_id=s.conversations.get(thread).source_id,
        result_store=s.results,
        analysis_store=s.analyses,
        run_store=s.runs,
        report_store=s.reports,
        findings=answer,
    )
    answer = answer.model_copy(update={"report": report.reference()})
    s.runs.publish(run, answer)
    s.runs.attach_report(run, report.reference())
    s.runs.complete(run, answer)
    s.conversations.complete_run(
        thread, run, ChatTurn(run_id=run, user_message="Analyze data", answer=answer)
    )
    return answer


@pytest.fixture
def analytical_bundle(test_settings, tmp_path):
    s = Services(settings=test_settings)
    table = pa.table(
        {
            "id": ["0007", "0008"],
            "date": [date(2026, 9, 1), date(2026, 9, 2)],
            "amount": pa.array(
                [Decimal("12.3400"), Decimal("0.0000")], type=pa.decimal128(12, 4)
            ),
        }
    )
    buffer = BytesIO()
    pq.write_table(table, buffer)
    upload = stage_upload(s, buffer.getvalue(), "sales.parquet")
    upload = confirm_upload(
        s,
        upload.thread_id,
        UploadReview(types={c.name: "original" for c in upload.columns}),
    )
    thread = upload.thread_id
    run = s.runs.create(thread, upload.source_id, "Analyze amounts")
    s.conversations.begin_run(thread, run)
    s.runs.begin_assignment(run, "analysis", "data-analysis", "Analyze amounts")

    def runtime(call):
        return SimpleNamespace(
            state={
                "thread_id": thread,
                "run_id": run,
                "source_id": upload.source_id,
                "assignment_id": "analysis",
                "question": "Analyze amounts",
            },
            tool_call_id=call,
        )

    execute, finish = create_analysis_tools(
        s.results,
        s.runs,
        s.analyses,
        source_id=upload.source_id,
        limits=s.settings.python_execution_limits(),
    )
    first = execute.func(
        inputs={"sales": upload.result_id},
        code="""import matplotlib.pyplot as plt
leaked = 123
frame = datasets['sales'].copy()
frame['amount'] = frame['amount'] * 2
output_datasets = {'doubled': frame}
fig, ax = plt.subplots()
ax.plot([1,2],[float(x) for x in frame['amount']])
ax.set_title('Doubled amounts')
analysis_outputs = {'total': str(frame['amount'].sum()), 'figure': fig}
""",
        runtime=runtime("first"),
    )
    assert first["ok"], first
    second = execute.func(
        inputs={
            "original": upload.result_id,
            "doubled": first["output_datasets"]["doubled"],
        },
        code="""assert 'leaked' not in globals()
combined = datasets['doubled'].copy()
analysis_outputs = {'ratio': 2.0, 'rows': len(combined)}
output_datasets = {'final': combined}
""",
        runtime=runtime("second"),
    )
    assert second["ok"], second
    failed = execute.func(
        inputs={"original": upload.result_id},
        code="raise ValueError('discarded attempt')",
        runtime=runtime("failed"),
    )
    assert not failed["ok"]
    end = finish.func(
        outcome="analysis_completed",
        answer="Doubled total is 24.6800.",
        method="Multiply each complete snapshot amount by two.",
        runtime=runtime("finish"),
    )
    analysis = s.analyses.get(end["analysis_id"], thread).analysis
    final = s.results.get(second["output_datasets"]["final"], thread)
    assert sum(row["amount"] for row in final.rows) == Decimal("24.6800")
    answer = complete(s, thread, run, [final], analysis)
    unrelated = s.results.save(
        columns=["secret"],
        rows=[{"secret": "UNRELATED"}],
        thread_id=thread,
        source_id=upload.source_id,
    )
    target = tmp_path / "analysis.zip"
    write_bundle(s, run, answer.report.report_id, target)
    moved = tmp_path / "moved elsewhere"
    moved.mkdir()
    with ZipFile(target) as zip:
        zip.extractall(moved)
    return SimpleNamespace(
        s=s,
        run=run,
        thread=thread,
        answer=answer,
        final=final,
        unrelated=unrelated,
        folder=moved,
        target=target,
    )


def test_bundle_replays_exact_steps_and_scoped_typed_outputs(analytical_bundle):
    w = analytical_bundle
    manifest = json.loads((w.folder / "manifest.json").read_text())
    assert len(manifest["steps"]) == 2
    assert w.unrelated.result_id not in manifest["datasets"]
    assert all("parquet_path" not in d for d in manifest["datasets"].values())
    assert str(w.s.storage.root) not in (w.folder / "manifest.json").read_text()
    assert (
        "discarded attempt"
        not in (w.folder / manifest["steps"][0]["code_path"]).read_text()
    )
    assert manifest["runtime"]["pandas"]
    assert json.loads((w.folder / "sql-provenance.json").read_text()) == []
    assert "No SQL queries were recorded" in (w.folder / "README.md").read_text()
    result = subprocess.run(
        [sys.executable, str(w.folder / "analysis.py")],
        cwd="/tmp",
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    replayed = pq.read_table(w.folder / "replayed" / f"{w.final.result_id}.parquet")
    assert replayed.to_pylist() == pq.read_table(w.final.parquet_path).to_pylist()
    assert replayed["id"].to_pylist() == ["0007", "0008"]
    assert replayed["date"].to_pylist() == [date(2026, 9, 1), date(2026, 9, 2)]
    assert list((w.folder / "replayed").glob("*.png"))


def test_notebook_keeps_code_figures_and_executes_fresh_kernel(analytical_bundle):
    w = analytical_bundle
    notebook = nbformat.read(w.folder / "analysis.ipynb", as_version=4)
    nbformat.validate(notebook)
    assert any(
        "%%writefile" in c.source and "leaked = 123" in c.source for c in notebook.cells
    )
    assert any(
        "image/png" in o.get("data", {})
        for c in notebook.cells
        if c.cell_type == "code"
        for o in c.outputs
    )
    NotebookClient(
        notebook,
        timeout=90,
        kernel_name="python3",
        resources={"metadata": {"path": str(w.folder)}},
    ).execute()
    assert not any(
        o.output_type == "error"
        for c in notebook.cells
        if c.cell_type == "code"
        for o in c.outputs
    )
    assert any(
        "image/png" in o.get("data", {})
        for c in notebook.cells
        if c.cell_type == "code"
        for o in c.outputs
    )
    nbformat.write(notebook, w.folder / "analysis.ipynb")
    saved = nbformat.read(w.folder / "analysis.ipynb", as_version=4)
    NotebookClient(
        saved,
        timeout=90,
        kernel_name="python3",
        resources={"metadata": {"path": str(w.folder)}},
    ).execute()


def test_download_after_restart_and_exact_presentation(analytical_bundle):
    w = analytical_bundle
    # Export is independent of provider/model construction and source readiness.
    s = Services(settings=w.s.settings)
    with TestClient(create_app(s)) as api:
        response = api.get(
            f"/api/runs/{w.run}/download",
            params={"report_id": w.answer.report.report_id},
        )
        assert response.status_code == 200, response.text
        with ZipFile(BytesIO(response.content)) as zip:
            assert (
                zip.read("report.html").decode()
                == s.reports.get(w.answer.report.report_id, w.thread).html
            )
        assert (
            api.get(
                f"/api/runs/{w.run}/download", params={"report_id": "stale"}
            ).status_code
            == 409
        )


@pytest.mark.parametrize("partial", [False, True])
def test_sql_only_snapshot_export_labels_incomplete_and_replays(
    test_settings, tmp_path, partial
):
    s = Services(settings=test_settings)
    thread = s.conversations.create("test")
    run = s.runs.create(thread, "test", "Show total")
    s.conversations.begin_run(thread, run)
    executed_sql = "-- Reviewed total: café\nSELECT SUM(amount) AS total FROM sales\n\n"
    result = s.results.save(
        columns=["total"],
        rows=[{"total": 10}],
        thread_id=thread,
        source_id="test",
        executed_sql=executed_sql,
        truncated=partial,
    )
    answer = complete(s, thread, run, [result], partial=partial)
    target = tmp_path / "sql.zip"
    write_bundle(s, run, answer.report.report_id, target)
    folder = tmp_path / "sql"
    folder.mkdir()
    with ZipFile(target) as zip:
        zip.extractall(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["population_complete"] is not partial
    assert manifest["partial"] is partial
    assert not manifest["steps"]
    queries = json.loads((folder / "sql-provenance.json").read_text())
    assert len(queries) == 1
    query = queries[0]
    assert query["result_id"] == result.result_id
    assert (folder / query["path"]).read_bytes() == executed_sql.encode("utf-8")
    assert (
        manifest["files"][query["path"]]
        == hashlib.sha256(executed_sql.encode("utf-8")).hexdigest()
    )
    assert f"]({query['path']})" in (folder / "README.md").read_text()
    result = subprocess.run(
        [sys.executable, str(folder / "analysis.py")], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    notebook = nbformat.read(folder / "analysis.ipynb", as_version=4)
    nbformat.validate(notebook)
    assert any(c.get("outputs") for c in notebook.cells)


def test_download_includes_reused_sql_lineage_without_chart_copies_or_other_queries(
    test_settings, monkeypatch
):
    from data_analytics_agent import coordinator

    s = Services(settings=test_settings)
    thread = s.conversations.create("test")
    prior_run = s.runs.create(thread, "test", "List artists")
    s.conversations.begin_run(thread, prior_run)
    source = s.results.save(
        columns=["Name"],
        rows=[{"Name": "Café ensemble"}],
        thread_id=thread,
        source_id="test",
        executed_sql='-- Exact reviewed SQL\nSELECT "Name" FROM "Artist"\n',
        purpose="Artists from the source",
        originating_question="List artists",
    )
    complete(s, thread, prior_run, [source])
    run = s.runs.create(thread, "test", "Use the saved artist list")
    s.conversations.begin_run(thread, run)
    shaped = s.results.save(
        columns=["Name"],
        rows=source.rows,
        thread_id=thread,
        source_id="test",
        executed_sql='SELECT "Name" FROM saved_artists WHERE "Name" IS NOT NULL\n',
        kind="saved_sql",
        parent_result_ids=[source.result_id],
        purpose="Artists from the saved snapshot",
        originating_question="Use the saved artist list",
    )
    chart_data = s.results.save(
        columns=["Name"],
        rows=shaped.rows,
        thread_id=thread,
        source_id="test",
        executed_sql=shaped.executed_sql,
        kind="presentation",
        parent_result_ids=[shaped.result_id],
    )
    unrelated = s.results.save(
        columns=["Name"],
        rows=[{"Name": "Other"}],
        thread_id=thread,
        source_id="test",
        executed_sql="SELECT Name FROM Unrelated",
    )
    answer = complete(s, thread, run, [chart_data])

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "SQL downloads use saved evidence without source/model calls"
        )

    monkeypatch.setattr(s, "backend_for_source", forbidden)
    monkeypatch.setattr(coordinator, "_build_chat_model", forbidden)
    with TestClient(create_app(s)) as api:
        response = api.get(
            f"/api/runs/{run}/download",
            params={"report_id": answer.report.report_id},
        )
        assert response.status_code == 200, response.text
        with ZipFile(BytesIO(response.content)) as bundle:
            index = json.loads(bundle.read("sql-provenance.json"))
            manifest = json.loads(bundle.read("manifest.json"))
            assert [q["result_id"] for q in index] == [
                source.result_id,
                shaped.result_id,
            ]
            assert [q["kind"] for q in index] == ["source_sql", "saved_sql"]
            assert [q["parent_result_ids"] for q in index] == [[], [source.result_id]]
            assert [q["question"] for q in index] == [
                "List artists",
                "Use the saved artist list",
            ]
            assert [q["label"] for q in index] == [
                source.short_label,
                shaped.short_label,
            ]
            assert set(n for n in bundle.namelist() if n.endswith(".sql")) == {
                q["path"] for q in index
            }
            for query, saved in zip(index, [source, shaped], strict=True):
                content = saved.executed_sql.encode("utf-8")
                assert bundle.read(query["path"]) == content
                assert (
                    query["snapshot_path"]
                    == manifest["datasets"][saved.result_id]["path"]
                )
                assert query["snapshot_path"] in bundle.namelist()
                assert (
                    manifest["files"][query["path"]]
                    == hashlib.sha256(content).hexdigest()
                )
            assert unrelated.result_id not in manifest["datasets"]


def test_unfinished_turn_has_no_download(test_settings, tmp_path):
    s = Services(settings=test_settings)
    thread = s.conversations.create("test")
    run = s.runs.create(thread, "test", "Unfinished")
    with pytest.raises(ExportConflict, match="Complete"):
        write_bundle(s, run, "missing", tmp_path / "unfinished.zip")


def test_reused_python_dataset_exports_its_prior_producer(analytical_bundle, tmp_path):
    w = analytical_bundle
    s = w.s
    run = s.runs.create(
        w.thread, s.conversations.get(w.thread).source_id, "Reuse final"
    )
    s.conversations.begin_run(w.thread, run)
    answer = complete(s, w.thread, run, [w.final])
    target = tmp_path / "reused.zip"
    write_bundle(s, run, answer.report.report_id, target)
    with ZipFile(target) as zip:
        manifest = json.loads(zip.read("manifest.json"))
        assert len(manifest["steps"]) == 2
        assert w.final.result_id in manifest["datasets"]


def test_download_uses_latest_report_revision(analytical_bundle):
    from data_analytics_agent.presentation_edits import (
        edit_report_title,
        ReportTitleEdit,
    )

    w = analytical_bundle
    answer = edit_report_title(
        w.s,
        w.run,
        ReportTitleEdit(
            report_id=w.answer.report.report_id, title="Updated export title"
        ),
    )
    with TestClient(create_app(w.s)) as api:
        assert (
            api.get(
                f"/api/runs/{w.run}/download",
                params={"report_id": w.answer.report.report_id},
            ).status_code
            == 409
        )
        response = api.get(
            f"/api/runs/{w.run}/download", params={"report_id": answer.report.report_id}
        )
        assert response.status_code == 200
        with ZipFile(BytesIO(response.content)) as zip:
            assert "Updated export title" in zip.read("README.md").decode()
            assert "Updated export title" in zip.read("report.html").decode()


def test_evidence_hash_check_rejects_changed_snapshot(analytical_bundle):
    w = analytical_bundle
    manifest = json.loads((w.folder / "manifest.json").read_text())
    (w.folder / manifest["datasets"][w.final.result_id]["path"]).write_bytes(b"changed")
    result = subprocess.run(
        [sys.executable, str(w.folder / "analysis.py")], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "Bundle file changed" in result.stderr
