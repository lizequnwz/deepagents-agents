"""Reusable procedures use the existing execution, report and portable replay path."""

import os
import subprocess
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from data_analytics_agent.agents.data_analysis.runner import PythonExecutionLimits
from data_analytics_agent.agents.data_analysis.tools import create_analysis_tools
from data_analytics_agent.api import Services
from data_analytics_agent.export_replay import load_manifest
from data_analytics_agent.exports import write_bundle
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import ChatTurn, CoordinatorResponse
from tests.test_persistent_analyst import save


def test_helpers_are_saved_reported_and_replayed_from_exact_sources(
    workspace, test_settings, tmp_path
):
    w = workspace
    frame = pd.DataFrame(
        {
            "period": pd.date_range("2020-01-01", periods=40, freq="MS"),
            "amount": 10 + np.arange(40) * 0.3 + np.sin(np.arange(40)),
        }
    )
    saved = save(w, frame.to_dict("records"))
    execute, finish = create_analysis_tools(
        w.results, w.runs, w.analyses, source_id="test", limits=PythonExecutionLimits()
    )
    result = execute.func(
        inputs={"source": saved.result_id},
        runtime=w.runtime("explore"),
        code="""
from data_analytics_agent.analysis.exploration import explore_dataset
from data_analytics_agent.analysis.time_series import diagnose_series
from data_analytics_agent.analysis.scenarios import scenario_grid
profile = explore_dataset(datasets['source'])
diagnostics = diagnose_series(datasets['source'], time='period', value='amount', frequency='monthly')
scenarios = scenario_grid({'price':[10,12], 'volume':[10,20]}, lambda price, volume: price*volume, formula_description='price times volume')
output_datasets = {'overview':profile['overview'], 'diagnostics':diagnostics['series'], **scenarios}
analysis_outputs = {'rows':int(profile['overview'].row_count.iloc[0]), 'maximum_scenario':float(scenarios['scenarios'].outcome.max())}
""",
        analysis_kind="general",
    )
    assert result["ok"], result
    assert "workflow_sources" not in result
    execution = w.runs.get_python_execution(w.run)[0]
    assert "def explore_dataset" in execution.workflow_sources["exploration.py"]
    assert "_calendar.py" in execution.workflow_sources
    assert {output.name: output.value for output in execution.outputs} == {
        "rows": 40,
        "maximum_scenario": 240,
    }
    completed = finish.func(
        outcome="analysis_completed",
        answer="Forty observations; the maximum supplied scenario is 240 source units.",
        method="Explore the complete input, diagnose trend, and calculate explicit deterministic scenarios.",
        final_outputs={result["execution_id"]: ["rows", "maximum_scenario"]},
        final_result_ids=list(result["output_datasets"].values()),
        runtime=w.runtime("finish"),
    )
    answer = resolve_answer(
        CoordinatorResponse(
            answer="Forty observations; maximum supplied scenario 240 source units.",
            result_ids=[result["output_datasets"]["scenarios"]],
            analysis_ids=[completed["analysis_id"]],
        ),
        thread_id=w.thread,
        source_id="test",
        results=w.results,
        analyses=w.analyses,
        runs=w.runs,
    )
    report = generate_report(
        ReportSpec(
            title="Exploration and scenarios",
            blocks=[{"type": "narrative", "body": answer.answer}],
        ),
        thread_id=w.thread,
        source_id="test",
        result_store=w.results,
        analysis_store=w.analyses,
        run_store=w.runs,
        report_store=w.reports,
        findings=answer,
    )
    answer = answer.model_copy(update={"report": report.reference()})
    w.runs.publish(w.run, answer)
    w.runs.attach_report(w.run, report.reference())
    w.runs.complete(w.run, answer)
    w.conversations.complete_run(
        w.thread,
        w.run,
        ChatTurn(
            run_id=w.run, user_message="Explore and compare scenarios", answer=answer
        ),
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
    target = tmp_path / "analysis.zip"
    write_bundle(services, w.run, report.report_id, target)
    moved = tmp_path / "moved outside the workspace"
    with ZipFile(target) as archive:
        archive.extractall(moved)
    manifest = load_manifest(moved)
    assert manifest["format_version"] == 4
    assert "data-analytics-agent==" not in (moved / "requirements.txt").read_text()
    environment = {
        key: value for key, value in os.environ.items() if key != "PYTHONPATH"
    }
    replay = subprocess.run(
        [sys.executable, str(moved / "analysis.py")],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert replay.returncode == 0, replay.stderr
    assert "Step 1: replayed" in replay.stdout
    sources = list(
        moved.glob("steps/libraries/*/data_analytics_agent/analysis/exploration.py")
    )
    assert len(sources) == 1
    assert sources[0].read_text() == execution.workflow_sources["exploration.py"]
    sources[0].write_text(sources[0].read_text() + "\n# changed\n")
    with pytest.raises(ValueError, match="Bundle file changed"):
        load_manifest(moved)
