"""Inspectable chronological forecast evaluation over immutable saved predictions."""

from datetime import date
from typing import Literal

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlglot import exp

from data_analytics_agent.visualization.schemas import ChartInterval


class ForecastEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predictions_result_id: str
    time_column: str
    actual_column: str
    candidate_column: str
    baseline_column: str
    training_start: date
    training_end: date
    holdout_start: date
    holdout_end: date
    forecast_origin: date
    horizon: int = Field(ge=1, le=1000)
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "yearly"]
    candidate_method: str = Field(min_length=1, max_length=500)
    baseline_method: str = Field(min_length=1, max_length=500)
    lower_bound: str | None = None
    upper_bound: str | None = None
    interval: ChartInterval | None = None
    preparation: str = Field(default="No missing periods filled.", max_length=2000)

    @model_validator(mode="after")
    def chronological(self):
        if not (
            self.training_start
            <= self.training_end
            < self.holdout_start
            <= self.holdout_end
            <= self.forecast_origin
        ):
            raise ValueError(
                "Evaluation must use an earlier training window and a later holdout ending by the forecast origin."
            )
        if bool(self.lower_bound) != bool(self.upper_bound) or bool(
            self.lower_bound
        ) != bool(self.interval):
            raise ValueError(
                "Evaluation bounds need both columns and declared interval meaning."
            )
        columns = [
            self.time_column,
            self.actual_column,
            self.candidate_column,
            self.baseline_column,
        ]
        if self.lower_bound:
            columns += [self.lower_bound, self.upper_bound]
        if len(set(columns)) != len(columns):
            raise ValueError(
                "Time, actuals, candidate, baseline and interval bounds need distinct named columns."
            )
        return self


class ForecastEvaluation(ForecastEvaluationRequest):
    scores_result_id: str
    training_count: int
    evaluation_sample_size: int
    forecast_start: date
    warnings: list[str] = Field(default_factory=list)

    @property
    def description(self):
        return (
            f"Chronological evaluation: training {self.training_start} through {self.training_end} "
            f"({self.training_count} periods); holdout {self.holdout_start} through {self.holdout_end} "
            f"({self.evaluation_sample_size} periods). Forecast origin {self.forecast_origin}; "
            f"{self.horizon} {self.frequency} periods beginning {self.forecast_start}. "
            f"Candidate: {self.candidate_method}. Baseline: {self.baseline_method}. "
            f"Preparation: {self.preparation} "
            + (
                self.interval.description
                if self.interval
                else "No forecast interval supplied."
            )
        )


FREQUENCIES = {
    "daily": "D",
    "weekly": "7D",
    "monthly": "MS",
    "quarterly": "QS",
    "yearly": "YS",
}


def _finite(frame, columns, purpose):
    for column in columns:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(numeric.to_numpy(dtype=float)).all():
            raise ValueError(
                f"{purpose} requires finite values in {column!r}; explicitly prepare missing periods and save the preparation first."
            )


def _regular(frame, column, start, end, frequency, purpose):
    expected = pd.date_range(start, end, freq=frequency)
    if len(expected) == 0 or list(frame[column]) != list(expected):
        raise ValueError(
            f"{purpose} has missing, duplicate, or unaligned periods. Save an explicit regular series; do not silently discard periods."
        )


def evaluate_forecast(request, *, results, thread_id, source_id):
    saved = results.get(request.predictions_result_id, thread_id, source_id=source_id)
    if saved.truncated or saved.kind == "presentation":
        raise ValueError(
            "Forecast evaluation needs a complete analytical prediction dataset."
        )
    columns = [
        request.time_column,
        request.actual_column,
        request.candidate_column,
        request.baseline_column,
    ]
    if request.lower_bound:
        columns += [request.lower_bound, request.upper_bound]
    if missing := set(columns) - set(saved.columns):
        raise ValueError(f"Prediction columns are absent: {sorted(missing)}.")
    schema = pq.read_schema(saved.parquet_path)
    if not (
        pa.types.is_date(schema.field(request.time_column).type)
        or pa.types.is_timestamp(schema.field(request.time_column).type)
    ):
        raise ValueError(
            "Forecast periods need a typed date or timestamp; prepare text dates explicitly."
        )
    for column in columns[1:]:
        kind = schema.field(column).type
        if not (
            pa.types.is_integer(kind)
            or pa.types.is_floating(kind)
            or pa.types.is_decimal(kind)
        ):
            raise ValueError(
                f"Forecast values in {column!r} need a numeric type; save an explicit conversion before evaluating."
            )
    frame = pq.read_table(saved.parquet_path, columns=columns).to_pandas()
    time = request.time_column
    frame[time] = pd.to_datetime(frame[time], errors="raise")
    if (
        frame[time].dt.tz is not None
        or frame[time].isna().any()
        or frame[time].duplicated().any()
    ):
        raise ValueError(
            "Use one row per typed period without timezone or duplicate dates."
        )
    if not frame[time].equals(frame[time].dt.normalize()):
        raise ValueError(
            "Forecast evaluation supports calendar periods; normalize subdaily times explicitly."
        )
    frame = frame.sort_values(time)
    train = frame[
        frame[time].between(
            pd.Timestamp(request.training_start), pd.Timestamp(request.training_end)
        )
    ]
    test = frame[
        frame[time].between(
            pd.Timestamp(request.holdout_start), pd.Timestamp(request.holdout_end)
        )
    ]
    future = frame[frame[time] > pd.Timestamp(request.forecast_origin)]
    freq = (
        pd.offsets.Week(weekday=request.training_start.weekday())
        if request.frequency == "weekly"
        else FREQUENCIES[request.frequency]
    )
    _regular(
        train,
        time,
        request.training_start,
        request.training_end,
        freq,
        "Training series",
    )
    _regular(
        test, time, request.holdout_start, request.holdout_end, freq, "Holdout series"
    )
    if len(train) < 2:
        raise ValueError(
            "At least two training periods are required; save a limitation instead of an unsupported evaluation."
        )
    if len(future) != request.horizon or future.empty:
        raise ValueError(
            "The saved future predictions must match the declared horizon exactly."
        )
    following = pd.date_range(
        pd.Timestamp(request.forecast_origin), periods=2, freq=freq
    )
    start = (
        following[0]
        if following[0] > pd.Timestamp(request.forecast_origin)
        else following[1]
    )
    _regular(
        future,
        time,
        start,
        pd.date_range(start, periods=request.horizon, freq=freq)[-1],
        freq,
        "Future series",
    )
    _finite(train, [request.actual_column], "Training series")
    _finite(
        test,
        [request.actual_column, request.candidate_column, request.baseline_column],
        "Holdout scores",
    )
    _finite(future, [request.candidate_column], "Future predictions")
    if future[request.actual_column].notna().any():
        raise ValueError(
            "Future actuals must be unknown; observed values belong in the chronological holdout."
        )
    if request.lower_bound:
        _finite(
            pd.concat([test, future]),
            [request.lower_bound, request.upper_bound],
            "Interval evaluation",
        )
        if (
            pd.concat([test, future])[request.lower_bound]
            > pd.concat([test, future])[request.upper_bound]
        ).any():
            raise ValueError("Interval lower bounds exceed upper bounds.")

    def q(column):
        return exp.column(column, quoted=True).sql(dialect="duckdb")

    actual = q(request.actual_column)
    scored = []
    for column, method in [
        (request.candidate_column, request.candidate_method),
        (request.baseline_column, request.baseline_method),
    ]:
        error = f"({q(column)} - {actual})"
        coverage = (
            f"avg(CASE WHEN {actual} BETWEEN {q(request.lower_bound)} AND {q(request.upper_bound)} THEN 1.0 ELSE 0.0 END)"
            if column == request.candidate_column and request.lower_bound
            else "NULL::DOUBLE"
        )
        nominal = (
            repr(request.interval.nominal_coverage)
            if column == request.candidate_column
            and request.interval
            and request.interval.nominal_coverage is not None
            else "NULL::DOUBLE"
        )
        scored.append(
            f"SELECT {exp.Literal.string(method).sql()} AS method, count(*) AS sample_size, avg(abs({error})) AS mae, sqrt(avg(pow({error}, 2))) AS rmse, {coverage} AS measured_interval_coverage, {nominal} AS nominal_coverage FROM predictions WHERE {q(time)} BETWEEN DATE '{request.holdout_start}' AND DATE '{request.holdout_end}'"
        )
    query = " UNION ALL ".join(scored)
    with duckdb.connect(config={"enable_external_access": False}) as db:
        db.register("predictions", pq.read_table(saved.parquet_path))
        score_table = db.execute(query).to_arrow_table()
        if any(
            not np.isfinite(score_table[column].to_numpy()).all()
            for column in ("mae", "rmse")
        ):
            raise ValueError(
                "Forecast error scores must be finite. Save an explicit rescaling with declared units before evaluating these values."
            )
        scores = results.save_batches(
            score_table.to_batches(),
            thread_id=thread_id,
            source_id=source_id,
            executed_sql=query,
            kind="saved_sql",
            parent_result_ids=[saved.result_id],
            sql_bindings={"predictions": saved.result_id},
            purpose="Forecast evaluation scores",
            originating_question=saved.originating_question,
        )
    warnings = [
        "Chronological boundaries are validated; method code and preparation remain inspectable for leakage review."
    ]
    if len(test) < 5:
        warnings.append(
            "The holdout has fewer than five periods; error and measured coverage estimates are unstable."
        )
    return ForecastEvaluation(
        **request.model_dump(),
        scores_result_id=scores.result_id,
        training_count=len(train),
        evaluation_sample_size=len(test),
        forecast_start=future[time].iloc[0].date(),
        warnings=warnings,
    )
