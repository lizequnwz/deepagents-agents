"""Customer journeys over explicitly supplied populations and observation windows."""

from collections.abc import Sequence
from datetime import date, datetime

import numpy as np
import pandas as pd

from data_analytics_agent.analysis._frames import (
    sum_numbers,
    numeric_values,
    timestamp_value,
    timestamp_values,
)


def _observation_end(value: str | pd.Timestamp) -> pd.Timestamp:
    result = timestamp_value(value, label="Observation cutoff")
    if pd.isna(result):
        raise ValueError("An explicit observation cutoff is required")
    # An ISO calendar date covers that entire UTC day; timestamps stay exact.
    if (isinstance(value, str) and len(value) == 10) or (
        isinstance(value, date) and not isinstance(value, datetime)
    ):
        result += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return result


def _population(frame: pd.DataFrame, entity: str, date: str) -> pd.DataFrame:
    if entity == date:
        raise ValueError("Entity and date must be distinct columns")
    result = frame[[entity, date]].copy()
    if result[entity].isna().any() or result[entity].duplicated().any():
        raise ValueError("Population requires one nonmissing row per entity")
    result[date] = timestamp_values(result[date], label="Population dates")
    if result[date].isna().any():
        raise ValueError("Population dates must be nonmissing")
    if result.empty:
        raise ValueError("Population must not be empty")
    return result


def cohort_retention(
    population: pd.DataFrame,
    events: pd.DataFrame,
    *,
    entity: str,
    cohort_time: str,
    event_time: str,
    observation_end: str | pd.Timestamp,
    periods: int = 6,
    frequency: str = "M",
) -> dict[str, pd.DataFrame]:
    """Calendar-period activity retention for an explicit eligible population.

    ``events`` must already contain the declared qualifying activity. Period zero
    measures activity too; it is not forced to 100%. A cell is assessed only when
    its entire calendar period ends by ``observation_end`` (an inclusive UTC
    timestamp; an ISO date includes the whole UTC day). Future/partial cells retain their cohort size with missing counts
    and rates. Population dates define cohort membership, never first observed
    activity. Calendar periods use UTC; frequency is D, W, M, Q or Y.
    """
    if frequency not in {"D", "W", "M", "Q", "Y"}:
        raise ValueError("frequency must be D, W, M, Q or Y")
    if not isinstance(periods, int) or not 1 <= periods <= 120:
        raise ValueError("periods must be between 1 and 120")
    end = _observation_end(observation_end)
    members = _population(population, entity, cohort_time).rename(
        columns={entity: "entity_id", cohort_time: "cohort_time"}
    )
    # Period arithmetic is calendar based; remove the already-normalized UTC tz.
    cohort = members["cohort_time"].dt.tz_localize(None).dt.to_period(frequency)
    members["cohort_period"] = cohort.astype(str)
    activity = (
        events[[entity, event_time]]
        .rename(columns={entity: "entity_id", event_time: "event_time"})
        .copy()
    )
    activity["event_time"] = timestamp_values(
        activity["event_time"], label="Event dates"
    )
    missing_events = activity[["entity_id", "event_time"]].isna().any(axis=1)
    outside_population = (
        ~activity["entity_id"].isin(members["entity_id"]) & ~missing_events
    )
    usable = activity.loc[~missing_events & ~outside_population].merge(
        members[["entity_id", "cohort_time"]], on="entity_id", validate="many_to_one"
    )
    before_cohort = usable["event_time"] < usable["cohort_time"]
    after_cutoff = usable["event_time"] > end
    usable = usable.loc[~before_cohort & ~after_cutoff].copy()
    usable["activity_period"] = (
        usable["event_time"].dt.tz_localize(None).dt.to_period(frequency).astype(str)
    )
    active_sets = {
        key: set(group["entity_id"]) for key, group in usable.groupby("activity_period")
    }
    rows = []
    for label, group in members.groupby("cohort_period", sort=True):
        first = pd.Period(label, freq=frequency)
        ids = set(group["entity_id"])
        for age in range(periods):
            period = first + age
            assessed = period.end_time.tz_localize("UTC") <= end
            active = (
                len(ids & active_sets.get(str(period), set())) if assessed else pd.NA
            )
            rows.append(
                {
                    "cohort_period": label,
                    "period_age": age,
                    "activity_period": str(period),
                    "cohort_size": len(ids),
                    "is_observed": assessed,
                    "active_entities": active,
                    "retention_rate": active / len(ids) if assessed else np.nan,
                }
            )
    retention = pd.DataFrame(rows)
    retention["active_entities"] = retention["active_entities"].astype("Int64")
    return {
        "retention": retention,
        "cohort_members": members,
        "retention_metadata": pd.DataFrame(
            [
                {
                    "observation_end": end,
                    "frequency": frequency,
                    "population_entities": len(members),
                    "activity_rows": len(events),
                    "missing_entity_or_date_rows": int(missing_events.sum()),
                    "outside_population_rows": int(outside_population.sum()),
                    "before_cohort_rows": int(before_cohort.sum()),
                    "after_cutoff_rows": int(after_cutoff.sum()),
                    "entity_column": entity,
                    "cohort_time_column": cohort_time,
                    "event_time_column": event_time,
                    "activity_definition": "Qualifying activity supplied by caller",
                    "censoring": "Only complete calendar periods assessed",
                }
            ]
        ),
    }


def ordered_funnel(
    population: pd.DataFrame,
    events: pd.DataFrame,
    *,
    entity: str,
    entry_time: str,
    event: str,
    event_time: str,
    steps: Sequence[str],
    window: str | pd.Timedelta,
    observation_end: str | pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    """Strictly ordered events within a fixed window from population entry.

    Each step must occur strictly after the previous step (the first may occur
    at entry); the upper deadline is inclusive. Earliest matching events are
    used. Aggregate conversion uses only entities with fully observed windows.
    All entities, including right-censored ones, remain in ``funnel_entities``.
    """
    steps = list(steps)
    if (
        not steps
        or len(set(steps)) != len(steps)
        or any(not isinstance(step, str) or not step for step in steps)
    ):
        raise ValueError("steps must be nonempty, distinct event names")
    duration = pd.Timedelta(window)
    end = _observation_end(observation_end)
    if pd.isna(end) or pd.isna(duration) or duration <= pd.Timedelta(0):
        raise ValueError("Explicit observation_end and positive window required")
    members = _population(population, entity, entry_time)
    activity = events[[entity, event, event_time]].copy()
    activity[event_time] = timestamp_values(activity[event_time], label="Event dates")
    missing = activity[[entity, event, event_time]].isna().any(axis=1)
    groups = {
        key: group.sort_values(event_time, kind="stable")
        for key, group in activity.loc[~missing].groupby(entity, sort=False)
    }
    rows = []
    for _, member in members.iterrows():
        key, start = member[entity], member[entry_time]
        deadline = start + duration
        observed = deadline <= end
        row = {
            "entity_id": key,
            "entry_time": start,
            "deadline": deadline,
            "is_observed": observed,
            "observation_status": "complete" if observed else "right_censored",
        }
        group = groups.get(key)
        previous = start
        reached = 0
        for index, step in enumerate(steps):
            timestamp = pd.NaT
            if group is not None and reached == index:
                after = (
                    group[event_time] >= previous
                    if index == 0
                    else group[event_time] > previous
                )
                matches = group.loc[
                    (group[event] == step)
                    & after
                    & (group[event_time] <= min(deadline, end))
                ]
                if not matches.empty:
                    timestamp = matches.iloc[0][event_time]
                    previous = timestamp
                    reached += 1
            row[f"step_{index + 1}_time"] = timestamp
        row["steps_reached"] = reached
        rows.append(row)
    entities = pd.DataFrame(rows)
    assessed = entities.loc[entities["is_observed"]]
    denominator = len(assessed)
    counts = [
        int((assessed["steps_reached"] >= i + 1).sum()) for i in range(len(steps))
    ]
    funnel = pd.DataFrame(
        [
            {
                "step_number": i + 1,
                "event_name": step,
                "eligible_entities": denominator,
                "reached_entities": count,
                "conversion_from_entry": count / denominator if denominator else np.nan,
                "conversion_from_previous": count / counts[i - 1]
                if i and counts[i - 1]
                else (count / denominator if not i and denominator else np.nan),
            }
            for i, (step, count) in enumerate(zip(steps, counts, strict=True))
        ]
    )
    return {
        "funnel": funnel,
        "funnel_entities": entities,
        "funnel_metadata": pd.DataFrame(
            [
                {
                    "observation_end": end,
                    "window": str(duration),
                    "window_origin": "population entry_time",
                    "ordering": "strictly increasing timestamps",
                    "population_entities": len(members),
                    "right_censored_entities": int((~entities["is_observed"]).sum()),
                    "missing_event_rows": int(missing.sum()),
                    "outside_population_rows": int(
                        (~activity[entity].isin(members[entity]) & ~missing).sum()
                    ),
                    "entity_column": entity,
                    "entry_time_column": entry_time,
                    "event_column": event,
                    "event_time_column": event_time,
                }
            ]
        ),
    }


def rfm_segments(
    transactions: pd.DataFrame,
    *,
    entity: str,
    transaction_id: str,
    transaction_time: str,
    monetary: str,
    as_of: str | pd.Timestamp,
    unit: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Deterministic RFM scores on one-row-per-transaction input.

    Four percentile-rank bands preserve ties. Missing dates/amounts are retained
    in quality counts; any missing eligible amount makes monetary scoring and
    segment assignment unassessed. Negative amounts are retained as supplied.
    """
    frame = transactions[[entity, transaction_id, transaction_time, monetary]].copy()
    if frame.empty or frame[entity].isna().any() or frame[transaction_id].isna().any():
        raise ValueError("Nonempty transactions require entity and transaction IDs")
    if frame.duplicated([entity, transaction_id]).any():
        raise ValueError(
            "Expected one row per entity/transaction; aggregate lines first"
        )
    frame[transaction_time] = timestamp_values(
        frame[transaction_time], label="Transaction dates"
    )
    numeric_values(frame, monetary)
    end = _observation_end(as_of)
    rows = []
    for key, group in frame.groupby(entity, sort=False):
        eligible = group.loc[group[transaction_time] <= end]
        missing_dates = int(group[transaction_time].isna().sum())
        missing_amounts = int(eligible[monetary].isna().sum())
        last = eligible[transaction_time].max()
        complete = bool(len(eligible) and not missing_dates and not missing_amounts)
        rows.append(
            {
                "entity_id": key,
                "recency_days": (end.normalize() - last.normalize()).days
                if pd.notna(last)
                else np.nan,
                "frequency": len(eligible),
                "monetary": sum_numbers(eligible[monetary])
                if len(eligible) and not missing_amounts
                else np.nan,
                "missing_date_transactions": missing_dates,
                "missing_amount_transactions": missing_amounts,
                "future_transactions": int((group[transaction_time] > end).sum()),
                "is_assessed": complete,
            }
        )
    rfm = pd.DataFrame(rows)
    for column, ascending in [
        ("recency_days", False),
        ("frequency", True),
        ("monetary", True),
    ]:
        values = rfm[column].where(rfm["is_assessed"])
        rfm[column.replace("_days", "") + "_score"] = (
            np.ceil(values.rank(method="average", pct=True, ascending=ascending) * 4)
            .clip(1, 4)
            .astype("Int64")
        )
    rfm["segment"] = "unassessed"
    assessed = rfm["is_assessed"]
    recent = rfm["recency_score"].ge(3).fillna(False)
    frequent = rfm["frequency_score"].ge(3).fillna(False)
    rfm.loc[assessed & recent & frequent, "segment"] = "recent_frequent"
    rfm.loc[assessed & recent & ~frequent, "segment"] = "recent_infrequent"
    rfm.loc[assessed & ~recent & frequent, "segment"] = "less_recent_frequent"
    rfm.loc[assessed & ~recent & ~frequent, "segment"] = "less_recent_infrequent"
    profiles = (
        rfm.groupby("segment", dropna=False)
        .agg(
            entities=("segment", "size"),
            mean_recency_days=("recency_days", "mean"),
            mean_frequency=("frequency", "mean"),
            mean_monetary=("monetary", "mean"),
        )
        .reset_index()
    )
    return {
        "rfm_entities": rfm,
        "segment_profiles": profiles,
        "segmentation_metadata": pd.DataFrame(
            [
                {
                    "as_of": end,
                    "monetary_unit": unit or "unknown",
                    "frequency_definition": "Count of distinct supplied transactions through as_of",
                    "score_method": "Four equal percentile-rank bands, average ties",
                    "population_entities": len(rfm),
                    "entity_column": entity,
                    "recency_definition": "UTC calendar days since last eligible transaction",
                }
            ]
        ),
    }
