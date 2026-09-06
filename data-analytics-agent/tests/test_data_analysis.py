import pytest
from threading import Event
from data_analytics_agent.agents.data_analysis.runner import (
    execute_python,
    PythonExecutionLimits,
    AnalysisExecutionError,
)
from tests.test_persistent_analyst import save


def execute(w, r, code, limits=None, cancel=None):
    return execute_python(
        datasets={"data": r.parquet_path},
        inputs={"data": r.result_id},
        artifact_dir=w.storage.artifacts,
        result_store=w.results,
        thread_id=w.thread,
        source_id="test",
        code=code,
        attempt=1,
        limits=limits or PythonExecutionLimits(),
        cancel=cancel,
    )


def test_python_figures_and_temporal_forecast_evaluation(workspace):
    w = workspace
    r = save(w, [{"t": i, "value": 100 + i + 10 * (i % 12)} for i in range(72)])
    outcome = execute(
        w,
        r,
        """import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.tsa.holtwinters import ExponentialSmoothing
series=datasets['data'].value.astype(float)
train,test=series.iloc[:-12],series.iloc[-12:]
fit=ExponentialSmoothing(train,trend='add',seasonal='add',seasonal_periods=12).fit()
pred=fit.forecast(12)
naive=train.iloc[-12:].to_numpy()
analysis_outputs={'model_mae':float(np.abs(test.to_numpy()-pred.to_numpy()).mean()), 'baseline_mae':float(np.abs(test.to_numpy()-naive).mean())}
fig,ax=plt.subplots();ax.plot(series);analysis_outputs['trend']=fig
output_datasets={'predictions':pd.DataFrame({'actual':test.to_numpy(),'prediction':pred.to_numpy(),'baseline':naive})}
""",
    )
    metrics = {o.name: o.value for o in outcome.outputs if o.kind == "scalar"}
    assert metrics["model_mae"] < metrics["baseline_mae"]
    figure = next(o for o in outcome.outputs if o.kind == "figure")
    assert __import__("pathlib").Path(figure.image_path).is_file()
    assert (
        w.results.get_unscoped(outcome.output_datasets["predictions"]).row_count == 12
    )


def test_timeout_and_output_limits_return_repairable_errors(workspace):
    w = workspace
    r = save(w, [{"value": 1}])
    with pytest.raises(AnalysisExecutionError, match="timeout"):
        execute(w, r, "while True: pass", PythonExecutionLimits(timeout_seconds=0.1))
    with pytest.raises(AnalysisExecutionError):
        execute(
            w,
            r,
            'analysis_outputs={"large": datasets["data"].reindex(range(100))}',
            PythonExecutionLimits(max_output_rows=10),
        )


def test_python_cancellation(workspace):
    w = workspace
    r = save(w, [{"value": 1}])
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        execute(w, r, "while True: pass", cancel=cancel)


def test_python_accepts_compact_scalar_lists(workspace):
    r = save(workspace, [{"x": 1}])
    outcome = execute(
        workspace, r, "analysis_outputs={'columns':list(datasets['data'].columns)}"
    )
    assert outcome.outputs[0].text == '["x"]'
