# Reusable analytical procedures

Import the relevant module inside execute_analysis_python. Modules are supplied
with the application, captured with each execution and included in portable replay.
Every function below returns a dictionary of complete pandas DataFrames. Save it
in output_datasets; choose at most ten compact diagnostics in analysis_outputs.
Derived tables can be named inputs in later executions and shared charts.

```python
from data_analytics_agent.analysis.exploration import explore_dataset
tables = explore_dataset(datasets['input'])
output_datasets = tables
analysis_outputs = {'overview': tables['overview'],
                    'columns': tables['columns'].head(10)}
```

Helpers preserve explicit unknowns and method limitations. They do not establish
business meaning, source completeness, independence or leakage-free feature design.
They are optional building blocks; use the installed libraries when the question
requires another defensible method.

## Exploration, preparation and diagnostics

- `exploration.explore_dataset(frame, columns=None, date_column=None,
  frequency=None, top_categories=20)`: full-population overview, column profiles,
  numeric moments/distributions, categorical counts with omitted-category accounting,
  pairwise Pearson/Spearman correlations and pair counts. Date coverage requires an
  explicitly parsed date column; supply a pandas period frequency such as `M`.
- `exploration.compare_groups(frame, group=..., value=..., reference_group=None)`:
  descriptive `groups` and `comparisons`; missing categories/values and denominators
  remain visible. This is distinct from a statistical test.
- `preparation.prepare_dataset(frame, conversions=None, date_formats=None,
  derived=None, fill_values=None, drop_missing=None, deduplicate_by=None,
  deduplicate_keep='first')`: `dataset` plus `operations`. Defaults preserve rows.
  Date parsing needs an explicit format. Derived columns are named pandas callables,
  e.g. `derived={'margin': lambda df: df.revenue - df.cost}`. Never invent a missing
  value policy; record any population change and preserve the original input.
- `diagnostics.reconcile_tables(current, baseline, keys=[...], value=...,
  unmatched='unknown', atol=1e-8, rtol=1e-5)`: `rows` and `summary`. Duplicate
  grouping keys are rejected. Missing values remain unknown; choose `unmatched='zero'`
  only when absence really means no activity under the business definition.
- `diagnostics.decompose_change(current, baseline, keys=[...], value=...,
  unmatched='unknown')`: `contributions` and `summary`, with reconciled residual and
  relative shares. No causal interpretation is implied. Build a waterfall table with
  the baseline total (`absolute`), each contribution (`relative`), and ending total
  (`total`), explicitly saved as ordinary columns for create_chart.

## Customer/product behavior

Customer dates and prediction split cutoffs accept typed dates/timestamps or strict
ISO text. Prepare ambiguous strings with an explicit date format first; numeric
epochs need explicit conversion. Customer observation cutoffs given as ISO calendar
dates include the entire UTC day; timestamp cutoffs remain exact. Calendar cohorts
use UTC, so prepare local business dates explicitly when that distinction matters.

`customer.cohort_retention(population, events, entity=..., cohort_time=...,
event_time=..., observation_end=..., periods=6, frequency='M')` expects one row per
eligible entity in population and qualifying activity in events. Save `retention`,
`cohort_members` and `retention_metadata`. Unobserved calendar periods are missing,
not zero. Confirm cohort and observation-window meaning before calculation.

`customer.ordered_funnel(population, events, entity=..., entry_time=...,
event=..., event_time=..., steps=[...], window='30D', observation_end=...)` uses
strictly increasing event times within the declared window from entry. Save
`funnel`, `funnel_entities` and `funnel_metadata`; censored entities are retained
but do not silently become eligible completed windows. Shared funnel charts use
explicit stage_order and matching saved stage/count columns.

`customer.rfm_segments(transactions, entity=..., transaction_id=...,
transaction_time=..., monetary=..., as_of=..., unit=None)` expects one row per
transaction and produces `rfm_entities`, `segment_profiles`, `segmentation_metadata`.
Average percentile ranks preserve ties. Segments describe supplied transactions;
they are not validated customer types or predictions of future value.

## Inference and prediction

`statistical.compare_groups(frame, group=..., outcome=..., reference=...,
comparison=..., kind='numeric', confidence=.95, unit_id=None, unit=None)` supports
independent numeric or binary observations, preserving counts and exclusions.
Numeric comparisons use Welch uncertainty and Hedges' g; binary comparisons use
risk-difference uncertainty and Fisher exact. Supply unique unit IDs when available.
Repeated observations need a suitable alternative; do not imply randomization.

`prediction.evaluate_prediction(frame, target=..., features=[...],
task='regression'|'classification', split='random'|'time'|'group',
feature_availability='...', split_column=None, cutoff=None, test_size=.25,
random_state=0, unit=None)` evaluates a fixed Ridge/logistic candidate against a
training-only dummy baseline. Time splits require an explicit cutoff; group splits
keep groups together. Classification is binary 0/1. Save `scored_rows`,
`prediction_scores`, `prediction_features`, `prediction_metadata`. Preprocessing
is fitted only on training data; the feature-availability statement still requires
method review. Do not tune on the holdout or describe these scores as calibrated
future certainty. Inspect meaningful errors/subgroups as the task requires.

## Time series and scenarios

`time_series.diagnose_series(frame, time=..., value=..., frequency=...,
seasonal_periods=None, anomaly_threshold=3.5)` requires an explicit calendar
frequency: daily, weekly, monthly, quarterly or yearly. It reports gaps without
filling, and residual-based anomaly candidates with undefined/degenerate cases
retained as unassessed. Seasonal decomposition needs at least two declared cycles.
The time column must already contain parsed, timezone-free calendar dates; prepare
and label business periods explicitly instead of inferring them from text.

`time_series.forecast_series(frame, time=..., value=..., frequency=...,
horizon=..., holdout=..., seasonal_periods=None, coverage=.95)` returns
`forecast_predictions`, `forecast_scores`, `forecast_metadata`, `model_parameters`.
It compares one ETS candidate with a naive baseline on a chronological holdout,
then refits on observed history. Bounds use declared model prediction intervals.
Inspect predictions, score quality and interval suitability; the helper does not
prove a useful forecast. Save predictions and pass their exact saved ID and
metadata to finish_analysis.forecast_evaluation so application code recomputes
scores and chronology. Nominal coverage remains distinct from measured coverage.

`scenarios.scenario_grid(assumptions, formula, formula_description=...,
outcome='outcome', unit=None)` evaluates an explicit grid, e.g.
`assumptions={'price':[10,11], 'volume':[90,100]}` and
`formula=lambda price, volume: price * volume`. Save `scenarios` and
`scenario_summary`. Undefined arithmetic stays missing with a reason. The range
describes supplied assumptions, with no probability coverage claim.
