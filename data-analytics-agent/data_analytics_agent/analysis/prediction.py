"""Small held-out regression/classification pipelines with explicit splits."""

from collections.abc import Sequence

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from data_analytics_agent.analysis._frames import (
    is_numeric,
    timestamp_value,
    timestamp_values,
)


def evaluate_prediction(
    frame: pd.DataFrame,
    *,
    target: str,
    features: Sequence[str],
    task: str,
    split: str,
    feature_availability: str,
    split_column: str | None = None,
    cutoff: str | pd.Timestamp | None = None,
    test_size: float = 0.25,
    random_state: int = 0,
    unit: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Evaluate a fixed Ridge or binary logistic candidate against a baseline.

    Splits are ``random``, ``time`` (train strictly before explicit cutoff), or
    ``group`` (no group crosses the boundary). Feature preprocessing is fitted
    only on training rows. ``feature_availability`` records the caller's account
    of information available at prediction time; this function cannot infer
    leakage from a column name. Time/group columns cannot also be model features.

    Missing targets remain in scored_rows as excluded. Feature missingness is
    imputed inside the pipeline. No tuning or final refit uses the holdout.
    Classification targets must be binary 0/1; absent holdout classes produce
    missing ROC AUC with an explicit status. Metrics are point estimates on this
    particular holdout, not a claimed probability interval or causal estimate.
    """
    features = list(features)
    if task not in {"regression", "classification"}:
        raise ValueError("task must be regression or classification")
    if split not in {"random", "time", "group"}:
        raise ValueError("split must be random, time or group")
    if not feature_availability.strip():
        raise ValueError("Declare when features are available relative to prediction")
    if not features or len(features) != len(set(features)) or target in features:
        raise ValueError("Distinct features must be supplied without the target")
    if not 0 < test_size < 1:
        raise ValueError("test_size must be between zero and one")
    if split in {"time", "group"} and (
        not split_column or split_column in features or split_column == target
    ):
        raise ValueError("Time/group splitting needs a separate split column")
    if split != "time" and cutoff is not None:
        raise ValueError("cutoff is only used by a time split")
    if split == "random" and split_column is not None:
        raise ValueError("split_column is only used by time/group splits")
    missing_target = frame[target].isna().to_numpy()
    available = np.flatnonzero(~missing_target)
    if len(available) < 4:
        raise ValueError("At least four rows with observed targets are required")
    y = pd.to_numeric(frame.iloc[available][target], errors="raise").to_numpy(
        dtype=float
    )
    if not np.isfinite(y).all():
        raise ValueError("Observed targets must be finite")
    if task == "classification" and not np.isin(y, [0, 1]).all():
        raise ValueError("Classification targets must be binary zero/one")
    split_values = None
    boundary = pd.NaT
    if split == "time":
        if cutoff is None:
            raise ValueError("Time evaluation requires an explicit cutoff")
        boundary = timestamp_value(cutoff, label="Prediction cutoff")
        split_values = timestamp_values(
            frame[split_column], label="Prediction split dates"
        )
        if pd.isna(boundary) or split_values.iloc[available].isna().any():
            raise ValueError("Observed targets require nonmissing split dates")
        before = split_values.iloc[available] < boundary
        train, test = np.flatnonzero(before), np.flatnonzero(~before)
    elif split == "group":
        split_values = frame[split_column]
        groups = split_values.iloc[available]
        if groups.isna().any() or groups.nunique() < 2:
            raise ValueError("Group split requires at least two nonmissing groups")
        train, test = next(
            GroupShuffleSplit(
                n_splits=1, test_size=test_size, random_state=random_state
            ).split(np.zeros(len(y)), y, groups=groups)
        )
    else:
        train, test = train_test_split(
            np.arange(len(y)),
            test_size=test_size,
            random_state=random_state,
            stratify=y if task == "classification" else None,
        )
    if len(train) < 2 or not len(test):
        raise ValueError(
            "Split requires at least two training rows and one holdout row"
        )
    if task == "classification" and set(y[train]) != {0.0, 1.0}:
        raise ValueError("Training split must contain both classes")
    x = frame.iloc[available][features].copy()
    numeric = [column for column in features if is_numeric(x.iloc[train][column])]
    categorical = [column for column in features if column not in numeric]
    if any(pd.api.types.is_datetime64_any_dtype(x[column]) for column in categorical):
        raise ValueError(
            "Convert date features to declared prediction-time features first"
        )
    for column in numeric:
        x[column] = pd.to_numeric(x[column], errors="raise").astype(float)
        if np.isinf(x[column].dropna()).any():
            raise ValueError("Numeric features must be finite or missing")
    for column in categorical:
        # Normalize extension dtypes/None to sklearn-compatible strings and NaN.
        x[column] = (
            x[column]
            .map(lambda value: str(value) if pd.notna(value) else np.nan)
            .astype(object)
        )
    numeric_pipeline = Pipeline(
        [
            (
                "impute",
                SimpleImputer(
                    strategy="median", add_indicator=True, keep_empty_features=True
                ),
            ),
            ("scale", StandardScaler()),
        ]
    )
    category_pipeline = Pipeline(
        [
            (
                "impute",
                SimpleImputer(strategy="most_frequent", keep_empty_features=True),
            ),
            ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=True)),
        ]
    )
    transform = ColumnTransformer(
        [
            ("numeric", numeric_pipeline, numeric),
            ("categorical", category_pipeline, categorical),
        ],
        sparse_threshold=1.0,
    )
    candidate = (
        Ridge(alpha=1.0)
        if task == "regression"
        else LogisticRegression(max_iter=1000, random_state=random_state)
    )
    model = Pipeline([("preprocess", transform), ("model", candidate)])
    baseline = (
        DummyRegressor(strategy="mean")
        if task == "regression"
        else DummyClassifier(strategy="prior", random_state=random_state)
    )
    model.fit(x.iloc[train], y[train])
    baseline.fit(np.zeros((len(train), 1)), y[train])
    predicted = model.predict(x)
    baseline_predicted = baseline.predict(np.zeros((len(y), 1)))
    probability = baseline_probability = None
    if task == "classification":
        probability = model.predict_proba(x)[:, 1]
        baseline_probability = baseline.predict_proba(np.zeros((len(y), 1)))[:, 1]
    metric_rows = []
    for name, pred, prob in [
        ("candidate", predicted, probability),
        ("baseline", baseline_predicted, baseline_probability),
    ]:
        actual = y[test]
        if task == "regression":
            measures = {
                "mae": mean_absolute_error(actual, pred[test]),
                "rmse": np.sqrt(mean_squared_error(actual, pred[test])),
                "r2": r2_score(actual, pred[test])
                if len(test) > 1 and np.var(actual) > 0
                else np.nan,
            }
        else:
            measures = {
                "accuracy": accuracy_score(actual, pred[test]),
                "balanced_accuracy": balanced_accuracy_score(actual, pred[test])
                if len(np.unique(actual)) == 2
                else np.nan,
                "roc_auc": roc_auc_score(actual, prob[test])
                if len(np.unique(actual)) == 2
                else np.nan,
                "brier_score": brier_score_loss(actual, prob[test]),
                "log_loss": log_loss(
                    actual, np.column_stack([1 - prob[test], prob[test]]), labels=[0, 1]
                ),
            }
        for metric, value in measures.items():
            metric_rows.append(
                {
                    "model": name,
                    "metric": metric,
                    "value": float(value),
                    "holdout_rows": len(test),
                    "status": "assessed"
                    if pd.notna(value)
                    else "undefined_holdout_variation",
                }
            )
    scored = pd.DataFrame(
        {
            "source_row": np.arange(len(frame)),
            "partition": np.where(missing_target, "excluded", ""),
            "actual": frame[target].to_numpy(),
            "candidate_prediction": np.nan,
            "baseline_prediction": np.nan,
            "exclusion_reason": np.where(missing_target, "missing_target", ""),
        }
    )
    scored.loc[available[train], "partition"] = "train"
    scored.loc[available[test], "partition"] = "holdout"
    scored.loc[available, "candidate_prediction"] = predicted
    scored.loc[available, "baseline_prediction"] = baseline_predicted
    if probability is not None:
        scored["candidate_probability"] = np.nan
        scored["baseline_probability"] = np.nan
        scored.loc[available, "candidate_probability"] = probability
        scored.loc[available, "baseline_probability"] = baseline_probability
    if split_values is not None:
        scored["split_value"] = split_values.to_numpy()
    feature_rows = []
    for feature in features:
        feature_rows.append(
            {
                "feature": feature,
                "kind": "numeric" if feature in numeric else "categorical",
                "train_missing": int(x.iloc[train][feature].isna().sum()),
                "holdout_missing": int(x.iloc[test][feature].isna().sum()),
            }
        )
    return {
        "prediction_scores": pd.DataFrame(metric_rows),
        "scored_rows": scored,
        "prediction_features": pd.DataFrame(feature_rows),
        "prediction_metadata": pd.DataFrame(
            [
                {
                    "task": task,
                    "target": target,
                    "features": ", ".join(features),
                    "feature_availability": feature_availability,
                    "candidate": "Ridge(alpha=1)"
                    if task == "regression"
                    else "LogisticRegression",
                    "baseline": "training mean"
                    if task == "regression"
                    else "training class prior",
                    "split": split,
                    "split_column": split_column or "",
                    "cutoff": boundary,
                    "random_state": random_state,
                    "input_rows": len(frame),
                    "train_rows": len(train),
                    "holdout_rows": len(test),
                    "missing_target_rows": int(missing_target.sum()),
                    "target_unit": "class 0/1"
                    if task == "classification"
                    else unit or "unknown",
                    "interval_meaning": "Held-out point estimates; no interval coverage claimed",
                }
            ]
        ),
    }
