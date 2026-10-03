import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import nbformat
from nbclient import NotebookClient

from data_analytics_agent.agents.data_analysis.runner import PythonExecutionLimits
from data_analytics_agent.agents.data_analysis.tools import create_analysis_tools
from data_analytics_agent.api import Services
from data_analytics_agent.exports import write_bundle
from data_analytics_agent.forecasting import (
    ForecastEvaluationRequest,
    ForecastEvaluation,
)
from data_analytics_agent.presentation import create_presentation_tools
from data_analytics_agent.reporting.schemas import ReportSpec
from data_analytics_agent.reporting.tools import create_create_report_tool
from data_analytics_agent.schemas import CoordinatorResponse
from data_analytics_agent.run_manager import RunManager
from tests.test_forecast_evaluation import predictions, request


def test_forecast_report_and_moved_notebook_recompute_same_scores(
    workspace, test_settings, tmp_path
):
    w = workspace
    _, source = predictions(w)
    tools = {
        t.name: t
        for t in create_analysis_tools(
            w.results,
            w.runs,
            w.analyses,
            source_id="test",
            limits=PythonExecutionLimits(),
        )
    }
    code = """import numpy as np
import pandas as pd
frame = datasets['observations'].copy()
train = frame.iloc[:6]
slope, intercept = np.polyfit(np.arange(len(train)), train['actual'], 1)
frame['forecast'] = np.nan
frame.loc[6:7, 'forecast'] = intercept + slope * np.array([6, 7])
frame['baseline'] = np.nan
frame.loc[6:7, 'baseline'] = train['actual'].iloc[-1]
production = frame.iloc[:8]
slope, intercept = np.polyfit(np.arange(len(production)), production['actual'], 1)
frame.loc[8:9, 'forecast'] = intercept + slope * np.array([8, 9])
frame['low'] = frame['forecast'] - 3
frame['high'] = frame['forecast'] + 3
output_datasets = {'predictions': frame}
analysis_outputs = {'evaluation_periods': 2}
"""
    executed = tools["execute_analysis_python"].func(
        inputs={"observations": source.result_id},
        code=code,
        runtime=w.runtime("execute"),
    )
    assert executed["ok"]
    descriptor = request(executed["output_datasets"]["predictions"])
    finished = tools["finish_analysis"].func(
        outcome="analysis_completed",
        answer="The short holdout supports only a limited evaluation.",
        method="Earlier training fit; untouched later holdout; production refit uses all observed periods.",
        forecast_evaluation=ForecastEvaluationRequest(**descriptor.model_dump()),
        runtime=w.runtime("finish"),
    )
    assert finished.get("analysis_id"), finished
    evaluation = finished["forecast_evaluation"]
    findings = CoordinatorResponse(
        answer="Forecast evaluation is saved with its measured errors.",
        result_ids=[
            evaluation["scores_result_id"],
            evaluation["predictions_result_id"],
        ],
        analysis_ids=[finished["analysis_id"]],
    )
    publish = next(
        t
        for t in create_presentation_tools(
            w.results, w.analyses, w.runs, w.conversations, source_id="test"
        )
        if t.name == "publish_findings"
    )
    publish.func(findings=findings, runtime=w.runtime("publish"))
    create_create_report_tool(
        w.results, w.analyses, w.runs, w.reports, source_id="test"
    ).func(
        report_json=ReportSpec(
            title="Forecast evidence",
            blocks=[
                {
                    "type": "data_analysis",
                    "title": "Forecast evidence",
                    "summary": findings.answer,
                    "analysis_id": finished["analysis_id"],
                    "include_outputs": False,
                }
            ],
        ).model_dump_json(),
        runtime=w.runtime("report"),
    )
    manager = RunManager(
        conversations=w.conversations,
        runs=w.runs,
        results=w.results,
        analyses=w.analyses,
        reports=w.reports,
    )
    manager._finish(w.run, w.runs.get(w.run).findings)
    services = Services(
        settings=test_settings,
        conversations=w.conversations,
        runs=w.runs,
        results=w.results,
        analyses=w.analyses,
        reports=w.reports,
    )
    report_id = w.runs.get(w.run).answer.report.report_id
    html = Path(
        w.reports.get(report_id, w.thread, source_id="test").html_path
    ).read_text()
    assert "Chronological evaluation" in html
    assert "measured_interval_coverage" in html and "nominal_coverage" in html
    bundle = tmp_path / "forecast.zip"
    write_bundle(services, w.run, report_id, bundle)
    moved = tmp_path / "another-directory"
    with ZipFile(bundle) as archive:
        archive.extractall(moved)
    manifest = json.loads((moved / "manifest.json").read_text())
    assert manifest["forecast_evaluations"] == [
        ForecastEvaluation.model_validate(evaluation).model_dump(mode="json")
    ]
    replayed = subprocess.run(
        [sys.executable, str(moved / "analysis.py")],
        cwd=moved,
        capture_output=True,
        text=True,
    )
    assert replayed.returncode == 0, replayed.stderr
    notebook = nbformat.read(moved / "analysis.ipynb", as_version=4)
    assert any("evaluate_forecasts" in cell.source for cell in notebook.cells)
    NotebookClient(
        notebook,
        timeout=90,
        kernel_name="python3",
        resources={"metadata": {"path": str(moved)}},
    ).execute()
