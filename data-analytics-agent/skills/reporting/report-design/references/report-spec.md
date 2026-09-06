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
       "row_index": 0, "number_format": ",.2f", "prefix": "$"}
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
