---
name: statistical-analysis
description: Conduct robust, reproducible statistical analysis with general Python over a reviewed saved dataset. Use for experiments, hypothesis tests, correlations, distributions, regression, effect estimation, uncertainty, significance, diagnostics, and related inferential or exploratory statistical questions.
---

# Statistical analysis

## Establish the analysis design

1. Restate the estimand or analytical question in operational terms.
2. Identify the outcome, predictors or groups, observational unit, population,
   time scope, and whether observations are independent, paired, clustered, or
   repeated.
3. Inspect result provenance, profile, and bounded sample. Never infer against a
   result marked `truncated`.
4. Confirm the dataset retains the variation and grain needed for the method.
   Request SQL reshaping rather than analyzing aggregates that destroy the
   experimental unit or within-group variation.
   A categorical predictor with one aggregate row per category is not adequate
   for estimating a category effect or its uncertainty; do not substitute a
   correlation between two category-level totals.
5. Ask for clarification when plausible choices would materially change the
   dataset, estimand, or method. Otherwise choose and justify an appropriate
   method without forcing the user to name a test.

## Use robust statistical practice

- Default to 95% confidence intervals, two-sided tests, and alpha 0.05 only when
  the user has not specified alternatives. State these defaults in assumptions.
- Report effect sizes and uncertainty whenever applicable. Never use a p-value
  alone as the conclusion, and distinguish statistical from practical
  significance.
- Check method assumptions with quantitative diagnostics and useful plots.
  When assumptions are doubtful, use a justified transformation, robust model,
  nonparametric method, permutation procedure, or bootstrap rather than silently
  proceeding.
- Handle missingness deliberately. Report counts and the rule used; do not let a
  library's implicit row dropping determine the analysis unnoticed.
- Treat outliers as observations to investigate, not values to delete by
  default. Disclose exclusions and, when material, compare sensitivity with and
  without influential points.
- Address multiplicity when testing several hypotheses, outcomes, subgroups, or
  model terms. Name the correction or hierarchical strategy.
- Respect dependence, clustering, repeated measures, weights, censoring, and
  time ordering when present. Do not treat correlated observations as
  independent.
- Separate predictive validation from in-sample fit. Use suitable holdout or
  cross-validation for predictive claims, but do not confuse prediction with
  causal identification.
- Describe association as association unless the study design and assumptions
  support a causal claim. State material confounding and selection limitations.
- Set an explicit random seed for stochastic methods. Use seed `0` unless the
  user requests another value, and report it.

## Write reviewed Python

- Work from the preloaded pandas DataFrame `df`; `pd` and `np` are also
  preloaded. Import other guaranteed statistical libraries as needed.
- Keep the submitted code self-contained and readable. Use meaningful variable
  names and short comments for analytical choices that a reviewer must verify.
- Preserve the requested population. Derive fields, reshape, and handle missing
  values inside the reviewed code so the executed transformation is auditable.
- Assign a named dictionary to `analysis_outputs`. Values may be compact text,
  scalars, pandas DataFrames or Series, JSON record lists, or matplotlib Figures
  or Axes. Never place the complete input `df` in the outputs.
- Make tables compact and decision-relevant: estimates, uncertainty intervals,
  test statistics, adjusted p-values, fit diagnostics, or sensitivity results.
- After an execution error, use the bounded traceback to make a targeted repair.
  Every revision requires another review. Do not repeat unchanged failing code.

## Produce expert conclusions

Return a concise answer, method description, assumptions, interpretation,
warnings, and compact outputs. Include sample sizes and exclusions. Explain
direction, magnitude, uncertainty, and limitations in domain language. Avoid
claims stronger than the design or data support.

When a figure is requested or materially improves diagnostics or interpretation,
read [statistical graphics](references/statistical-graphics.md) before writing
code.

For a categorical predictor and numeric outcome, a distribution or effect plot
normally materially improves interpretation. Preserve repeated observations
within each category, read the graphics reference, and return a compact figure
alongside the inferential table unless the data or user request makes a figure
inappropriate.
