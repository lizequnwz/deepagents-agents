# Regression and predictive modeling

Use regression when a modeled relationship, adjusted estimate, or prediction
materially answers the question. Do not fit a model merely because numeric
columns are present.

## Match the model to the question

- Distinguish explanation, prediction, and causal effect estimation before
  choosing features or interpreting coefficients.
- Match the outcome: ordinary least squares for a defensible continuous-outcome
  relationship, logistic regression for binary outcomes, and a suitable
  generalized linear model for counts, rates, or nonconstant variance.
- Encode categories with an explicit reference level. Add transformations,
  interactions, or nonlinear terms only when the question or diagnostics
  justify them.
- Do not interpret a category-level aggregate model as evidence about
  within-category observations.

## Diagnose what affects the claim

- Report the analyzed sample, missing-value rule, coefficient or prediction
  estimates, and uncertainty relevant to the question.
- Check residual structure, influential observations, and collinearity when
  they can materially change coefficient interpretation. Prefer robust or
  cluster-aware standard errors when the data structure warrants them.
- For prediction, compare against a simple baseline and evaluate on held-out or
  cross-validated data. Keep groups or time periods together when random row
  splitting would leak information.
- Do not use fit statistics alone as evidence of practical usefulness, and do
  not describe adjusted association as causal without a defensible design.

Return a compact coefficient or performance table and at most the diagnostics
needed to support the conclusion.
