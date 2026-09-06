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
`output_datasets` (a mapping of names to reusable DataFrames). Preserve each
material execution ID in finish_analysis. Never copy full datasets into messages.

Begin with grain, population, coverage, missingness, duplicates and plausible
ranges. Convert Decimal measures explicitly with pandas.to_numeric for modeling;
original evidence retains precision. Do not analyze capped source prefixes.
Request additional source data with a complete requested_data brief through
finish_analysis(needs_sql_reshape). The coordinator obtains SQL and reassigns you.

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
