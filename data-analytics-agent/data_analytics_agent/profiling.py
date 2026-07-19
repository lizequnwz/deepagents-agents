"""Deterministic full-artifact profiling for model-safe result inspection."""

from __future__ import annotations

from datetime import date, datetime
from numbers import Real
import re
from typing import Any

from data_analytics_agent.schemas import (
    AnalyticalRole,
    ColumnProfile,
    PhysicalKind,
    ResultProfile,
    RoleCandidate,
    TemporalKind,
)

_MONTH_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
_QUARTER_RE = re.compile(r"^\d{4}[- ]?Q[1-4]$", re.IGNORECASE)
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _stable_distinct(values: list[Any]) -> list[Any]:
    distinct: list[Any] = []
    seen: set[tuple[type[Any], str]] = set()
    for value in values:
        key = (type(value), str(value))
        if key not in seen:
            seen.add(key)
            distinct.append(value)
    return distinct


def _physical_kind(values: list[Any]) -> PhysicalKind:
    if not values:
        return PhysicalKind.EMPTY
    if all(isinstance(value, bool) for value in values):
        return PhysicalKind.BOOLEAN
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return PhysicalKind.INTEGER
    if all(_is_number(value) for value in values):
        return PhysicalKind.NUMBER
    if all(isinstance(value, str) for value in values):
        return PhysicalKind.TEXT
    return PhysicalKind.MIXED


def _temporal_kind(value: Any) -> TemporalKind | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _QUARTER_RE.fullmatch(text):
        return TemporalKind.QUARTER
    if _MONTH_RE.fullmatch(text):
        return TemporalKind.MONTH
    if _YEAR_RE.fullmatch(text):
        return TemporalKind.YEAR
    try:
        if "T" in text or " " in text:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
            return TemporalKind.DATETIME
        date.fromisoformat(text)
        return TemporalKind.DATE
    except ValueError:
        return None


def _range(values: list[Any], kind: PhysicalKind) -> tuple[Any | None, Any | None]:
    if not values:
        return None, None
    if kind in {PhysicalKind.INTEGER, PhysicalKind.NUMBER, PhysicalKind.TEXT}:
        try:
            return min(values), max(values)
        except TypeError:
            return None, None
    return None, None


def _role_candidates(
    values: list[Any],
    *,
    distinct_count: int,
    temporal_kind: TemporalKind | None,
    temporal_confidence: float,
) -> tuple[RoleCandidate, ...]:
    if not values:
        return (RoleCandidate(role=AnalyticalRole.UNKNOWN, confidence=1),)

    total = len(values)
    numeric_count = sum(_is_number(value) for value in values)
    text_or_bool_count = sum(
        isinstance(value, (str, bool)) for value in values
    )
    candidates: list[RoleCandidate] = []

    if temporal_kind is not None:
        candidates.append(
            RoleCandidate(
                role=AnalyticalRole.TEMPORAL,
                confidence=temporal_confidence,
            )
        )
    if numeric_count:
        numeric_confidence = numeric_count / total
        candidates.append(
            RoleCandidate(
                role=AnalyticalRole.NUMERIC,
                confidence=numeric_confidence,
            )
        )
        low_cardinality = (
            distinct_count <= 30
            or distinct_count / max(total, 1) <= 0.2
        )
        if low_cardinality:
            candidates.append(
                RoleCandidate(
                    role=AnalyticalRole.DISCRETE_NUMERIC,
                    confidence=numeric_confidence,
                )
            )
    if text_or_bool_count:
        candidates.append(
            RoleCandidate(
                role=AnalyticalRole.CATEGORICAL,
                confidence=text_or_bool_count / total,
            )
        )
    if not candidates:
        candidates.append(
            RoleCandidate(role=AnalyticalRole.UNKNOWN, confidence=1)
        )
    return tuple(candidates)


def profile_result(
    columns: list[str],
    rows: list[dict[str, Any]],
) -> ResultProfile:
    """Profile every stored row once, when the immutable artifact is saved."""

    profiles: list[ColumnProfile] = []
    for column in columns:
        all_values = [row.get(column) for row in rows]
        values = [value for value in all_values if value is not None]
        distinct = _stable_distinct(values)
        kind = _physical_kind(values)

        temporal_values = [_temporal_kind(value) for value in values]
        matched = [value for value in temporal_values if value is not None]
        inferred_temporal: TemporalKind | None = None
        temporal_confidence = 0.0
        if matched:
            counts = {
                candidate: matched.count(candidate) for candidate in set(matched)
            }
            inferred_temporal, matched_count = max(
                counts.items(), key=lambda item: item[1]
            )
            temporal_confidence = matched_count / len(values)
            if temporal_confidence < 0.8:
                inferred_temporal = None

        minimum, maximum = _range(values, kind)
        profiles.append(
            ColumnProfile(
                name=column,
                physical_kind=kind,
                role_candidates=_role_candidates(
                    values,
                    distinct_count=len(distinct),
                    temporal_kind=inferred_temporal,
                    temporal_confidence=temporal_confidence,
                ),
                temporal_kind=inferred_temporal,
                null_count=len(all_values) - len(values),
                non_null_count=len(values),
                distinct_count=len(distinct),
                minimum=minimum,
                maximum=maximum,
                representative_values=tuple(distinct[:5]),
            )
        )
    return ResultProfile(row_count=len(rows), columns=tuple(profiles))
