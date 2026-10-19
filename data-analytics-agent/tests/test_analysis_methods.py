"""Numerical and population checks for reusable analytical methods."""

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from data_analytics_agent.analysis.customer import (
    cohort_retention,
    ordered_funnel,
    rfm_segments,
)
from data_analytics_agent.analysis.prediction import evaluate_prediction
from data_analytics_agent.analysis.scenarios import scenario_grid
from data_analytics_agent.analysis.statistical import compare_groups
from data_analytics_agent.analysis._frames import timestamp_values
from data_analytics_agent.analysis.preparation import prepare_dataset


@pytest.mark.parametrize(
    "value", ["01/02/2026", "2026/02/01", "February 1, 2026", 1769904000, "", "NaT"]
)
def test_analytical_dates_reject_inferred_formats_and_missingness(value):
    with pytest.raises(ValueError, match="explicit date-format preparation"):
        timestamp_values(pd.Series([value]))


def test_strict_dates_preserve_missingness_precision_and_explicit_utc_conversion():
    raw = pd.Series(
        [
            "2026-02-01",
            "2026-02-01T12:34:56.123456789Z",
            "2026-02-01T02:00:00+02:00",
            date(2026, 2, 1),
            pd.Timestamp("2026-02-01", tz="UTC"),
            None,
            pd.NaT,
            np.nan,
        ],
        index=range(10, 18),
        name="event_time",
    )
    parsed = timestamp_values(raw)
    assert parsed.index.equals(raw.index) and parsed.name == raw.name
    assert parsed.iloc[0] == pd.Timestamp("2026-02-01", tz="UTC")
    assert parsed.iloc[1].nanosecond == 789
    assert parsed.iloc[2] == parsed.iloc[0] == parsed.iloc[3] == parsed.iloc[4]
    assert parsed.iloc[5:].isna().all()


@pytest.mark.parametrize("location", ["cohort", "activity", "cutoff"])
def test_retention_never_guesses_ambiguous_cohort_activity_or_cutoff_dates(location):
    population = pd.DataFrame({"id": [1], "joined": ["2026-02-01"]})
    events = pd.DataFrame({"id": [1], "activity": ["2026-02-02"]})
    cutoff = "2026-03-31"
    if location == "cohort":
        population.loc[0, "joined"] = "01/02/2026"
    elif location == "activity":
        events.loc[0, "activity"] = "02/03/2026"
    else:
        cutoff = "03/04/2026"
    with pytest.raises(ValueError, match="explicit date-format preparation"):
        cohort_retention(
            population,
            events,
            entity="id",
            cohort_time="joined",
            event_time="activity",
            observation_end=cutoff,
        )


def test_explicit_day_first_preparation_preserves_intended_cohort_membership():
    population = prepare_dataset(
        pd.DataFrame({"id": [1], "joined": ["01/02/2026"]}),
        date_formats={"joined": "%d/%m/%Y"},
    )["dataset"]
    events = prepare_dataset(
        pd.DataFrame({"id": [1], "activity": ["02/03/2026"]}),
        date_formats={"activity": "%d/%m/%Y"},
    )["dataset"]
    result = cohort_retention(
        population,
        events,
        entity="id",
        cohort_time="joined",
        event_time="activity",
        observation_end="2026-03-31",
        periods=2,
    )
    assert result["cohort_members"].cohort_period.tolist() == ["2026-02"]
    assert result["retention"].active_entities.tolist() == [0, 1]


def test_funnel_and_rfm_reject_ambiguous_event_dates():
    with pytest.raises(ValueError, match="explicit date-format preparation"):
        ordered_funnel(
            pd.DataFrame({"id": [1], "entered": ["2026-02-01"]}),
            pd.DataFrame({"id": [1], "event": ["start"], "when": ["02/03/2026"]}),
            entity="id",
            entry_time="entered",
            event="event",
            event_time="when",
            steps=["start"],
            window="7D",
            observation_end="2026-03-31",
        )
    with pytest.raises(ValueError, match="explicit date-format preparation"):
        rfm_segments(
            pd.DataFrame(
                {"id": [1], "tx": [1], "when": ["02/03/2026"], "amount": [10]}
            ),
            entity="id",
            transaction_id="tx",
            transaction_time="when",
            monetary="amount",
            as_of="2026-03-31",
        )


def test_calendar_cutoff_date_includes_day_but_timestamp_remains_exact():
    population = pd.DataFrame({"id": [1], "joined": [date(2026, 2, 1)]})
    events = pd.DataFrame({"id": [1], "activity": ["2026-02-28T12:00:00Z"]})
    arguments = dict(
        entity="id", cohort_time="joined", event_time="activity", periods=1
    )
    full_day = cohort_retention(
        population, events, observation_end=date(2026, 2, 28), **arguments
    )
    midnight = cohort_retention(
        population,
        events,
        observation_end=pd.Timestamp("2026-02-28", tz="UTC"),
        **arguments,
    )
    assert full_day["retention"].active_entities.iloc[0] == 1
    assert pd.isna(midnight["retention"].active_entities.iloc[0])


def test_retention_uses_declared_cohorts_and_censors_calendar_cells():
    population = pd.DataFrame(
        {
            "customer": ["a", "b", "c"],
            "joined": ["2024-01-01", "2024-01-15", "2024-02-05"],
        }
    )
    events = pd.DataFrame(
        {
            "customer": ["a", "a", "a", "b", "c", "outside", None],
            "occurred": [
                "2024-01-02",
                "2024-02-06",
                "2024-03-01",
                "2024-01-20",
                "2024-02-20",
                "2024-01-01",
                "2024-01-01",
            ],
        }
    )
    result = cohort_retention(
        population,
        events,
        entity="customer",
        cohort_time="joined",
        event_time="occurred",
        observation_end="2024-03-31T23:59:59.999999999Z",
        periods=3,
    )
    retention = result["retention"].set_index(["cohort_period", "period_age"])
    assert retention.loc[("2024-01", 0), "retention_rate"] == 1
    assert retention.loc[("2024-01", 1), "retention_rate"] == 0.5
    assert retention.loc[("2024-02", 1), "retention_rate"] == 0
    assert pd.isna(retention.loc[("2024-02", 2), "active_entities"])
    assert pd.isna(retention.loc[("2024-02", 2), "retention_rate"])
    assert len(result["cohort_members"]) == 3
    assert result["retention_metadata"].iloc[0]["outside_population_rows"] == 1
    assert result["retention_metadata"].iloc[0]["missing_entity_or_date_rows"] == 1


def test_retention_partial_period_is_not_zero_and_preactivity_is_ignored():
    population = pd.DataFrame({"id": [1], "start": ["2024-01-15"]})
    events = pd.DataFrame({"id": [1, 1], "when": ["2024-01-01", "2024-02-01"]})
    output = cohort_retention(
        population,
        events,
        entity="id",
        cohort_time="start",
        event_time="when",
        observation_end="2024-02-15",
        periods=2,
    )["retention"]
    assert output.iloc[0]["active_entities"] == 0
    assert pd.isna(output.iloc[1]["active_entities"])


def test_customer_population_requires_unique_nonmissing_entities():
    with pytest.raises(ValueError, match="one nonmissing"):
        cohort_retention(
            pd.DataFrame({"id": [1, 1], "start": ["2024-01-01"] * 2}),
            pd.DataFrame({"id": [], "when": []}),
            entity="id",
            cohort_time="start",
            event_time="when",
            observation_end="2024-02-01",
        )


def test_funnel_has_strict_order_fixed_entry_window_and_censoring():
    population = pd.DataFrame(
        {
            "id": ["a", "b", "c", "d"],
            "entered": ["2024-01-01", "2024-01-01", "2024-01-01", "2024-01-18"],
        }
    )
    events = pd.DataFrame(
        {
            "id": ["a", "a", "b", "b", "b", "c", "c", "d", "d"],
            "event": [
                "view",
                "buy",
                "buy",
                "view",
                "buy",
                "view",
                "buy",
                "view",
                "buy",
            ],
            "when": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-01",
                "2024-01-02",
                "2024-01-09",
                "2024-01-03",
                "2024-01-03",
                "2024-01-18",
                "2024-01-19",
            ],
        }
    )
    output = ordered_funnel(
        population,
        events,
        entity="id",
        entry_time="entered",
        event="event",
        event_time="when",
        steps=["view", "buy"],
        window="7D",
        observation_end="2024-01-20",
    )
    assert output["funnel"]["eligible_entities"].tolist() == [3, 3]
    assert output["funnel"]["reached_entities"].tolist() == [3, 1]
    assert output["funnel"].iloc[-1]["conversion_from_entry"] == pytest.approx(1 / 3)
    entities = output["funnel_entities"].set_index("entity_id")
    assert entities.loc["b", "steps_reached"] == 1
    assert entities.loc["c", "steps_reached"] == 1
    assert entities.loc["d", "steps_reached"] == 2
    assert not entities.loc["d", "is_observed"]
    assert len(entities) == len(population)


def test_funnel_all_censored_has_undefined_rates():
    result = ordered_funnel(
        pd.DataFrame({"id": [1], "entered": ["2024-01-01"]}),
        pd.DataFrame({"id": [1], "event": ["start"], "when": ["2024-01-01"]}),
        entity="id",
        entry_time="entered",
        event="event",
        event_time="when",
        steps=["start", "finish"],
        window="7D",
        observation_end="2024-01-02",
    )
    assert result["funnel"]["eligible_entities"].eq(0).all()
    assert result["funnel"]["conversion_from_entry"].isna().all()


def test_rfm_preserves_missingness_and_transaction_grain():
    transactions = pd.DataFrame(
        {
            "id": ["a", "a", "b", "c", "d"],
            "tx": [1, 2, 3, 4, 5],
            "when": ["2024-01-01", "2024-01-09", "2024-01-01", "2024-01-02", None],
            "amount": [10, 20, 5, None, 40],
        }
    )
    output = rfm_segments(
        transactions,
        entity="id",
        transaction_id="tx",
        transaction_time="when",
        monetary="amount",
        as_of="2024-01-10",
    )
    entities = output["rfm_entities"].set_index("entity_id")
    assert entities.loc["a", "recency_days"] == 1
    assert entities.loc["a", "frequency"] == 2
    assert entities.loc["a", "monetary"] == 30
    assert entities.loc["a", "recency_score"] > entities.loc["b", "recency_score"]
    assert pd.isna(entities.loc["c", "monetary"])
    assert entities.loc["c", "segment"] == "unassessed"
    assert entities.loc["d", "frequency"] == 0
    assert entities.loc["d", "segment"] == "unassessed"
    assert output["segment_profiles"]["entities"].sum() == 4
    assert output["segmentation_metadata"].iloc[0]["monetary_unit"] == "unknown"
    with pytest.raises(ValueError, match="aggregate lines first"):
        rfm_segments(
            pd.concat([transactions, transactions.iloc[[0]]]),
            entity="id",
            transaction_id="tx",
            transaction_time="when",
            monetary="amount",
            as_of="2024-01-10",
        )


def test_rfm_preserves_exact_monetary_values_and_close_rank_differences():
    import pyarrow as pa

    transactions = pd.DataFrame(
        {
            "id": ["a", "b"],
            "tx": [1, 2],
            "when": ["2024-01-01"] * 2,
            "amount": [
                Decimal("10000000000000000.01"),
                Decimal("10000000000000000.02"),
            ],
        }
    )
    output = rfm_segments(
        transactions,
        entity="id",
        transaction_id="tx",
        transaction_time="when",
        monetary="amount",
        as_of="2024-01-02",
    )
    entities = output["rfm_entities"].set_index("entity_id")
    assert entities.loc["a", "monetary"] == Decimal("10000000000000000.01")
    assert entities.loc["b", "monetary"] == Decimal("10000000000000000.02")
    assert entities.loc["a", "monetary_score"] < entities.loc["b", "monetary_score"]
    for table in output.values():
        pa.Table.from_pandas(table, preserve_index=False)


@pytest.mark.parametrize("scale", [1e-200, 1e200])
def test_numeric_inference_is_invariant_to_rescaling_without_variance_overflow(scale):
    frame = pd.DataFrame(
        {
            "group": [0, 0, 0, 1, 1, 1],
            "value": scale * np.array([1.0, 2.0, 3.0, 3.0, 4.0, 5.0]),
        }
    )
    effect = compare_groups(
        frame, group="group", outcome="value", reference=0, comparison=1
    )["group_comparison"].iloc[0]
    expected_p = stats.ttest_ind(
        [3.0, 4.0, 5.0], [1.0, 2.0, 3.0], equal_var=False
    ).pvalue
    expected_half_width = stats.t.ppf(0.975, df=4) * np.sqrt(2 / 3)
    assert effect["status"] == "assessed"
    assert effect["estimate"] == pytest.approx(2 * scale, rel=1e-12, abs=0)
    assert effect["ci_lower"] == pytest.approx(
        (2 - expected_half_width) * scale, rel=1e-12, abs=0
    )
    assert effect["ci_upper"] == pytest.approx(
        (2 + expected_half_width) * scale, rel=1e-12, abs=0
    )
    assert effect["p_value"] == pytest.approx(expected_p)
    assert np.isfinite(effect["hedges_g"])


def test_numeric_inference_centers_exact_decimals_before_float_conversion():
    values = [
        Decimal("10000000000000000." + cents)
        for cents in ["10", "20", "30", "30", "40", "50"]
    ]
    effect = compare_groups(
        pd.DataFrame({"g": [0, 0, 0, 1, 1, 1], "y": values}),
        group="g",
        outcome="y",
        reference=0,
        comparison=1,
    )["group_comparison"].iloc[0]
    assert effect["estimate"] == pytest.approx(0.2)
    assert effect["status"] == "assessed"
    assert effect["p_value"] == pytest.approx(
        stats.ttest_ind([3, 4, 5], [1, 2, 3], equal_var=False).pvalue
    )


@pytest.mark.parametrize("reference", [None, np.nan, pd.NA])
def test_missing_reference_labels_cannot_be_marked_as_analyzed_groups(reference):
    with pytest.raises(ValueError, match="nonmissing groups"):
        compare_groups(
            pd.DataFrame({"g": [None, None, 1, 1], "y": [1, 2, 3, 4]}),
            group="g",
            outcome="y",
            reference=reference,
            comparison=1,
        )


def test_numeric_comparison_effect_welch_interval_and_sample_accounting():
    frame = pd.DataFrame(
        {
            "group": ["a"] * 5 + ["b"] * 4 + ["other"],
            "value": [1, 2, 3, 4, None, 3, 4, 5, 6, 1000],
        }
    )
    output = compare_groups(
        frame, group="group", outcome="value", reference="a", comparison="b"
    )
    effect = output["group_comparison"].iloc[0]
    assert effect["estimate"] == pytest.approx(2)
    standard_error = np.sqrt(2 * np.var([1, 2, 3, 4], ddof=1) / 4)
    expected_half_width = stats.t.ppf(0.975, df=6) * standard_error
    assert effect["ci_lower"] == pytest.approx(2 - expected_half_width)
    assert effect["ci_upper"] == pytest.approx(2 + expected_half_width)
    assert effect["hedges_g"] > 0
    assert output["group_samples"]["analyzed_rows"].tolist() == [4, 4]
    assert output["comparison_population"]["is_analyzed"].sum() == 8
    assert len(output["comparison_population"]) == len(frame)
    assert effect["outcome_unit"] == "unknown"


def test_numeric_constant_and_insufficient_samples_do_not_invent_certainty():
    effect = compare_groups(
        pd.DataFrame({"g": [0, 0, 1, 1], "y": [1, 1, 2, 2]}),
        group="g",
        outcome="y",
        reference=0,
        comparison=1,
    )["group_comparison"].iloc[0]
    assert effect["estimate"] == 1
    assert effect["status"] == "undefined_zero_variance"
    assert pd.isna(effect["p_value"])
    absent = compare_groups(
        pd.DataFrame({"g": [0], "y": [1]}),
        group="g",
        outcome="y",
        reference=0,
        comparison=1,
    )["group_comparison"].iloc[0]
    assert absent["status"] == "insufficient_data"
    assert pd.isna(absent["estimate"])


def test_binary_effect_interval_handles_all_zero_and_small_samples():
    output = compare_groups(
        pd.DataFrame({"g": [0] * 4 + [1] * 4, "y": [0, 0, 1, 0, 1, 1, 1, 0]}),
        group="g",
        outcome="y",
        reference=0,
        comparison=1,
        kind="binary",
    )["group_comparison"].iloc[0]
    assert output["estimate"] == 0.5
    assert output["ci_lower"] < 0.5 < output["ci_upper"]
    zeros = compare_groups(
        pd.DataFrame({"g": [0, 0, 1, 1], "y": [0, 0, 0, 0]}),
        group="g",
        outcome="y",
        reference=0,
        comparison=1,
        kind="binary",
    )["group_comparison"].iloc[0]
    assert zeros["p_value"] == 1
    assert zeros["ci_lower"] < 0 < zeros["ci_upper"]


def test_group_comparison_rejects_repeated_units_and_nonbinary_outcomes():
    with pytest.raises(ValueError, match="unique nonmissing"):
        compare_groups(
            pd.DataFrame({"g": [0, 1], "y": [0, 1], "id": [1, 1]}),
            group="g",
            outcome="y",
            reference=0,
            comparison=1,
            unit_id="id",
        )
    with pytest.raises(ValueError, match="zero or one"):
        compare_groups(
            pd.DataFrame({"g": [0, 1], "y": [0, 2]}),
            group="g",
            outcome="y",
            reference=0,
            comparison=1,
            kind="binary",
        )


def _prediction_frame():
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=40, tz="UTC"),
            "x": np.arange(40, dtype=float),
            "category": ["one", "two"] * 20,
            "y": np.arange(40, dtype=float) * 3 + 7,
        }
    )


@pytest.mark.parametrize("location", ["split_column", "cutoff"])
def test_prediction_time_split_never_guesses_ambiguous_dates(location):
    frame = _prediction_frame()
    cutoff = "2024-02-01"
    if location == "split_column":
        frame["date"] = frame.date.astype(object)
        frame.loc[0, "date"] = "01/02/2024"
    else:
        cutoff = "02/01/2024"
    with pytest.raises(ValueError, match="explicit date-format preparation"):
        evaluate_prediction(
            frame,
            target="y",
            features=["x"],
            task="regression",
            split="time",
            split_column="date",
            cutoff=cutoff,
            feature_availability="Known before outcome",
        )


def test_prediction_time_split_metrics_and_missing_targets_are_saved():
    frame = _prediction_frame()
    frame.loc[3, "y"] = np.nan
    frame.loc[4, "x"] = np.nan
    output = evaluate_prediction(
        frame,
        target="y",
        features=["x", "category"],
        task="regression",
        split="time",
        split_column="date",
        cutoff="2024-02-01",
        feature_availability="Measurements available before the target is observed",
    )
    scored = output["scored_rows"]
    assert len(scored) == 40
    assert scored.loc[3, "partition"] == "excluded"
    assert scored.loc[3, "exclusion_reason"] == "missing_target"
    assert scored.loc[31, "partition"] == "holdout"
    assert scored.loc[:30, "partition"].isin(["train", "excluded"]).all()
    metrics = output["prediction_scores"].set_index(["model", "metric"])
    actual = scored.loc[scored["partition"].eq("holdout")]
    expected_mae = (actual["actual"] - actual["candidate_prediction"]).abs().mean()
    assert metrics.loc[("candidate", "mae"), "value"] == pytest.approx(expected_mae)
    assert (
        metrics.loc[("candidate", "mae"), "value"]
        < metrics.loc[("baseline", "mae"), "value"]
    )
    assert output["prediction_metadata"].iloc[0]["target_unit"] == "unknown"


def test_prediction_decimal_features_keep_numeric_meaning_and_float_parity():
    frame = _prediction_frame()
    arguments = dict(
        target="y",
        features=["x", "category"],
        task="regression",
        split="time",
        split_column="date",
        cutoff="2024-02-01",
        feature_availability="Known at prediction time",
    )
    expected = evaluate_prediction(frame, **arguments)
    frame["x"] = frame.x.map(lambda value: Decimal(str(value)))
    actual = evaluate_prediction(frame, **arguments)
    assert (
        actual["prediction_features"].set_index("feature").loc["x", "kind"] == "numeric"
    )
    np.testing.assert_allclose(
        actual["scored_rows"].candidate_prediction,
        expected["scored_rows"].candidate_prediction,
    )


def test_prediction_training_and_preprocessing_do_not_see_holdout():
    frame = _prediction_frame()
    frame.loc[0, "x"] = np.nan
    arguments = dict(
        target="y",
        features=["x", "category"],
        task="regression",
        split="time",
        split_column="date",
        cutoff="2024-02-01",
        feature_availability="Known at prediction time",
    )
    first = evaluate_prediction(frame, **arguments)["scored_rows"]
    changed = frame.copy()
    changed.loc[31:, "x"] = 1e10
    changed.loc[31:, "y"] = -1e10
    changed.loc[31:, "category"] = "unseen_in_training"
    second = evaluate_prediction(changed, **arguments)["scored_rows"]
    np.testing.assert_allclose(
        first.loc[:30, "candidate_prediction"], second.loc[:30, "candidate_prediction"]
    )
    np.testing.assert_allclose(
        first.loc[:30, "baseline_prediction"], second.loc[:30, "baseline_prediction"]
    )


def test_prediction_group_split_preserves_groups_and_reproducibility():
    frame = _prediction_frame()
    frame["subject"] = np.repeat(np.arange(10), 4)
    arguments = dict(
        target="y",
        features=["x"],
        task="regression",
        split="group",
        split_column="subject",
        feature_availability="Known at prediction time",
        random_state=18,
    )
    first = evaluate_prediction(frame, **arguments)["scored_rows"]
    second = evaluate_prediction(frame, **arguments)["scored_rows"]
    assert first.groupby("split_value")["partition"].nunique().eq(1).all()
    pd.testing.assert_frame_equal(first, second)


def test_binary_prediction_records_probabilities_and_undefined_auc():
    frame = _prediction_frame()
    frame["y"] = (frame["x"] >= 15).astype(int)
    output = evaluate_prediction(
        frame,
        target="y",
        features=["x"],
        task="classification",
        split="time",
        split_column="date",
        cutoff="2024-02-01",
        feature_availability="Known at prediction time",
    )
    scores = output["prediction_scores"].set_index(["model", "metric"])
    assert pd.isna(scores.loc[("candidate", "roc_auc"), "value"])
    assert (
        scores.loc[("candidate", "roc_auc"), "status"] == "undefined_holdout_variation"
    )
    assert np.isfinite(scores.loc[("candidate", "log_loss"), "value"])
    assert output["scored_rows"]["candidate_probability"].between(0, 1).all()
    assert output["prediction_metadata"].iloc[0]["baseline"] == "training class prior"


def test_prediction_rejects_target_leakage_and_invalid_split():
    frame = _prediction_frame()
    with pytest.raises(ValueError, match="without the target"):
        evaluate_prediction(
            frame,
            target="y",
            features=["x", "y"],
            task="regression",
            split="random",
            feature_availability="Known at prediction time",
        )
    with pytest.raises(ValueError, match="explicit cutoff"):
        evaluate_prediction(
            frame,
            target="y",
            features=["x"],
            task="regression",
            split="time",
            split_column="date",
            feature_availability="Known at prediction time",
        )
    with pytest.raises(ValueError, match="both classes"):
        evaluate_prediction(
            frame.assign(y=0),
            target="y",
            features=["x"],
            task="classification",
            split="time",
            split_column="date",
            cutoff="2024-02-01",
            feature_availability="Known at prediction time",
        )


def test_scenarios_retain_assumptions_and_undefined_arithmetic():
    result = scenario_grid(
        {"price": [10, 20], "volume": [0, 2]},
        lambda price, volume: price / volume,
        formula_description="price / volume",
        outcome="ratio",
    )
    rows = result["scenarios"]
    assert len(rows) == 4
    assert rows["status"].eq("undefined").sum() == 2
    assert rows.loc[rows["volume"].eq(2), "ratio"].tolist() == [5, 10]
    summary = result["scenario_summary"].iloc[0]
    assert summary["minimum"] == 5
    assert summary["maximum"] == 10
    assert summary["unit"] == "unknown"
    assert "no probability coverage" in summary["range_meaning"]


def test_scenarios_reject_nonfinite_assumptions_and_name_collisions():
    with pytest.raises(ValueError, match="finite numeric"):
        scenario_grid(
            {"price": [np.nan]}, lambda price: price, formula_description="price"
        )
    with pytest.raises(ValueError, match="distinct"):
        scenario_grid(
            {"price": [1]},
            lambda price: price,
            formula_description="price",
            outcome="price",
        )
