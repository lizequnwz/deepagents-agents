from __future__ import annotations

from data_analytics_agent.profiling import profile_result
from data_analytics_agent.schemas import AnalyticalRole, TemporalKind


def _roles(profile, column: str) -> set[AnalyticalRole]:
    match = next(item for item in profile.columns if item.name == column)
    return {candidate.role for candidate in match.role_candidates}


def test_full_result_profile_infers_roles_counts_ranges_and_dates() -> None:
    rows = [
        {
            "month_start": "2025-01-01",
            "genre": "Rock",
            "sales": 10.5,
            "month_number": 1,
        },
        {
            "month_start": "2025-02-01",
            "genre": "Jazz",
            "sales": 12.0,
            "month_number": 2,
        },
        {
            "month_start": "not-a-date",
            "genre": None,
            "sales": "bad",
            "month_number": 2,
        },
    ]

    profile = profile_result(list(rows[0]), rows)
    by_name = {column.name: column for column in profile.columns}

    assert profile.scope == "stored_rows"
    assert profile.row_count == 3
    assert by_name["month_start"].temporal_kind is None
    assert by_name["genre"].null_count == 1
    assert by_name["genre"].distinct_count == 2
    assert AnalyticalRole.NUMERIC in _roles(profile, "sales")
    assert AnalyticalRole.DISCRETE_NUMERIC in _roles(
        profile, "month_number"
    )
    assert by_name["month_number"].minimum == 1
    assert by_name["month_number"].maximum == 2


def test_consistent_iso_dates_are_temporal() -> None:
    rows = [
        {"month_start": f"2025-{month:02d}-01"}
        for month in range(1, 6)
    ]

    profile = profile_result(["month_start"], rows)
    column = profile.columns[0]

    assert column.temporal_kind is TemporalKind.DATE
    assert AnalyticalRole.TEMPORAL in {
        candidate.role for candidate in column.role_candidates
    }
