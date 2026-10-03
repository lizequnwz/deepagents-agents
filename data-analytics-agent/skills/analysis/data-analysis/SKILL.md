---
name: data-analysis
description: Iterative exploratory, statistical, predictive and time-series analysis of saved datasets.
---

# Analyze iteratively

Inspect saved inputs, formulate a method, execute a small useful step, examine
outputs, revise, and continue. Successful execution is progress, not a mandatory
stopping point. Use execute_analysis_python with named input artifact bindings.
Each fresh process exposes pandas DataFrames in `datasets`. Explicitly load
previous derived datasets; no kernel state survives. Set `analysis_outputs`
(a mapping of names to compact text, scalars, tables or figures) and
`output_datasets` (a mapping of names to reusable DataFrames). Keep useful
intermediate datasets; finish_analysis attaches this assignment’s inputs and
executions automatically. Never copy full datasets into messages.

Begin with grain, population, coverage, missingness, duplicates and plausible
ranges. Convert Decimal measures explicitly with pandas.to_numeric for modeling;
original evidence retains precision. Do not analyze capped source prefixes.
Request additional source data with a complete requested_data brief through
finish_analysis(needs_sql_reshape). The coordinator obtains SQL and reassigns you.

## Reconcile the final evidence

When refining a method, recompute derived columns (especially candidate flags)
and save the updated table. Derive narrative counts with groupby/value_counts from
that exact final table. Print only compact diagnostics, never full row dumps.
A zero MAD does not mean every candidate flag is false. If the rule is undefined,
save missing scores AND nullable Boolean flags (`pd.NA` with dtype `boolean`),
not False; missing means unassessed, False means assessed and not flagged.
If you select a justified fallback rule, persist its flags and explain the rule. Earlier outputs remain
provenance, but identify which output is final. Check all counts sum to the
population and screening flags match the claimed observations before finishing.

Use only declared units. Neither dollar symbols nor currency codes can be inferred
from a column called revenue. Observed first/last dates do not establish a source
cutoff. Preserve all requested periods and state completeness is unknown unless
an explicit source statement establishes it.

## Choose a defensible method

- Exploration: study distributions, missingness, segments, relationships and
  outliers. Separate descriptive associations from explanations. Investigate
  competing hypotheses before selecting a driver.
- Prediction: identify the target, prediction time and available features.
  Compare against a simple baseline. Use held-out evaluation, report suitable
  metrics and uncertainty, and prevent leakage. Fit preprocessing only on
  training data, preferably with sklearn pipelines. Avoid causal claims.
- Time series: inspect frequency, gaps, sample length, trends, seasonality and
  structural breaks. Use temporal holdouts or rolling-origin evaluation.
  Save a named prediction dataset with actuals, candidate predictions, a baseline,
  and future predictions on one regular calendar series. Pass its exact ID and
  chronological boundaries to `finish_analysis.forecast_evaluation`; application
  code validates the periods and recomputes MAE, RMSE and measured interval coverage.
  Keep future actuals missing, declare any preparation, and save interval bounds
  for both holdout and future when evaluating coverage. The descriptor supports
  daily, weekly, monthly, quarterly and yearly periods. With fewer than two training
  periods or unresolved missing periods, return an explicit analytical limitation.
  Choose candidates using training-only diagnostics, even when prior conversation
  analysis examined the full history. Do not use those full-history findings to
  exclude candidates or call the holdout an untouched assessment after tuning.
  Compare naive/seasonal-naive baselines. Validate at the requested horizon;
  include prediction intervals and distinguish them from parameter confidence
  intervals. Do not assume seasonality from the date column alone. Examine
  model-comparison outputs before final refitting: an unexpectedly poor fit,
  systematic holdout bias or implausible uncertainty calls for another step.
  Compare interval widths against held-out forecast errors and assess empirical
  coverage when feasible. Tiny in-sample residuals do not establish accurate
  future uncertainty, especially with trend damping or model misspecification.
  Do not present residual-SD times sqrt(horizon) as calibrated model intervals;
  use a justified model simulation or forecast-error approach and state its limits.
- Statistical inference: state estimand, observational unit, assumptions and
  limitations. Report effect sizes and uncertainty, not only p-values. Account
  for repeated observations or multiple comparisons where relevant.
- Anomalies: compare against expected seasonal/segment behavior. Treat flags
  as investigation leads, report sensitivity and plausible data-quality causes.

Save prediction rows, residuals, decomposition components, scored observations
or model-comparison tables as derived datasets when useful for later work and
charts. Save diagnostic matplotlib/seaborn figures as compact outputs. Use
pandas, NumPy, SciPy, statsmodels and scikit-learn as appropriate; no prescribed
algorithm catalog. See references for additional method guidance.

Repair errors using the returned diagnostics. Preserve successful earlier steps.
When the budget ends, return partial findings and unresolved questions. Finish
with analysis_completed only when the requested analysis is supported; otherwise
use partial, needs_sql_reshape, needs_clarification or cannot_analyze.
