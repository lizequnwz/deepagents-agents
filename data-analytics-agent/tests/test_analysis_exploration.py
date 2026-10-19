from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from data_analytics_agent.analysis.diagnostics import decompose_change, reconcile_tables
from data_analytics_agent.analysis.exploration import compare_groups, explore_dataset
from data_analytics_agent.analysis.preparation import prepare_dataset


def test_exploration_uses_complete_population_and_pairwise_denominators():
    frame = pd.DataFrame(
        {
            "x": [1.0, 2.0, 3.0, np.nan, np.inf],
            "y": [2.0, 4.0, 6.0, 8.0, 10.0],
            "category": ["a", "a", "b", None, "c"],
        }
    )
    tables = explore_dataset(frame, top_categories=2)
    assert tables["overview"].iloc[0].row_count == 5
    numeric = tables["numeric_summary"].set_index("column")
    assert numeric.loc["x", "finite_count"] == 3
    assert numeric.loc["x", "nonfinite_count"] == 1
    assert numeric.loc["x", "mean"] == 2
    correlations = tables["correlations"].iloc[0]
    assert correlations.pair_count == 3
    assert correlations.pearson == pytest.approx(1)
    assert correlations.spearman == pytest.approx(1)
    counts, remainder = (
        tables["categorical_counts"],
        tables["categorical_remainder"].iloc[0],
    )
    assert counts["count"].sum() + remainder.omitted_rows == 5
    assert remainder.omitted_categories == 2
    assert tables["columns"].set_index("column").loc["category", "missing_count"] == 1
    assert tables["overview"].iloc[0].source_completeness == "unknown"


def test_exploration_selected_columns_and_duplicates_are_explicit():
    frame = pd.DataFrame({"x": [2.0, 2.0, 3.0], "ignored": ["a", "b", "c"]})
    tables = explore_dataset(frame, columns=["x"])
    assert list(tables["columns"]["column"]) == ["x"]
    assert tables["overview"].iloc[0].duplicate_rows == 1
    assert tables["overview"].iloc[0].duplicate_members == 2
    assert tables["categorical_counts"].empty


def test_exploration_retains_null_categories_and_undefined_correlations():
    frame = pd.DataFrame(
        {
            "x": pd.Series([None, None], dtype="Float64"),
            "y": [1.0, 1.0],
            "label": [None, "a"],
        }
    )
    tables = explore_dataset(frame)
    assert tables["categorical_counts"].loc[lambda d: d.is_missing, "count"].sum() == 1
    assert tables["correlations"].iloc[0].pair_count == 0
    assert pd.isna(tables["correlations"].iloc[0].pearson)
    assert tables["numeric_summary"].set_index("column").loc["x", "finite_count"] == 0


def test_exploration_decimal_values_and_empty_tables():
    tables = explore_dataset(
        pd.DataFrame({"amount": [Decimal("1.10"), Decimal("2.20"), None]})
    )
    assert tables["numeric_summary"].iloc[0]["mean"] == pytest.approx(1.65)
    empty = explore_dataset(pd.DataFrame({"value": pd.Series(dtype="float64")}))
    assert empty["overview"].iloc[0].row_count == 0
    assert empty["correlations"].empty
    assert empty["numeric_summary"].iloc[0].finite_count == 0


def test_exploration_outputs_with_different_category_types_can_be_saved_as_arrow():
    import pyarrow as pa

    frame = pd.DataFrame({"label": ["a", "b"], "flag": [True, False]})
    tables = explore_dataset(frame)
    for table in tables.values():
        pa.Table.from_pandas(table, preserve_index=False)
    counts = tables["categorical_counts"]
    assert set(counts.category_type) == {"str", "bool"}


def test_explicit_time_coverage_preserves_local_calendar_and_unknown_completeness():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2025-01-31 23:00", "2025-01-31 23:00", "2025-03-01 00:00"]
            ).tz_localize("America/New_York"),
            "x": [1, 2, 3],
        }
    )
    tables = explore_dataset(frame, date_column="date", frequency="M")
    coverage = tables["time_coverage"].iloc[0]
    assert coverage.duplicate_timestamps == 1
    assert coverage.source_completeness == "unknown"
    assert tables["time_gaps"]["period"].tolist() == ["2025-02"]
    assert tables["time_periods"].observed_rows.tolist() == [2, 0, 1]
    assert not any(name.startswith("time_") for name in explore_dataset(frame))


def test_date_exploration_does_not_guess_formats_or_accept_frequency_without_date():
    frame = pd.DataFrame({"date": ["01/02/2025"]})
    with pytest.raises(ValueError, match="explicitly parsed"):
        explore_dataset(frame, date_column="date")
    with pytest.raises(ValueError, match="explicit date_column"):
        explore_dataset(frame, frequency="D")


def test_group_comparison_retains_missing_groups_values_and_effect_denominators():
    frame = pd.DataFrame(
        {
            "segment": ["a", "a", "b", "b", "b", None],
            "value": [1.0, 3.0, 2.0, 8.0, None, 5.0],
        }
    )
    tables = compare_groups(frame, group="segment", value="value", reference_group="a")
    groups = tables["groups"].set_index("group")
    assert groups.loc["a", "mean"] == 2
    assert groups.loc["b", "row_count"] == 3
    assert groups.loc["b", "observed_count"] == 2
    assert groups.loc["b", "missing_count"] == 1
    assert groups.row_count.sum() == len(frame)
    effects = tables["comparisons"].set_index("group")
    assert effects.loc["b", "mean_difference"] == 3
    assert effects.loc["b", "mean_ratio"] == 2.5
    assert effects.loc["b", "median_difference"] == 3


def test_group_comparison_zero_and_missing_reference_means_are_undefined():
    frame = pd.DataFrame({"mean": ["a", "a", "b"], "x": [-1.0, 1.0, 3.0]})
    tables = compare_groups(frame, group="mean", value="x", reference_group="a")
    assert tables["comparisons"].mean_ratio.isna().all()
    with pytest.raises(ValueError, match="observed, non-null"):
        compare_groups(frame, group="mean", value="x", reference_group="missing")


def test_reconciliation_does_not_hide_same_total_different_groups():
    current = pd.DataFrame({"key": ["a", "b"], "amount": [20.0, 10.0]})
    baseline = pd.DataFrame({"key": ["b", "a"], "amount": [20.0, 10.0]})
    result = reconcile_tables(current, baseline, keys=["key"], value="amount")
    summary = result["summary"].iloc[0]
    assert summary.total_difference == 0
    assert summary.different_groups == 2
    assert not summary.all_groups_match
    assert result["rows"].difference.sum() == 0


def test_unmatched_and_observed_nulls_remain_distinct():
    current = pd.DataFrame(
        {"key": ["a", "new", "unknown"], "amount": [20.0, 5.0, None]}
    )
    baseline = pd.DataFrame(
        {"key": ["a", "old", "unknown"], "amount": [10.0, 7.0, None]}
    )
    unknown = reconcile_tables(current, baseline, keys=["key"], value="amount")
    assert unknown["summary"].iloc[0].unassessed_groups == 3
    assert pd.isna(unknown["summary"].iloc[0].current_total)
    explicit = reconcile_tables(
        current, baseline, keys=["key"], value="amount", unmatched="zero"
    )
    rows = explicit["rows"].set_index("key")
    assert rows.loc["new", "difference"] == 5
    assert rows.loc["old", "difference"] == -7
    assert pd.isna(rows.loc["unknown", "difference"])
    assert pd.isna(rows.loc["unknown", "matches"])


def test_change_contributions_reconcile_new_and_lost_groups_only_under_explicit_policy():
    current = pd.DataFrame({"key": ["a", "new"], "amount": [15.0, 8.0]})
    baseline = pd.DataFrame({"key": ["a", "old"], "amount": [10.0, 3.0]})
    unknown = decompose_change(current, baseline, keys=["key"], value="amount")
    assert not unknown["summary"].iloc[0].reconciled
    assert unknown["summary"].iloc[0].unallocated_difference == 5
    result = decompose_change(
        current, baseline, keys=["key"], value="amount", unmatched="zero"
    )
    summary = result["summary"].iloc[0]
    assert summary.current_total == 23
    assert summary.baseline_total == 13
    assert summary.total_difference == 10
    assert summary.known_contribution_sum == 10
    assert summary.reconciled
    assert summary.unallocated_difference == 0
    assert result["contributions"].share_of_total_change.sum() == 1
    assert pd.isna(
        result["contributions"].set_index("key").loc["new", "relative_change"]
    )


def test_change_preserves_decimal_amounts_null_keys_and_zero_change():
    current = pd.DataFrame(
        {"key": [None, "a"], "amount": [Decimal("0.10"), Decimal("0.20")]}
    )
    baseline = pd.DataFrame(
        {"key": [None, "a"], "amount": [Decimal("0.20"), Decimal("0.10")]}
    )
    result = decompose_change(current, baseline, keys=["key"], value="amount")
    assert result["summary"].iloc[0].current_total == Decimal("0.30")
    assert result["summary"].iloc[0].total_difference == Decimal("0.00")
    assert result["contributions"].share_of_total_change.isna().all()
    assert result["summary"].iloc[0].matched_groups == 2


@pytest.mark.parametrize("function", [reconcile_tables, decompose_change])
def test_reconciliation_rejects_duplicate_grain_and_text_measures(function):
    duplicate = pd.DataFrame({"key": ["a", "a"], "amount": [1.0, 2.0]})
    with pytest.raises(ValueError, match="duplicate grouping keys"):
        function(duplicate, duplicate, keys=["key"], value="amount")
    text = pd.DataFrame({"key": ["a"], "amount": ["1.00"]})
    with pytest.raises(ValueError, match="numeric values"):
        function(text, text, keys=["key"], value="amount")


def test_reconciliation_has_explicit_finite_tolerances():
    current = pd.DataFrame({"key": [1], "value": [1.01]})
    baseline = pd.DataFrame({"key": [1], "value": [1.0]})
    result = reconcile_tables(
        current, baseline, keys=["key"], value="value", atol=0.02, rtol=0
    )
    assert result["rows"].matches.iloc[0]
    with pytest.raises(ValueError, match="Tolerances"):
        reconcile_tables(current, baseline, keys=["key"], value="value", atol=np.nan)


def test_reconciliation_integer_totals_do_not_wrap_and_outputs_remain_saveable():
    import pyarrow as pa

    current = pd.DataFrame({"key": ["a", "b"], "amount": [2**62, 2**62]})
    baseline = pd.DataFrame({"key": ["a", "b"], "amount": [0, 0]})
    result = decompose_change(current, baseline, keys=["key"], value="amount")
    assert result["summary"].current_total.iloc[0] == 2**63
    assert result["summary"].total_difference.iloc[0] == 2**63
    assert result["summary"].known_contribution_sum.iloc[0] == 2**63
    assert result["summary"].reconciled.iloc[0]
    assert result["contributions"].share_of_total_change.tolist() == [0.5, 0.5]
    for table in result.values():
        pa.Table.from_pandas(table, preserve_index=False)


def test_outer_reconciliation_never_rounds_integer_evidence_through_float():
    import pyarrow as pa

    current = pd.DataFrame({"key": ["a", "new"], "amount": [2**53 + 1, 1]})
    baseline = pd.DataFrame({"key": ["a", "old"], "amount": [2**53, 1]})
    result = reconcile_tables(
        current, baseline, keys=["key"], value="amount", atol=0, rtol=0
    )
    matched = result["rows"].set_index("key").loc["a"]
    assert matched.current_value == 2**53 + 1
    assert matched.difference == 1
    assert not matched.matches
    pa.Table.from_pandas(result["rows"], preserve_index=False)
    changed = decompose_change(
        current, baseline, keys=["key"], value="amount", unmatched="zero"
    )
    assert changed["summary"].total_difference.iloc[0] == 1
    assert changed["summary"].known_contribution_sum.iloc[0] == 1
    assert changed["summary"].reconciled.iloc[0]


def test_unsigned_values_beyond_int64_are_exact_and_portable():
    import pyarrow as pa

    current = pd.DataFrame(
        {"key": ["a"], "amount": pd.Series([2**63 + 1], dtype="uint64")}
    )
    baseline = pd.DataFrame({"key": ["a"], "amount": [0]})
    result = reconcile_tables(
        current, baseline, keys=["key"], value="amount", atol=0, rtol=0
    )
    assert result["rows"].current_value.iloc[0] == 2**63 + 1
    assert result["rows"].difference.iloc[0] == 2**63 + 1
    for table in result.values():
        pa.Table.from_pandas(table, preserve_index=False)


def test_decimal_reconciliation_respects_zero_tolerance_and_full_precision():
    current = pd.DataFrame({"key": ["a"], "amount": [Decimal("10000000000000000.01")]})
    baseline = pd.DataFrame({"key": ["a"], "amount": [Decimal("10000000000000000.02")]})
    result = reconcile_tables(
        current, baseline, keys=["key"], value="amount", atol=0, rtol=0
    )
    assert not result["rows"].matches.iloc[0]
    assert result["rows"].difference.iloc[0] == Decimal("-0.01")
    current = pd.DataFrame(
        {
            "key": ["a", "b"],
            "amount": [Decimal("1234567890123456789012345678.91"), Decimal("0.02")],
        }
    )
    baseline = pd.DataFrame(
        {
            "key": ["a", "b"],
            "amount": [Decimal("1234567890123456789012345678.90"), Decimal("0.01")],
        }
    )
    changed = decompose_change(current, baseline, keys=["key"], value="amount")
    assert changed["summary"].current_total.iloc[0] == Decimal(
        "1234567890123456789012345678.93"
    )
    assert changed["summary"].total_difference.iloc[0] == Decimal("0.02")
    assert changed["summary"].unallocated_difference.iloc[0] == Decimal("0.00")


def test_floating_arithmetic_rejects_nonfinite_totals_instead_of_wrapping():
    current = pd.DataFrame({"key": ["a", "b"], "amount": [1e308, 1e308]})
    baseline = pd.DataFrame({"key": ["a", "b"], "amount": [0.0, 0.0]})
    with pytest.raises(ValueError, match="rescale"):
        reconcile_tables(current, baseline, keys=["key"], value="amount")


@pytest.mark.parametrize("value", [20260201, "20260201", 1769904000])
def test_iso_preparation_rejects_implicit_numeric_or_compact_date_interpretation(value):
    with pytest.raises(ValueError, match="explicit date-format preparation"):
        prepare_dataset(
            pd.DataFrame({"when": [value]}), date_formats={"when": "ISO8601"}
        )
    explicit = prepare_dataset(
        pd.DataFrame({"when": [20260201]}), date_formats={"when": "%Y%m%d"}
    )
    assert explicit["dataset"].when.iloc[0] == pd.Timestamp("2026-02-01")


def test_preparation_defaults_are_identity_without_mutating_input():
    frame = pd.DataFrame({"key": [1, 1], "value": [None, 2.0]})
    result = prepare_dataset(frame)
    assert_frame_equal(result["dataset"], frame)
    assert result["operations"].empty
    result["dataset"].loc[0, "value"] = 99
    assert pd.isna(frame.loc[0, "value"])


def test_preparation_explicit_pipeline_and_audit_preserve_original():
    frame = pd.DataFrame(
        {
            "key": [1, 1, 2, 3],
            "amount": ["2", "3", None, "8"],
            "cost": [1, 1, 1, 2],
            "date": ["01/02/2025"] * 4,
        }
    )
    original = frame.copy(deep=True)
    result = prepare_dataset(
        frame,
        conversions={"amount": "Float64"},
        date_formats={"date": "%d/%m/%Y"},
        derived={"margin": lambda data: data.amount - data.cost},
        fill_values={"amount": 0},
        drop_missing=["margin"],
        deduplicate_by=["key"],
        deduplicate_keep="last",
    )
    data = result["dataset"]
    assert data.key.tolist() == [1, 3]
    assert data.margin.tolist() == [2.0, 6.0]
    assert data.date.dt.month.tolist() == [2, 2]
    assert_frame_equal(frame, original)
    audit = result["operations"]
    assert audit.operation.tolist() == [
        "convert",
        "parse_datetime",
        "derive",
        "fill_missing",
        "drop_missing",
        "deduplicate",
    ]
    assert audit.iloc[-1].rows_before == 3
    assert audit.iloc[-1].rows_after == 2
    assert audit.iloc[-2].affected_rows == 1


def test_preparation_conversion_errors_and_ambiguous_dates_are_not_silently_coerced():
    frame = pd.DataFrame({"amount": ["2", "bad"], "date": ["01/02/2025", "01/03/2025"]})
    with pytest.raises(ValueError):
        prepare_dataset(frame, conversions={"amount": "numeric"})
    with pytest.raises(ValueError, match="explicit date format"):
        prepare_dataset(frame, conversions={"date": "datetime"})
    with pytest.raises(ValueError, match="not mixed"):
        prepare_dataset(frame, date_formats={"date": "mixed"})
    assert frame.amount.tolist() == ["2", "bad"]


@pytest.mark.parametrize(
    "dtype",
    [
        "M8[ns]",
        "datetime64[ns]",
        "datetime64[ns, UTC]",
        "date32[pyarrow]",
        "timestamp[ns][pyarrow]",
    ],
)
def test_datetime_dtype_aliases_require_explicit_date_formats(dtype):
    frame = pd.DataFrame({"when": ["01/02/2026"]})
    with pytest.raises(ValueError, match="explicit date format"):
        prepare_dataset(frame, conversions={"when": dtype})
    prepared = prepare_dataset(
        frame,
        conversions={"when": dtype},
        date_formats={"when": "%d/%m/%Y"},
    )["dataset"]
    assert prepared.when.dt.month.tolist() == [2]
    assert frame.when.tolist() == ["01/02/2026"]


@pytest.mark.parametrize("value", ["", "NaT"])
@pytest.mark.parametrize("fmt", ["ISO8601", "%Y-%m-%d"])
def test_date_parsing_cannot_silently_promote_text_to_missing(value, fmt):
    frame = pd.DataFrame({"when": ["2026-02-01", value, None]})
    original = frame.copy(deep=True)
    with pytest.raises(ValueError):
        prepare_dataset(frame, date_formats={"when": fmt})
    assert_frame_equal(frame, original)


def test_date_parsing_retains_actual_missing_values_and_row_index():
    frame = pd.DataFrame({"when": ["2026-02-01", None]}, index=[10, 20])
    result = prepare_dataset(frame, date_formats={"when": "ISO8601"})
    assert result["dataset"].index.tolist() == [10, 20]
    assert result["dataset"].when.isna().tolist() == [False, True]
    assert result["operations"].operation.tolist() == ["parse_datetime"]


def test_derived_transforms_cannot_overwrite_columns_or_misalign_rows():
    frame = pd.DataFrame({"value": [2, 3]}, index=[10, 20])
    with pytest.raises(ValueError, match="new, nonempty"):
        prepare_dataset(frame, derived={"value": lambda data: data.value * 2})
    with pytest.raises(ValueError, match="row index"):
        prepare_dataset(frame, derived={"doubled": lambda data: pd.Series([4, 6])})


def test_preparation_string_and_boolean_conversions_preserve_missing_values():
    frame = pd.DataFrame({"label": [1, None], "flag": [True, None]})
    result = prepare_dataset(frame, conversions={"label": "str", "flag": "bool"})[
        "dataset"
    ]
    assert result.label.iloc[0] == "1.0"
    assert pd.isna(result.label.iloc[1])
    assert pd.isna(result.flag.iloc[1])
    with pytest.raises(TypeError):
        prepare_dataset(pd.DataFrame({"flag": ["False"]}), conversions={"flag": "bool"})


def test_explicit_deduplication_can_remove_all_duplicate_members_including_null_keys():
    frame = pd.DataFrame({"key": [None, None, "a"], "value": [1, 2, 3]})
    result = prepare_dataset(frame, deduplicate_by=["key"], deduplicate_keep=False)
    assert result["dataset"].key.tolist() == ["a"]
    assert result["operations"].iloc[0].affected_rows == 2


def test_helpers_reject_duplicate_column_names():
    frame = pd.DataFrame([[1, 2]], columns=["x", "x"])
    with pytest.raises(ValueError, match="column names must be unique"):
        explore_dataset(frame)
    with pytest.raises(ValueError, match="column names must be unique"):
        prepare_dataset(frame)
