"""Independent numerical, chronological and uncertainty checks for series helpers."""

import numpy as np
import pandas as pd
import pytest
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

from data_analytics_agent.analysis.time_series import diagnose_series, forecast_series
from data_analytics_agent.forecasting import (
    ForecastEvaluationRequest,
    evaluate_forecast,
)
from data_analytics_agent.stores import ResultStore


def _series(count=40, frequency="MS"):
    positions = np.arange(count)
    return pd.DataFrame(
        {
            "period": pd.date_range("2021-01-01", periods=count, freq=frequency),
            "amount": 20 + 0.4 * positions + np.sin(positions * 1.7),
        }
    )


def _forecast(frame, **updates):
    return forecast_series(
        frame,
        **{
            "time": "period",
            "value": "amount",
            "frequency": "monthly",
            "horizon": 4,
            "holdout": 5,
            **updates,
        },
    )


def test_trend_residual_scores_and_anomalies_recompute_from_saved_values():
    frame = _series(50)
    frame.loc[25, "amount"] += 30
    original = frame.copy(deep=True)
    result = diagnose_series(frame, time="period", value="amount", frequency="monthly")
    rows = result["series"]
    center = np.median(rows.residual)
    scale = 1.4826 * np.median(np.abs(rows.residual - center))
    independent_scores = (rows.residual - center) / scale
    np.testing.assert_allclose(rows.robust_score, independent_scores)
    np.testing.assert_array_equal(
        rows.anomaly.to_numpy(dtype=bool), np.abs(independent_scores) > 3.5
    )
    assert rows.anomaly.iloc[25]
    np.testing.assert_allclose(rows.actual, rows.trend + rows.seasonal + rows.residual)
    assert result["summary"].source_completeness.iloc[0] == "unknown"
    pd.testing.assert_frame_equal(frame, original)


def test_stl_requires_declared_cycles_and_preserves_additive_identity():
    frame = _series(24)
    frame.amount += np.tile([0, 3, -2, 1, 2, -1], 4)
    output = diagnose_series(
        frame, time="period", value="amount", frequency="monthly", seasonal_periods=6
    )
    rows = output["series"]
    np.testing.assert_allclose(rows.actual, rows.trend + rows.seasonal + rows.residual)
    assert "STL" in output["summary"].component_method.iloc[0]
    short = diagnose_series(
        frame.iloc[:11],
        time="period",
        value="amount",
        frequency="monthly",
        seasonal_periods=6,
    )
    assert short["series"].trend.isna().all()
    assert short["series"].anomaly.isna().all()
    assert "two complete cycles" in short["summary"].anomaly_assessment.iloc[0]


@pytest.mark.parametrize("values", [np.ones(20), np.arange(20, dtype=float)])
def test_degenerate_residual_scale_stays_unknown_instead_of_using_sd(values):
    frame = _series(20).assign(amount=values)
    output = diagnose_series(frame, time="period", value="amount", frequency="monthly")
    assert output["series"].robust_score.isna().all()
    assert output["series"].anomaly.isna().all()
    assert pd.isna(output["summary"].residual_scale.iloc[0])
    assert pd.isna(output["summary"].flagged_count.iloc[0])


def test_anomaly_assessment_is_invariant_to_small_declared_measure_units():
    frame = _series(50)
    frame.loc[25, "amount"] += 30
    ordinary = diagnose_series(
        frame, time="period", value="amount", frequency="monthly"
    )
    tiny = diagnose_series(
        frame.assign(amount=frame.amount * 1e-20),
        time="period",
        value="amount",
        frequency="monthly",
    )
    np.testing.assert_allclose(
        ordinary["series"].robust_score, tiny["series"].robust_score, atol=1e-10
    )
    assert tiny["series"].anomaly.tolist() == ordinary["series"].anomaly.tolist()
    assert tiny["summary"].residual_scale.iloc[0] == pytest.approx(
        ordinary["summary"].residual_scale.iloc[0] * 1e-20, rel=1e-10, abs=0
    )


def test_gaps_and_missing_values_are_visible_without_interpolation():
    original = _series(20)
    frame = original.drop(index=4).reset_index(drop=True)
    frame.loc[6, "amount"] = np.nan
    output = diagnose_series(frame, time="period", value="amount", frequency="monthly")
    assert list(output["gaps"].time) == [original.period.iloc[4]]
    assert len(output["series"]) == 19
    assert output["series"].actual.isna().sum() == 1
    assert output["series"].trend.isna().all()
    assert output["series"].anomaly.isna().all()
    assert output["summary"].missing_value_count.iloc[0] == 1
    with pytest.raises(ValueError, match="complete regular series"):
        _forecast(frame)


@pytest.mark.parametrize(
    "change,message",
    [
        (lambda frame: frame.assign(period=frame.period.astype(str)), "parsed dates"),
        (
            lambda frame: pd.concat([frame, frame.iloc[:1]], ignore_index=True),
            "unique nonmissing",
        ),
        (
            lambda frame: frame.assign(period=frame.period.dt.tz_localize("UTC")),
            "without timezone",
        ),
        (
            lambda frame: frame.assign(period=frame.period + pd.Timedelta(hours=3)),
            "subdaily",
        ),
        (
            lambda frame: frame.assign(period=frame.period + pd.Timedelta(days=4)),
            "not aligned",
        ),
        (lambda frame: frame.assign(amount=frame.amount.astype(str)), "numeric values"),
    ],
)
def test_series_requires_explicit_typed_unique_aligned_periods(change, message):
    with pytest.raises(ValueError, match=message):
        diagnose_series(
            change(_series()), time="period", value="amount", frequency="monthly"
        )


def test_holdout_scores_and_temporal_boundaries_recompute_independently():
    frame = _series()
    original = frame.copy(deep=True)
    output = _forecast(frame)
    predictions = output["forecast_predictions"]
    training = predictions[predictions.split.eq("training")]
    held = predictions[predictions.split.eq("holdout")]
    future = predictions[predictions.split.eq("future")]
    assert len(training) == 35 and len(held) == 5 and len(future) == 4
    assert training.time.max() < held.time.min() <= held.time.max() < future.time.min()
    assert training.candidate.isna().all()
    assert future.actual.isna().all()
    assert held.baseline.eq(frame.amount.iloc[34]).all()
    assert future.baseline.eq(frame.amount.iloc[-1]).all()
    for index, column in enumerate(["candidate", "baseline"]):
        errors = held[column].to_numpy() - frame.amount.iloc[-5:].to_numpy()
        score = output["forecast_scores"].iloc[index]
        assert score.mae == pytest.approx(sum(abs(errors)) / 5)
        assert score.rmse == pytest.approx(np.sqrt(sum(errors**2) / 5))
    measured = np.mean((held.actual >= held.lower) & (held.actual <= held.upper))
    assert output["forecast_scores"].measured_interval_coverage.iloc[0] == measured
    assert output["forecast_scores"].nominal_coverage.iloc[0] == 0.95
    pd.testing.assert_frame_equal(frame, original)


def test_bounds_match_statsmodels_exact_model_prediction_intervals():
    frame = _series()
    output = _forecast(frame)
    training = pd.Series(
        frame.amount.iloc[:-5].to_numpy(),
        index=pd.DatetimeIndex(frame.period.iloc[:-5], freq="MS"),
    )
    reference = ETSModel(training, error="add", trend="add").fit(
        disp=False, maxiter=1000
    )
    expected = reference.get_prediction(start=35, end=39, method="exact").summary_frame(
        alpha=0.05
    )
    held = output["forecast_predictions"].query("split == 'holdout'")
    np.testing.assert_allclose(
        held[["candidate", "lower", "upper"]],
        expected[["mean", "pi_lower", "pi_upper"]],
    )
    assessed = output["forecast_predictions"].query("split != 'training'")
    assert (assessed.lower <= assessed.candidate).all()
    assert (assessed.candidate <= assessed.upper).all()
    assert (assessed.upper > assessed.lower).all()
    assert output["forecast_metadata"].interval_kind.iloc[0] == "prediction"
    assert (
        "excluding parameter/model uncertainty"
        in output["forecast_metadata"].interval_method.iloc[0]
    )


def test_holdout_changes_cannot_leak_into_holdout_predictions():
    frame = _series()
    original = _forecast(frame)["forecast_predictions"]
    frame.loc[len(frame) - 5 :, "amount"] += 100
    changed = _forecast(frame)["forecast_predictions"]
    np.testing.assert_allclose(
        original.query("split == 'holdout'")[
            ["candidate", "lower", "upper", "baseline"]
        ],
        changed.query("split == 'holdout'")[
            ["candidate", "lower", "upper", "baseline"]
        ],
    )
    assert not np.allclose(
        original.query("split == 'future'").candidate,
        changed.query("split == 'future'").candidate,
    )


def test_forecast_output_is_accepted_by_existing_saved_evidence_evaluator():
    output = _forecast(_series())
    predictions = output["forecast_predictions"]
    store = ResultStore()
    saved = store.save(
        thread_id="thread",
        source_id="source",
        columns=list(predictions),
        rows=predictions.to_dict("records"),
        executed_sql="",
    )
    metadata = output["forecast_metadata"].iloc[0].to_dict()
    fields = ForecastEvaluationRequest.model_fields
    values = {name: value for name, value in metadata.items() if name in fields}
    values["predictions_result_id"] = saved.result_id
    values["interval"] = {
        "kind": metadata["interval_kind"],
        "method": metadata["interval_method"],
        "nominal_coverage": metadata["nominal_coverage"],
    }
    evaluated = evaluate_forecast(
        ForecastEvaluationRequest(**values),
        results=store,
        thread_id="thread",
        source_id="source",
    )
    scores = store.get(evaluated.scores_result_id, "thread").rows
    for index in range(2):
        assert scores[index]["mae"] == pytest.approx(
            output["forecast_scores"].mae.iloc[index]
        )
        assert scores[index]["rmse"] == pytest.approx(
            output["forecast_scores"].rmse.iloc[index]
        )
    assert evaluated.training_count == 35
    assert evaluated.evaluation_sample_size == 5


def test_explicit_seasonal_ets_and_weekly_calendar_anchor():
    frame = _series(42)
    frame.amount += 3 * np.sin(np.arange(42) * np.pi / 3)
    seasonal = _forecast(frame, seasonal_periods=6)
    assert (
        "additive seasonality (6 periods)"
        in seasonal["forecast_metadata"].candidate_method.iloc[0]
    )
    weekly = _series(20).assign(
        period=pd.date_range("2021-01-06", periods=20, freq="W-WED")
    )
    predictions = _forecast(weekly, frequency="weekly")["forecast_predictions"]
    assert predictions.time.dt.dayofweek.eq(2).all()
    assert predictions.time.diff().dropna().eq(pd.Timedelta(days=7)).all()


@pytest.mark.parametrize(
    "updates,message",
    [
        ({"horizon": 0}, "horizon"),
        ({"holdout": 0}, "holdout"),
        ({"holdout": 35}, "training periods"),
        ({"coverage": 1}, "coverage"),
        ({"seasonal_periods": 1}, "seasonal_periods"),
        ({"frequency": "inferred"}, "frequency"),
    ],
)
def test_forecast_rejects_insufficient_or_implicit_model_requirements(updates, message):
    with pytest.raises(ValueError, match=message):
        _forecast(_series(), **updates)


def test_constant_training_refuses_unjustified_forecast_intervals():
    with pytest.raises(ValueError, match="no variation"):
        _forecast(_series().assign(amount=10.0))
