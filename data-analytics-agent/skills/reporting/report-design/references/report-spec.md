# ReportSpec reference

The authoritative schema is `data_analytics_agent.reporting.schemas.ReportSpec`.
Pass one JSON string to create_report after publishing findings. For example:

```json
{
  "title": "Monthly sales",
  "blocks": [
    {"type": "narrative", "body": "Explain the evidence and limitations."},
    {"type": "metrics", "metrics": [
      {"label": "Revenue", "result_id": "saved-result-id", "column": "revenue",
       "row_index": 0, "number_format": ",.2f"}
    ]},
    {"type": "chart", "chart_id": "saved-chart-id", "summary": "Describe the trend."},
    {"type": "table", "result_id": "saved-result-id", "title": "Evidence"},
    {"type": "data_analysis", "analysis_id": "saved-analysis-id",
     "title": "Method and evaluation", "summary": "Explain the analytical method."}
  ]
}
```

Use real IDs returned by tools. Charts are shared immutable artifacts; do not
embed or rebuild ChartSpec in reports. Metrics bind stored values. Tables default
to 25 rows, and their captions identify the scope. Full saved data downloads are
separate API artifacts. Use previous_report_id for conversational revisions.
Theme colors/fonts/density and accessible tables remain supported. Render errors
return correction guidance. Partial findings must retain their unresolved
questions and may never be presented as a completed investigation.


## Evidence-bound period comparisons

Metric cards may include `comparison` instead of a free-text change. Use one
complete saved aggregate snapshot for both periods. Declare `metric_ref`, shared
`population`, unique `grain` columns including `period_column`, exact
`current_period`/`baseline_period` values and `baseline_row_index`; the current
row is the metric card's `row_index`. For rates/shares include the saved
`numerator_column` and `denominator_column`, with `rate_scale` 1 for fractions
or 100 for percentages. Saved unrounded rates must reconcile to those columns. The same value column and dimension keys must apply to both
rows. The renderer calculates absolute/percentage change and provides How
calculated? with exact bindings, formula and checks. Zero baselines have no
percentage change. Completeness remains unknown; transaction bounds are not a
cutoff. Source join correctness and catalog meaning still require source grounding.
Never label or format source units as a currency unless it is explicitly declared.

Use `unit_column` only for an actual saved unit label; both periods must agree.
Comparison cards cannot use free-text prefixes/suffixes to invent units. Without
a unit column, amounts remain source units (rates use their declared rate scale).
For table display, `column_formats` maps selected columns to Python format specs,
e.g. `{"calendar_year": ".0f", "revenue": ",.2f"}`. Use integer formatting for
numeric year labels to avoid displaying 2,022.

For title-only requests use `revise_report_title`, preserving stored blocks and
findings. Do not reconstruct the report with `create_report` for that edit.
