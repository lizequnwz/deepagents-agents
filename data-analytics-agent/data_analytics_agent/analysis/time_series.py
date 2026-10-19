"""Explicit regular-series diagnostics and chronological ETS forecasting.

Inputs are complete saved populations already aggregated to one row per calendar
period. Helpers never interpolate periods, infer business units/source cutoffs, or
choose a frequency/seasonal cycle from the data. Save the returned DataFrames as
ordinary output_datasets; their metadata can populate evaluate_forecast after the
prediction table receives its saved result ID.
"""

from datetime import date, datetime
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.seasonal import STL

from data_analytics_agent.analysis._frames import numeric_values, require_columns
from data_analytics_agent.analysis._calendar import FREQUENCIES


def _positive_int(value, name, *, minimum=1, maximum=1000):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")


def _calendar_series(frame, time, value, frequency):
    require_columns(frame, [time, value])
    if frequency not in FREQUENCIES:
        raise ValueError(
            "frequency must be daily, weekly, monthly, quarterly, or yearly."
        )
    if frame.empty:
        raise ValueError("The series has no observations.")
    times = frame[time]
    if not pd.api.types.is_datetime64_any_dtype(times) and not all(
        isinstance(item, (date, datetime, pd.Timestamp)) for item in times
    ):
        raise ValueError(
            "time must contain explicitly parsed dates or timestamps, not text."
        )
    times = pd.to_datetime(times, errors="raise")
    if times.isna().any() or times.dt.tz is not None or times.duplicated().any():
        raise ValueError("Use unique nonmissing calendar periods without timezone.")
    if not times.equals(times.dt.normalize()):
        raise ValueError(
            "Normalize subdaily timestamps explicitly before calendar analysis."
        )
    numbers = numeric_values(frame, value).astype(float)
    data = (
        pd.DataFrame({"time": times.to_numpy(), "actual": numbers.to_numpy()})
        .sort_values("time")
        .reset_index(drop=True)
    )
    offset = (
        pd.offsets.Week(weekday=data.time.iloc[0].weekday())
        if frequency == "weekly"
        else pd.tseries.frequencies.to_offset(FREQUENCIES[frequency])
    )
    expected = pd.date_range(data.time.iloc[0], data.time.iloc[-1], freq=offset)
    if not data.time.isin(expected).all():
        raise ValueError(
            "Observed dates are not aligned to the declared frequency; prepare calendar period labels explicitly."
        )
    gaps = pd.DataFrame({"time": expected.difference(pd.DatetimeIndex(data.time))})
    return data, offset, gaps


def diagnose_series(
    frame: pd.DataFrame,
    *,
    time: str,
    value: str,
    frequency: str,
    seasonal_periods: int | None = None,
    anomaly_threshold: float = 3.5,
) -> dict[str, pd.DataFrame]:
    """Describe one declared series without repairing gaps or missing measures.

    A complete regular series gets a linear trend, or robust STL when an
    explicit seasonal cycle has at least two complete cycles. Anomalies use
    centered residuals / (1.4826 * residual MAD). Undefined/degenerate scales
    produce missing scores AND missing flags, never an SD fallback or false
    "normal" assessments. These are descriptive flags, not causal findings or
    calibrated false-positive probabilities. Gaps only describe the supplied
    window; source completeness remains unknown.
    """
    if seasonal_periods is not None:
        _positive_int(seasonal_periods, "seasonal_periods", minimum=2)
    if (
        isinstance(anomaly_threshold, bool)
        or not np.isfinite(anomaly_threshold)
        or anomaly_threshold <= 0
    ):
        raise ValueError("anomaly_threshold must be a positive finite number.")
    data, _, gaps = _calendar_series(frame, time, value, frequency)
    for name in ("trend", "seasonal", "residual", "robust_score"):
        data[name] = np.nan
    data["anomaly"] = pd.array([pd.NA] * len(data), dtype="boolean")
    missing = int(data.actual.isna().sum())
    method, assessment = "unavailable", "unavailable: insufficient observations"
    slope, scale = np.nan, np.nan
    if len(gaps) or missing:
        assessment = "unavailable: gaps or missing values require explicit preparation"
    elif seasonal_periods is not None and len(data) < 2 * seasonal_periods:
        assessment = (
            "unavailable: seasonal decomposition requires at least two complete cycles"
        )
    elif len(data) >= 3:
        positions = np.arange(len(data), dtype=float)
        if seasonal_periods is not None:
            fitted = STL(
                data.actual.to_numpy(), period=seasonal_periods, robust=True
            ).fit()
            data["trend"], data["seasonal"], data["residual"] = (
                fitted.trend,
                fitted.seasonal,
                fitted.resid,
            )
            method = "Robust STL with explicitly declared seasonal period"
        else:
            coefficients = np.polyfit(positions, data.actual.to_numpy(), 1)
            data["trend"] = np.polyval(coefficients, positions)
            data["seasonal"] = 0.0
            data["residual"] = data.actual - data.trend
            method = "Least-squares linear trend per declared period"
        slope = float(np.polyfit(positions, data.trend.to_numpy(), 1)[0])
        residual = data.residual.to_numpy()
        center = float(np.median(residual))
        mad_scale = float(1.4826 * np.median(np.abs(residual - center)))
        numerical_floor = (
            np.finfo(float).eps
            * max(np.finfo(float).tiny, float(data.actual.abs().max()))
            * 100
        )
        if not np.isfinite(mad_scale) or mad_scale <= numerical_floor:
            assessment = "unavailable: zero or numerically degenerate residual MAD"
        else:
            scale = mad_scale
            data["robust_score"] = (residual - center) / scale
            data["anomaly"] = pd.array(
                data.robust_score.abs() > anomaly_threshold, dtype="boolean"
            )
            assessment = "assessed with residual MAD; descriptive flags only"
    summary = pd.DataFrame(
        [
            {
                "frequency": frequency,
                "seasonal_periods": seasonal_periods,
                "observed_periods": len(data),
                "gap_count": len(gaps),
                "missing_value_count": missing,
                "first_observed_period": data.time.iloc[0],
                "last_observed_period": data.time.iloc[-1],
                "source_completeness": "unknown",
                "preparation": "No missing periods or values filled.",
                "component_method": method,
                "trend_per_period": slope,
                "residual_scale": scale,
                "anomaly_threshold": anomaly_threshold,
                "anomaly_assessment": assessment,
                "flagged_count": int(data.anomaly.sum())
                if data.anomaly.notna().any()
                else pd.NA,
            }
        ]
    )
    return {"series": data, "gaps": gaps, "summary": summary}


def _fit_and_predict(series, steps, seasonal_periods, coverage):
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        fitted = ETSModel(
            series,
            error="add",
            trend="add",
            seasonal="add" if seasonal_periods else None,
            seasonal_periods=seasonal_periods,
        ).fit(disp=False, maxiter=1000)
        if not fitted.mle_retvals.get("converged", False):
            raise ValueError(
                "ETS fitting did not converge; save an analytical limitation instead of unsupported predictions."
            )
        if not np.isfinite(fitted.scale) or fitted.scale <= 0:
            raise ValueError(
                "ETS cannot estimate a positive finite innovation variance for prediction intervals."
            )
        predictions = fitted.get_prediction(
            start=len(series),
            end=len(series) + steps - 1,
            method="exact",
        ).summary_frame(alpha=1 - coverage)
    if not np.isfinite(predictions[["mean", "pi_lower", "pi_upper"]].to_numpy()).all():
        raise ValueError("ETS returned nonfinite forecasts or prediction intervals.")
    if (predictions.pi_lower > predictions["mean"]).any() or (
        predictions["mean"] > predictions.pi_upper
    ).any():
        raise ValueError(
            "ETS prediction intervals do not enclose their point forecasts."
        )
    return (
        fitted,
        predictions,
        list(dict.fromkeys(str(item.message) for item in captured)),
    )


def forecast_series(
    frame: pd.DataFrame,
    *,
    time: str,
    value: str,
    frequency: str,
    horizon: int,
    holdout: int,
    seasonal_periods: int | None = None,
    coverage: float = 0.95,
) -> dict[str, pd.DataFrame]:
    """Evaluate additive ETS on an untouched final holdout, then refit for future.

    The sole candidate is ETS additive error/additive trend, with additive
    seasonality only when seasonal_periods is explicitly supplied. At least
    eight training observations and two seasonal cycles (when used) are
    required. The baseline repeats the last training observation throughout
    the holdout and the last observed value throughout the future horizon.

    Bounds are statsmodels ETS exact model-based prediction intervals under
    additive Gaussian innovations, conditional on estimated parameters. They
    exclude parameter/model uncertainty and impose no nonnegativity clipping.
    Holdout coverage is measured separately from nominal coverage. A series
    with gaps, nulls or no variation cannot support this model's intervals.
    """
    _positive_int(horizon, "horizon")
    _positive_int(holdout, "holdout")
    if seasonal_periods is not None:
        _positive_int(seasonal_periods, "seasonal_periods", minimum=2)
    if isinstance(coverage, bool) or not np.isfinite(coverage) or not 0 < coverage < 1:
        raise ValueError("coverage must lie strictly between zero and one.")
    data, offset, gaps = _calendar_series(frame, time, value, frequency)
    if len(gaps) or data.actual.isna().any():
        raise ValueError(
            "Forecasting requires a complete regular series; save explicit preparation for gaps or missing values first."
        )
    minimum = max(8, 2 * seasonal_periods if seasonal_periods else 0)
    if len(data) - holdout < minimum:
        raise ValueError(
            f"At least {minimum} training periods plus the explicit holdout are required."
        )
    training = data.iloc[:-holdout]
    if training.actual.nunique() < 2:
        raise ValueError(
            "Training has no variation; this ETS candidate cannot estimate supported prediction intervals."
        )
    series = pd.Series(
        data.actual.to_numpy(), index=pd.DatetimeIndex(data.time, freq=offset)
    )
    evaluated, held_predictions, held_warnings = _fit_and_predict(
        series.iloc[:-holdout], holdout, seasonal_periods, coverage
    )
    final, future_predictions, future_warnings = _fit_and_predict(
        series, horizon, seasonal_periods, coverage
    )
    candidate = "ETS additive error/additive trend" + (
        f"/additive seasonality ({seasonal_periods} periods)"
        if seasonal_periods
        else "/no seasonality"
    )
    baseline = "Last observed value carried forward at each forecast origin"
    historical = data.assign(
        candidate=np.nan, baseline=np.nan, lower=np.nan, upper=np.nan, split="training"
    )
    historical.loc[len(training) :, ["candidate", "lower", "upper"]] = held_predictions[
        ["mean", "pi_lower", "pi_upper"]
    ].to_numpy()
    historical.loc[len(training) :, "baseline"] = float(training.actual.iloc[-1])
    historical.loc[len(training) :, "split"] = "holdout"
    future = pd.DataFrame(
        {
            "time": future_predictions.index,
            "actual": np.nan,
            "candidate": future_predictions["mean"].to_numpy(),
            "baseline": float(data.actual.iloc[-1]),
            "lower": future_predictions.pi_lower.to_numpy(),
            "upper": future_predictions.pi_upper.to_numpy(),
            "split": "future",
        }
    )
    predictions = pd.concat([historical, future], ignore_index=True)
    held = historical.iloc[-holdout:]
    scores = []
    for column, method in [("candidate", candidate), ("baseline", baseline)]:
        errors = held[column].to_numpy() - held.actual.to_numpy()
        scores.append(
            {
                "method": method,
                "sample_size": holdout,
                "mae": float(np.mean(np.abs(errors))),
                "rmse": float(np.sqrt(np.mean(errors**2))),
                "measured_interval_coverage": float(
                    held.actual.between(held.lower, held.upper).mean()
                )
                if column == "candidate"
                else np.nan,
                "nominal_coverage": coverage if column == "candidate" else np.nan,
            }
        )
    interval_method = "statsmodels ETS get_prediction(method='exact'); additive Gaussian innovations; conditional on fitted parameters, excluding parameter/model uncertainty."
    metadata = pd.DataFrame(
        [
            {
                "time_column": "time",
                "actual_column": "actual",
                "candidate_column": "candidate",
                "baseline_column": "baseline",
                "lower_bound": "lower",
                "upper_bound": "upper",
                "frequency": frequency,
                "training_start": training.time.iloc[0],
                "training_end": training.time.iloc[-1],
                "holdout_start": held.time.iloc[0],
                "holdout_end": held.time.iloc[-1],
                "forecast_origin": data.time.iloc[-1],
                "forecast_start": future.time.iloc[0],
                "horizon": horizon,
                "training_count": len(training),
                "holdout_count": holdout,
                "candidate_method": candidate,
                "baseline_method": baseline,
                "interval_kind": "prediction",
                "interval_method": interval_method,
                "nominal_coverage": coverage,
                "preparation": "No missing periods or values filled; one chronological holdout; final model refit on all observed periods.",
                "source_completeness": "unknown",
                "model_warnings": " | ".join(
                    dict.fromkeys(held_warnings + future_warnings)
                ),
            }
        ]
    )
    parameters = pd.DataFrame(
        [
            {"fit": label, "parameter": name, "value": float(number)}
            for label, fitted in [("training", evaluated), ("all_observed", final)]
            for name, number in zip(fitted.model.param_names, fitted.params)
        ]
    )
    return {
        "forecast_predictions": predictions,
        "forecast_scores": pd.DataFrame(scores),
        "forecast_metadata": metadata,
        "model_parameters": parameters,
    }
