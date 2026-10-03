from datetime import date
from math import sqrt

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from pydantic import ValidationError

from data_analytics_agent.forecasting import (
    ForecastEvaluationRequest,
    evaluate_forecast,
)
from data_analytics_agent.visualization.renderer import build_chart
from data_analytics_agent.visualization.schemas import ChartSpec
from data_analytics_agent.visualization.validation import validate_chart_spec


def predictions(w, *, actuals=None):
    frame = pd.DataFrame(
        {
            "month": pd.date_range("2024-01-01", periods=10, freq="MS"),
            "actual": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 20.0, 30.0, None, None]
            if actuals is None
            else actuals,
            "forecast": [None] * 6 + [18.0, 34.0, 35.0, 36.0],
            "baseline": [None] * 6 + [15.0, 15.0, None, None],
            "low": [None] * 6 + [17.0, 31.0, 30.0, 31.0],
            "high": [None] * 6 + [22.0, 39.0, 40.0, 41.0],
        }
    )
    return frame, save_frame(w, frame)


def save_frame(w, frame):
    return w.results.save_batches(
        pa.Table.from_pandas(frame, preserve_index=False).to_batches(),
        thread_id=w.thread,
        source_id="test",
        purpose="Saved forecast predictions",
    )


def request(result_id, **kwargs):
    return ForecastEvaluationRequest(
        predictions_result_id=result_id,
        time_column="month",
        actual_column="actual",
        candidate_column="forecast",
        baseline_column="baseline",
        training_start=date(2024, 1, 1),
        training_end=date(2024, 6, 1),
        holdout_start=date(2024, 7, 1),
        holdout_end=date(2024, 8, 1),
        forecast_origin=date(2024, 8, 1),
        horizon=2,
        frequency="monthly",
        candidate_method="Chronological trend",
        baseline_method="Last training value",
        lower_bound="low",
        upper_bound="high",
        interval={
            "kind": "prediction",
            "method": "Declared holdout errors",
            "nominal_coverage": 0.9,
        },
        **kwargs,
    )


def evaluate(w, descriptor):
    return evaluate_forecast(
        descriptor, results=w.results, thread_id=w.thread, source_id="test"
    )


def test_scores_recompute_from_saved_actuals_and_predictions(workspace):
    w = workspace
    _, saved = predictions(w)
    outcome = evaluate(w, request(saved.result_id))
    scores = w.results.get(outcome.scores_result_id, w.thread, source_id="test")
    candidate, baseline = scores.rows
    assert candidate["mae"] == 3
    assert candidate["rmse"] == pytest.approx(sqrt(10))
    assert baseline["mae"] == 10
    assert baseline["rmse"] == pytest.approx(sqrt(125))
    assert candidate["measured_interval_coverage"] == 0.5
    assert candidate["nominal_coverage"] == 0.9
    assert outcome.training_count == 6 and outcome.evaluation_sample_size == 2
    assert outcome.forecast_start == date(2024, 9, 1)
    assert scores.parent_result_ids == [saved.result_id]
    assert "unstable" in " ".join(outcome.warnings)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "nonfinite",
        "future_actual",
        "wrong_horizon",
        "inverted_interval",
    ],
)
def test_invalid_forecast_evidence_is_repairable(workspace, damage):
    w = workspace
    frame, _ = predictions(w)
    if damage == "missing":
        frame = frame.drop(index=3)
    elif damage == "duplicate":
        frame.loc[3, "month"] = frame.loc[2, "month"]
    elif damage == "nonfinite":
        frame.loc[6, "forecast"] = np.inf
    elif damage == "future_actual":
        frame.loc[9, "actual"] = 50.0
    elif damage == "wrong_horizon":
        frame = frame.drop(index=9)
    else:
        frame.loc[6, "low"] = 50.0
    saved = save_frame(w, frame)
    with pytest.raises(ValueError):
        evaluate(w, request(saved.result_id))


def test_overlapping_temporal_windows_rejected(workspace):
    _, saved = predictions(workspace)
    data = request(saved.result_id).model_dump()
    data["training_end"] = date(2024, 7, 1)
    with pytest.raises(ValidationError, match="earlier training"):
        ForecastEvaluationRequest(**data)


@pytest.mark.parametrize("column", ["month", "actual", "forecast", "low"])
def test_text_requires_explicit_preparation(workspace, column):
    frame, _ = predictions(workspace)
    frame[column] = frame[column].astype("string")
    saved = save_frame(workspace, frame)
    with pytest.raises(ValueError, match="typed date|numeric type"):
        evaluate(workspace, request(saved.result_id))


@pytest.mark.parametrize(
    "values",
    [
        [50, 5, 70, 4, 90, 7, 100, 2, None, None],
        [10, 11, 12, 13, 14, 15, 150, 160, None, None],
    ],
)
def test_noisy_and_structural_break_cases_keep_measured_errors(workspace, values):
    _, saved = predictions(workspace, actuals=values)
    outcome = evaluate(workspace, request(saved.result_id))
    score = workspace.results.get_unscoped(outcome.scores_result_id).rows[0]
    error = np.array([18, 34]) - np.array(values[6:8])
    assert score["mae"] == pytest.approx(np.abs(error).mean())
    assert score["rmse"] == pytest.approx(np.sqrt(np.square(error).mean()))
    assert outcome.evaluation_sample_size == 2


def test_actual_forecast_chart_attaches_interval_and_marker(workspace):
    w = workspace
    _, saved = predictions(w)
    evaluation = evaluate(w, request(saved.result_id))
    spec = ChartSpec(
        result_id=saved.result_id,
        chart_type="line",
        title="Observed and forecast",
        x="month",
        y=["actual", "forecast"],
        lower_bound="low",
        upper_bound="high",
        interval=evaluation.interval,
        interval_series="forecast",
        forecast_start=evaluation.forecast_start,
    )
    validate_chart_spec(spec, saved)
    rendered = build_chart(spec, saved.rows)
    assert len(rendered.figure.data) == 4
    assert rendered.figure.data[-1].legendgroup == "forecast"
    assert rendered.figure.layout.shapes[0].x0 == "2024-09-01"
    assert "nominal" in " ".join(rendered.notes)
    with pytest.raises(ValidationError, match="explicit interval_series"):
        ChartSpec(**{**spec.model_dump(), "interval_series": None})


@pytest.mark.parametrize(
    "frequency,freq",
    [
        ("daily", "D"),
        ("weekly", "7D"),
        ("monthly", "MS"),
        ("quarterly", "QS"),
        ("yearly", "YS"),
    ],
)
def test_every_forecast_frequency_recomputes_independent_scores(
    workspace, frequency, freq
):
    w = workspace
    dates = pd.date_range("2024-01-01", periods=10, freq=freq)
    actual = np.arange(10, dtype=float)
    frame = pd.DataFrame(
        {
            "month": dates,
            "actual": [*actual[:8], None, None],
            "forecast": [None] * 5 + [6.0, 8.0, 10.0, 11.0, 12.0],
            "baseline": [None] * 5 + [4.0] * 3 + [None, None],
        }
    )
    saved = save_frame(w, frame)
    data = request(saved.result_id).model_dump()
    data.update(
        training_start=dates[0].date(),
        training_end=dates[4].date(),
        holdout_start=dates[5].date(),
        holdout_end=dates[7].date(),
        forecast_origin=dates[7].date(),
        frequency=frequency,
        lower_bound=None,
        upper_bound=None,
        interval=None,
    )
    outcome = evaluate(w, ForecastEvaluationRequest(**data))
    scores = w.results.get_unscoped(outcome.scores_result_id).rows
    assert scores[0]["mae"] == pytest.approx(2.0)
    assert scores[0]["rmse"] == pytest.approx(sqrt(14 / 3))
    assert scores[1]["mae"] == pytest.approx(2.0)
    assert all(
        r["measured_interval_coverage"] is None and r["nominal_coverage"] is None
        for r in scores
    )
    assert outcome.forecast_start == dates[8].date()


def test_weekly_origin_between_periods_keeps_training_calendar(workspace):
    w = workspace
    frame, _ = predictions(w)
    dates = pd.date_range("2024-01-01", periods=10, freq="W-MON")
    frame["month"] = dates
    saved = save_frame(w, frame)
    data = request(saved.result_id).model_dump()
    data.update(
        training_start=dates[0].date(),
        training_end=dates[5].date(),
        holdout_start=dates[6].date(),
        holdout_end=dates[7].date(),
        forecast_origin=(dates[7] + pd.Timedelta(days=3)).date(),
        frequency="weekly",
    )
    outcome = evaluate(w, ForecastEvaluationRequest(**data))
    assert outcome.forecast_start == dates[8].date()


def test_weekly_holdout_cannot_change_the_training_calendar(workspace):
    w = workspace
    frame, _ = predictions(w)
    dates = pd.date_range("2024-01-01", periods=10, freq="W-MON")
    frame["month"] = dates
    frame.loc[6:, "month"] += pd.Timedelta(days=1)
    saved = save_frame(w, frame)
    data = request(saved.result_id).model_dump()
    data.update(
        training_start=dates[0].date(),
        training_end=dates[5].date(),
        holdout_start=(dates[6] + pd.Timedelta(days=1)).date(),
        holdout_end=(dates[7] + pd.Timedelta(days=1)).date(),
        forecast_origin=(dates[7] + pd.Timedelta(days=1)).date(),
        frequency="weekly",
    )
    with pytest.raises(ValueError, match="unaligned periods"):
        evaluate(w, ForecastEvaluationRequest(**data))


@pytest.mark.parametrize(
    "column,value",
    [("lower_bound", "forecast"), ("upper_bound", "low"), ("lower_bound", "actual")],
)
def test_interval_columns_cannot_alias_other_prediction_roles(workspace, column, value):
    _, saved = predictions(workspace)
    data = request(saved.result_id).model_dump()
    data[column] = value
    with pytest.raises(ValidationError, match="distinct"):
        ForecastEvaluationRequest(**data)


@pytest.mark.parametrize(
    "damage", ["timezone", "subdaily", "missing_time", "future_gap"]
)
def test_extra_temporal_damage_has_explicit_feedback(workspace, damage):
    w = workspace
    frame, _ = predictions(w)
    if damage == "timezone":
        frame["month"] = frame["month"].dt.tz_localize("UTC")
    elif damage == "subdaily":
        frame.loc[6, "month"] += pd.Timedelta(hours=1)
    elif damage == "missing_time":
        frame.loc[6, "month"] = pd.NaT
    else:
        frame.loc[9, "month"] += pd.DateOffset(months=1)
    saved = save_frame(w, frame)
    with pytest.raises(ValueError, match="timezone|normalize|unaligned periods"):
        evaluate(w, request(saved.result_id))


def test_forecast_row_order_does_not_change_scores(workspace):
    w = workspace
    frame, original = predictions(w)
    shuffled = save_frame(w, frame.sample(frac=1, random_state=101))
    first = evaluate(w, request(original.result_id))
    second = evaluate(w, request(shuffled.result_id))
    assert (
        w.results.get_unscoped(first.scores_result_id).rows
        == w.results.get_unscoped(second.scores_result_id).rows
    )


@pytest.mark.parametrize("seed", [7, 101, 2026])
@pytest.mark.parametrize(
    "frequency,freq",
    [
        ("daily", "D"),
        ("weekly", "W-MON"),
        ("monthly", "MS"),
        ("quarterly", "QS"),
        ("yearly", "YS"),
    ],
)
def test_seeded_forecast_scores_and_coverage_match_known_errors(
    workspace, seed, frequency, freq
):
    w = workspace
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-12-25", periods=22, freq=freq)
    actuals = rng.normal(0, 25, 18)
    errors = rng.normal(0, 5, 6)
    forecast = np.r_[np.full(12, np.nan), actuals[12:] + errors, rng.normal(0, 25, 4)]
    frame = pd.DataFrame(
        {
            "month": dates,
            "actual": [*actuals, None, None, None, None],
            "forecast": forecast,
            "baseline": np.r_[
                np.full(12, np.nan), np.full(6, actuals[11]), np.full(4, np.nan)
            ],
            "low": forecast - 4,
            "high": forecast + 4,
        }
    )
    saved = save_frame(w, frame)
    data = request(saved.result_id).model_dump()
    data.update(
        training_start=dates[0].date(),
        training_end=dates[11].date(),
        holdout_start=dates[12].date(),
        holdout_end=dates[17].date(),
        forecast_origin=dates[17].date(),
        frequency=frequency,
        horizon=4,
    )
    outcome = evaluate(w, ForecastEvaluationRequest(**data))
    candidate, baseline = w.results.get_unscoped(outcome.scores_result_id).rows
    assert candidate["mae"] == pytest.approx(np.abs(errors).mean())
    assert candidate["rmse"] == pytest.approx(np.linalg.norm(errors) / sqrt(6))
    assert candidate["measured_interval_coverage"] == pytest.approx(
        np.count_nonzero(np.abs(errors) <= 4) / 6
    )
    baseline_errors = actuals[11] - actuals[12:]
    assert baseline["rmse"] == pytest.approx(np.linalg.norm(baseline_errors) / sqrt(6))
    assert outcome.evaluation_sample_size == 6
    assert not any("fewer than five" in warning for warning in outcome.warnings)


def test_overflowing_error_scores_are_repairable_before_saving(workspace):
    w = workspace
    frame, _ = predictions(w)
    frame.loc[6:7, "forecast"] = 1e308
    frame.loc[6:7, "low"] = 1e308
    frame.loc[6:7, "high"] = 1e308
    saved = save_frame(w, frame)
    before = {
        r.result_id for r in w.results.list_for_conversation(w.thread, source_id="test")
    }
    with pytest.raises(ValueError, match="finite|rescale"):
        evaluate(w, request(saved.result_id))
    assert {
        r.result_id for r in w.results.list_for_conversation(w.thread, source_id="test")
    } == before
