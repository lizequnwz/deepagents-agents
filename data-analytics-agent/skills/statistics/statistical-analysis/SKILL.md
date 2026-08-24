---
name: statistical-analysis
description: Analyze uncertainty or fit statistical models with general Python over one saved dataset. Use for experiments, inference, regression, predictive modeling, trend inference, seasonality, forecasting, and diagnostics; ordinary descriptive summaries and charts do not need this skill.
---

# Statistical analysis

## Design the smallest useful analysis

1. State the analytical question in operational terms: outcome, predictors or
   groups, observational unit, population, and time scope.
2. Inspect provenance, the full-result profile, and the bounded sample. Never
   analyze a result marked `truncated`.
3. Confirm the dataset preserves the grain and variation the method needs.
   Request SQL reshaping when aggregates have destroyed the observational unit,
   time order, within-group variation, or required population.
4. Use statistical Python only when uncertainty or modeling changes the answer.
   Leave ordinary totals, rankings, descriptive trends, and chartable
   distributions to SQL and visualization.
5. Choose the simplest defensible method. Ask for clarification only when a
   choice would materially change the data or conclusion.

For regression or predictive modeling, read
[regression guidance](references/regression.md). For trend inference,
seasonality, anomaly detection, or forecasting, read
[time-series guidance](references/time-series.md). Read
[statistical graphics](references/statistical-graphics.md) only when a figure
materially improves diagnosis or interpretation.

## Apply relevant statistical practice

- Report magnitude and uncertainty when applicable; do not make a p-value the
  conclusion.
- Handle missingness explicitly and report the analyzed sample size. Investigate
  influential observations rather than deleting them by default.
- Check only the assumptions that matter for the selected method and claim. Use
  a robust, nonparametric, permutation, or bootstrap alternative when justified.
- Address multiplicity only when several hypotheses, outcomes, subgroups, or
  model terms are being interpreted together.
- Respect pairing, clustering, repeated measures, weights, censoring, and time
  ordering when present.
- Separate explanatory, predictive, and causal questions. Use temporal or group
  validation when random row splitting would leak information.
- Use seed `0` for stochastic methods unless the user requests another value.

## Execute once, compactly

- Work from the preloaded pandas DataFrame `df`; `pd` and `np` are also
  preloaded. Use the available SciPy, statsmodels, scikit-learn, matplotlib, and
  seaborn libraries as needed.
- Write one self-contained program that performs the analysis and necessary
  diagnostics. Do not use executions as staged data exploration.
- Assign a named dictionary to `analysis_outputs`. Return only compact,
  decision-relevant text, scalars, tables, or figures; never return the complete
  input dataset.
- After a repairable execution error, use the bounded failure details for one
  targeted repair. Do not repeat unchanged code or start another analysis after
  the run has no attempts remaining.

Return a concise answer, method, material assumptions, interpretation, warnings,
sample sizes, exclusions, and limitations. Describe association as association
unless the data and design support a stronger claim.
