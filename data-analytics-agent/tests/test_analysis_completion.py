"""Final evidence is distinct from retained analytical attempts."""

from zipfile import ZipFile

import pytest

from data_analytics_agent.agents.data_analysis.runner import PythonExecutionLimits
from data_analytics_agent.agents.data_analysis.tools import create_analysis_tools
from data_analytics_agent.api import Services
from data_analytics_agent.exports import write_bundle
from data_analytics_agent.export_replay import load_manifest
from data_analytics_agent.persistence import LocalStorage
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.schemas import CoordinatorResponse
from data_analytics_agent.stores import RunStore
from tests.test_exports import complete
from tests.test_persistent_analyst import save


def test_revised_evidence_excludes_superseded_attempt_from_report_and_replay(
    workspace, test_settings, tmp_path
):
    w = workspace
    source = save(w, [{"amount": 2}, {"amount": 4}])
    execute, finish = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    wrong = execute.func(
        inputs={"source": source.result_id},
        analysis_kind="general",
        code="analysis_outputs={'mean':987654321}; output_datasets={'wrong':datasets['source'].assign(amount=987654321)}",
        runtime=w.runtime("wrong"),
    )
    corrected = execute.func(
        inputs={"source": source.result_id},
        analysis_kind="general",
        code="analysis_outputs={'mean':float(datasets['source'].amount.mean())}; output_datasets={'final':datasets['source'].assign(centered=lambda d:d.amount-d.amount.mean())}",
        runtime=w.runtime("corrected"),
    )
    receipt = finish.func(
        outcome="analysis_completed",
        answer="The mean is 3 source units.",
        final_outputs={corrected["execution_id"]: ["mean"]},
        final_result_ids=[corrected["output_datasets"]["final"]],
        runtime=w.runtime("finish"),
    )
    assert "987654321" not in str(receipt)
    analysis = w.analyses.get(receipt["analysis_id"], w.thread).analysis
    assert len(analysis.executions) == 2
    assert analysis.executions[0].outputs[0].value == 987654321
    response = CoordinatorResponse(
        answer=receipt["answer"], analysis_ids=[receipt["analysis_id"]]
    )
    resolved = resolve_answer(
        response,
        thread_id=w.thread,
        source_id="test",
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
    )
    assert [r.result_id for r in resolved.results] == [
        corrected["output_datasets"]["final"]
    ]
    with pytest.raises(ValueError, match="superseded"):
        resolve_answer(
            response.model_copy(
                update={"result_ids": [wrong["output_datasets"]["wrong"]]}
            ),
            thread_id=w.thread,
            source_id="test",
            results=w.results,
            analyses=w.analyses,
            runs=w.runs,
        )
    services = Services(
        settings=test_settings,
        storage=w.storage,
        results=w.results,
        runs=w.runs,
        conversations=w.conversations,
        analyses=w.analyses,
        reports=w.reports,
    )
    final = w.results.get_unscoped(corrected["output_datasets"]["final"])
    services.conversations.begin_run(w.thread, w.run)
    answer = complete(services, w.thread, w.run, [final], analysis)
    report = w.reports.get(answer.report.report_id, w.thread)
    assert "987654321" not in report.html
    archive = tmp_path / "final.zip"
    write_bundle(services, w.run, report.report_id, archive)
    target = tmp_path / "moved"
    with ZipFile(archive) as bundle:
        bundle.extractall(target)
    manifest = load_manifest(target)
    assert len(manifest["steps"]) == 1
    assert manifest["steps"][0]["execution_id"] == corrected["execution_id"]
    assert wrong["output_datasets"]["wrong"] not in manifest["datasets"]
    assert manifest["selected_result_ids"] == [final.result_id]
    assert source.result_id in manifest["lineage_result_ids"]
    assert manifest["analysis_selections"][0]["final_outputs"] == {
        corrected["execution_id"]: ["mean"]
    }


def test_declared_forecast_cannot_omit_evaluation_after_restart_or_general_step(
    workspace,
):
    w = workspace
    source = save(w, [{"amount": 2}, {"amount": 4}])
    execute, _ = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    forecast = execute.func(
        inputs={"source": source.result_id},
        analysis_kind="forecast",
        code="analysis_outputs={'forecast':3.0}",
        runtime=w.runtime("forecast"),
    )
    reopened = RunStore(LocalStorage(w.storage.root))
    execute, finish = create_analysis_tools(
        w.results,
        reopened,
        w.analyses,
        source_id="test",
        limits=PythonExecutionLimits(),
    )
    execute.func(
        inputs={"source": source.result_id},
        analysis_kind="general",
        code="analysis_outputs={'check':1}",
        runtime=w.runtime("check"),
    )
    arguments = dict(
        answer="Evaluation is unavailable.",
        final_outputs={forecast["execution_id"]: ["forecast"]},
        final_result_ids=[],
    )
    result = finish.func(
        outcome="analysis_completed", **arguments, runtime=w.runtime("invalid")
    )
    assert result["ok"] is False and "forecast_evaluation" in result["error"]
    partial = finish.func(outcome="partial", **arguments, runtime=w.runtime("partial"))
    assert partial["analysis_kind"] == "forecast" and partial["outcome"] == "partial"
    with pytest.raises(ValueError, match="partial"):
        resolve_answer(
            CoordinatorResponse(
                answer="Completed", analysis_ids=[partial["analysis_id"]]
            ),
            thread_id=w.thread,
            source_id="test",
            results=w.results,
            analyses=w.analyses,
            runs=reopened,
        )


def test_final_selection_rejects_unknown_outputs_and_empty_completed_claim(workspace):
    w = workspace
    source = save(w, [{"amount": 2}])
    execute, finish = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    result = execute.func(
        inputs={"source": source.result_id},
        analysis_kind="general",
        code="analysis_outputs={'total':2}",
        runtime=w.runtime("execute"),
    )
    for outputs, datasets in [
        ({}, []),
        ({result["execution_id"]: ["missing"]}, []),
        ({"other-assignment": ["total"]}, []),
        ({}, [source.result_id]),
    ]:
        receipt = finish.func(
            outcome="analysis_completed",
            answer="Finished",
            final_outputs=outputs,
            final_result_ids=datasets,
            runtime=w.runtime(str(outputs) + str(datasets)),
        )
        assert receipt["ok"] is False
    assert not w.analyses.list_for_conversation(w.thread, source_id="test")


def test_scalar_analysis_without_material_table_still_requires_html(workspace):
    from tests.test_run_manager import manager, Graph

    w = workspace
    source = save(w, [{"amount": 2}])
    execute, finish = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    step = execute.func(
        inputs={"source": source.result_id},
        analysis_kind="general",
        code="analysis_outputs={'total':2}",
        runtime=w.runtime("scalar"),
    )
    receipt = finish.func(
        outcome="analysis_completed",
        answer="Total is 2",
        final_outputs={step["execution_id"]: ["total"]},
        final_result_ids=[],
        runtime=w.runtime("finish"),
    )
    answer = resolve_answer(
        CoordinatorResponse(answer="Total is 2", analysis_ids=[receipt["analysis_id"]]),
        thread_id=w.thread,
        source_id="test",
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
    )
    assert not answer.results and answer.analyses
    with pytest.raises(ValueError, match="HTML report"):
        manager(w, Graph([]))._finish(w.run, answer)
