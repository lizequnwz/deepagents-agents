---
name: report-design
description: Compose the required polished HTML report from published findings and saved evidence.
---

# Report design

Publish findings first. Compose a declarative ReportSpec and pass its JSON to
create_report. Application rendering owns HTML, accessible tables, themes and
shared charts. Never write HTML/CSS/JavaScript. Every data-backed answer needs
its report, including supported partial analysis. Metadata-only answers do not.

Use a clear title and lead narrative answering the business question, then
purposeful charts/tables, interpretation, assumptions and limitations. Ordinary
questions need compact reports; match audience and visual direction for explicit
briefings. Keep evidence and claims consistent with published findings.
Published charts and analyses are attached automatically. Add explicit blocks only
to control placement or presentation; all references must belong to the published
selection. A successful create_report completes the turn without another answer.

Blocks use `type`:
- narrative: body, optional title/emphasis (`standard`, `lead`, or `muted`).
- table: result_id, title, optional columns/row_limit (default25).
- chart: chart_id from create_chart, summary, optional caption/show_data_table.
- data_analysis: analysis_id, title, summary, optional include_outputs.
- metrics: metrics list with label, result_id, column, row_index (default0),
  number_format (default ',.2f'), prefix/suffix. Values come from stored evidence.
- callout: title, body, variant insight/note/warning/action.
- infographic: title and items with label/description for qualitative concepts.

Metric bindings select one exact saved cell; they never aggregate rows. Match each
card's label to that row's population (for example, East sales cannot represent
all-region sales). Use one label per binding. An overall total requires its own
saved total cell. If the needed total was not saved before publication, omit the
card and use the supported narrative and table; do not substitute the first group
row or rerun analysis. Check each resolved card against the published answer.

For a period-comparison card, add `comparison` to the metric binding, for example:
`{"metric_ref":"total_revenue","population":"All invoice headers",
"grain":["calendar_year"],"period_column":"calendar_year",
"current_period":"2022","baseline_period":"2021","baseline_row_index":0}`.
The card's own row_index selects the current row of the same saved result.
metric_ref is an exact metric-name string; grain is an array of saved column names.
Omit prefix/suffix: comparison units come from a saved unit_column, otherwise source
units. The renderer supplies deltas and How calculated?; do not duplicate that
disclosure in a narrative block. Read references/report-spec.md for rates and units.

Reports accept title, subtitle, audience, blocks, footer, theme and
previous_report_id. Omit theme for the default styling. A custom theme is an
object (for example {"font_style":"editorial","density":"balanced"}), never
a string such as "default". Use previous_report_id for revisions. Reuse chart IDs from
chat; do not reconstruct charts. Unsupported offline maps become explanatory
tables. Report errors are repairable presentation errors: never rerun analysis.
