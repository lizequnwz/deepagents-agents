from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.checkpoint.base import empty_checkpoint

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.agents.data_analysis.schemas import (
    DataAnalysisResult,
    PythonExecutionResult,
    AnalysisOutput,
)
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.schemas import ApprovalRequest, RunStatus
from tests.test_persistent_analyst import save


def test_delete_history_removes_artifacts_checkpoints_and_preserves_other_conversations(
    workspace, test_settings
):
    w = workspace
    result = save(w, [{"revenue": 12}])
    image = w.storage.artifacts / "diagnostic.png"
    image.write_bytes(b"test figure")
    execution = PythonExecutionResult(
        execution_id="python-step",
        inputs={"sales": result.result_id},
        executed_python="analysis_outputs={'value':12}",
        attempt=1,
        outputs=[
            AnalysisOutput(
                name="figure",
                kind="figure",
                image_path=str(image),
                media_type="image/png",
            )
        ],
    )
    w.runs.record_python_execution(w.run, execution)
    analysis = w.analyses.save(
        thread_id=w.thread,
        source_id="test",
        analysis=DataAnalysisResult(
            outcome="analysis_completed",
            input_result_ids=[result.result_id],
            executions=[execution],
            answer="12",
        ),
    )
    report = w.reports.save(
        thread_id=w.thread,
        source_id="test",
        spec=ReportSpec(
            title="Saved result", blocks=[{"type": "narrative", "body": "12"}]
        ),
        html="<html>12</html>",
        input_result_ids=[result.result_id],
        input_analysis_ids=[analysis.analysis_id],
    )
    w.runs.add_chart(w.run, {"chart_id": "chart", "result_id": result.result_id})
    w.conversations.save_investigation(w.thread, {"objective": "saved"})
    w.storage.commit(w.run, "call", '{"ok":true}')
    w.runs.require_approval(
        w.run,
        ApprovalRequest(
            interrupt_id="pending",
            action_name="execute_sql",
            query="SELECT 1",
            allowed_decisions=["approve"],
        ),
    )
    other = w.conversations.create("test")
    other_run = w.runs.create(other, "test", "Keep me")
    w.conversations.begin_run(other, other_run)
    w.runs.pause(other_run)
    w.conversations.fail_run(other, other_run)
    kept = w.results.save(
        thread_id=other, source_id="test", columns=["x"], rows=[{"x": 9}]
    )
    services = Services(settings=test_settings, storage=w.storage)
    with TestClient(create_app(services)) as api:

        async def checkpoints():
            for key in [w.run, other_run]:
                config = {"configurable": {"thread_id": key, "checkpoint_ns": ""}}
                saved = await services.checkpointer.aput(
                    config, empty_checkpoint(), {}, {}
                )
                await services.checkpointer.aput_writes(
                    saved, [("test", "saved")], "task"
                )

        api.portal.call(checkpoints)
        assert api.delete(f"/api/conversations/{w.thread}").json() == {
            "deleted_conversations": 1
        }
        for path in [
            f"/api/conversations/{w.thread}",
            f"/api/runs/{w.run}",
            f"/api/results/{result.result_id}",
        ]:
            assert api.get(path).status_code == 404
        assert api.get(f"/api/conversations/{other}").status_code == 200
        assert services.results.get_unscoped(kept.result_id).rows == [{"x": 9}]
        assert (
            not Path(result.parquet_path).exists()
            and not image.exists()
            and not Path(report.html_path).exists()
        )
        assert w.storage.committed(w.run, "call") is None
        with w.storage.connect() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM metadata WHERE kind IN ('analyses','reports','investigations')"
                ).fetchone()[0]
                == 0
            )

        async def verify():
            assert (
                await services.checkpointer.aget_tuple(
                    {"configurable": {"thread_id": w.run}}
                )
                is None
            )
            assert (
                await services.checkpointer.aget_tuple(
                    {"configurable": {"thread_id": other_run}}
                )
                is not None
            )
            async with services.checkpointer.conn.execute(
                "SELECT count(*) FROM writes WHERE thread_id=?", (w.run,)
            ) as cursor:
                assert (await cursor.fetchone())[0] == 0

        api.portal.call(verify)
        assert api.delete("/api/conversations").json() == {"deleted_conversations": 1}
        assert api.delete("/api/conversations").json() == {"deleted_conversations": 0}
        assert not Path(kept.parquet_path).exists()
    reopened = Services(settings=test_settings, storage=w.storage)
    assert reopened.conversations.list() == []
    with w.storage.connect() as db:
        assert db.execute("SELECT count(*) FROM metadata").fetchone()[0] == 0


def test_clear_all_refuses_active_work_without_partial_deletion(test_settings):
    services = Services(settings=test_settings)
    with TestClient(create_app(services)) as api:
        first = services.conversations.create("test")
        second = services.conversations.create("test")
        run = services.runs.create(second, "test", "Active")
        services.conversations.begin_run(second, run)
        for state in [RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.STOPPING]:
            services.runs.set_status(run, state)
            assert api.delete("/api/conversations").status_code == 409
            assert services.conversations.exists(
                first
            ) and services.conversations.exists(second)
        services.runs.pause(run)
        with services.runs.worker(run):
            assert api.delete("/api/conversations").status_code == 409
        assert api.delete("/api/conversations").json()["deleted_conversations"] == 2
        assert not services.conversations.exists(first)
        assert api.delete(f"/api/conversations/{first}").status_code == 404


def test_resume_cannot_race_checkpoint_deletion(test_settings, monkeypatch):
    import asyncio
    from data_analytics_agent.history import delete_history

    services = Services(settings=test_settings)
    thread = services.conversations.create("test")
    run = services.runs.create(thread, "test", "Paused work")
    services.conversations.begin_run(thread, run)
    services.runs.pause(run)
    services.conversations.fail_run(thread, run)
    with TestClient(create_app(services)) as api:
        entered, release = asyncio.Event(), asyncio.Event()
        original = services.checkpointer.adelete_thread

        async def delayed(key):
            entered.set()
            await release.wait()
            await original(key)

        monkeypatch.setattr(services.checkpointer, "adelete_thread", delayed)
        deletion = api.portal.start_task_soon(delete_history, services, {thread})
        api.portal.call(entered.wait)
        try:
            assert api.post(f"/api/runs/{run}/resume").status_code == 409
            assert api.delete(f"/api/conversations/{thread}").status_code == 409
        finally:
            api.portal.call(release.set)
        assert deletion.result(timeout=5) == {"deleted_conversations": 1}
