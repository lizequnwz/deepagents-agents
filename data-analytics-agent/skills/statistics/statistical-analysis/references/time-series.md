# Trend, seasonality, and forecasting

Preserve time order throughout the analysis. The SQL result should contain a
timestamp or period, target value, intended frequency, and any grouping or
exogenous fields needed by the question.

## Establish a valid series

- Parse and sort time explicitly. Resolve duplicate periods and identify
  missing periods, irregular spacing, and incomplete current periods.
- Distinguish an aggregate time series from repeated entity observations; do
  not infer entity-level behavior from aggregate movement.
- Require enough history for the requested seasonal period. Do not claim
  seasonality from fewer than two complete cycles, and prefer more for
  forecasting.

## Choose the smallest adequate analysis

- For trend inference, estimate the direction and magnitude with uncertainty
  while accounting for autocorrelation or seasonality when material.
- For seasonality, use a transparent decomposition such as STL when frequency
  and history support it. Report the period and distinguish seasonal pattern
  from long-term trend.
- For forecasting, state the horizon, use only information available before
  each forecast origin, compare with a naive or seasonal-naive baseline, and
  report out-of-sample error plus forecast intervals.
- Use chronological holdouts or rolling-origin evaluation. Never randomly
  shuffle a time series for validation.
- Treat detected anomalies as model-relative observations, not automatically as
  data errors or business incidents.

Return compact trend, seasonal, or forecast outputs and one diagnostic figure
only when it helps interpret the result. Return `needs_sql_reshape` or
`cannot_analyze` when frequency, history, or target definition is inadequate.
