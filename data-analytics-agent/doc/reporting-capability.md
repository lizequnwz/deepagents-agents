# Shared charts and required reports

The coordinator publishes findings and then creates their HTML report. The run
is successful only when the report exists. Metadata-only answers are exempt.
Themes, accessible tables, report preview/download and conversational revisions
remain supported. Offline maps render an explanatory table where required.

`create_chart` validates and persists immutable versions. SQL and Python-derived
datasets are supported. Uncertainty bands use lower_bound/upper_bound on line
charts; error_y supports estimate error bars. Several purposeful charts may
appear, and scalar answers can use metrics/tables. Chart revisions reference
previous_chart_id; reports reference the exact chart_id shown in chat.

`ReportSpec` holds narrative, result/analysis references and chart references.
Metric cards bind result_id, column, row_index, number_format and optional
prefix/suffix to stored evidence. Rendering never depends on model-authored
numeric metric strings. `previous_report_id` creates a new report version.

See `skills/reporting/report-design/SKILL.md` and the generated Pydantic schema
for the current block contract. On a report error the saved findings remain
visible. Retry uses the stored specification and artifacts without computation.
