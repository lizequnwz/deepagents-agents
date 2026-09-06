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

Blocks use `type`:
- narrative: body, optional title/emphasis.
- table: result_id, title, optional columns/row_limit (default25).
- chart: chart_id from create_chart, summary, optional caption/show_data_table.
- data_analysis: analysis_id, title, summary, optional include_outputs.
- metrics: metrics list with label, result_id, column, row_index (default0),
  number_format (default ',.2f'), prefix/suffix. Values come from stored evidence.
- callout: title, body, variant insight/note/warning/action.
- infographic: title and items with label/description for qualitative concepts.

Reports accept title, subtitle, audience, blocks, footer, theme and
previous_report_id. Omit theme for the default styling. A custom theme is an
object (for example {"font_style":"editorial","density":"balanced"}), never
a string such as "default". Use previous_report_id for revisions. Reuse chart IDs from
chat; do not reconstruct charts. Unsupported offline maps become explanatory
tables. Report errors are repairable presentation errors: never rerun analysis.
