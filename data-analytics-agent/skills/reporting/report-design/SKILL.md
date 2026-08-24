---
name: report-design
description: Create or revise professional, accessible, self-contained HTML analytical reports from conversation-scoped SQL results, chart specifications, and statistical analyses. Use automatically after successful evidence-backed analysis and for explicit reports, infographics, briefings, findings summaries, data stories, or downloadable HTML presentations.
---

# Report design

Create an evidence-backed `ReportSpec`; never write HTML, CSS, JavaScript, data
URLs, or event handlers. The trusted `create_report` tool validates artifact
scope and renders the standalone document.

## Required tool contract

- Call `create_report` with exactly one model-supplied argument:
  `report_json="<JSON-encoded ReportSpec>"`.
- The decoded object requires `title` and `blocks`. Put result and analysis IDs
  inside typed blocks; there is no top-level `artifact_ids`, `instructions`,
  `output_format`, job, or status-polling contract.
- Read [report-spec.md](references/report-spec.md) before composing the payload.

## Workflow

1. Choose the report mode. For an ordinary completed analysis, use the compact
   automatic default below without asking questions. For an explicit report or
   revision, interpret the purpose, audience, key questions, evidence, and
   requested visual direction. Infer professional defaults when intent is
   clear. Ask one focused question only when ambiguity would materially change
   an explicitly requested report.
2. Discover relevant saved results. Reuse only artifacts from this conversation
   and source. A report may synthesize several compatible result IDs.
3. Identify evidence gaps. Obtain new reviewed SQL or reviewed statistical
   analysis through the existing specialists when needed. Do not fabricate
   values from samples or profiles.
4. Choose an information hierarchy and coherent design system. For a compact
   automatic report, use the renderer defaults and skip custom theme fields.
   For an explicitly designed report, read
   [design-quality.md](references/design-quality.md) before selecting theme,
   layout, charts, or infographic composition.
5. Read [report-spec.md](references/report-spec.md), then build one declarative
   `ReportSpec`. Use typed blocks to express content and composition; do not
   simulate unsupported markup.
6. Serialize the complete `ReportSpec` as a JSON string and pass it as the
   single `report_json` argument to `create_report`. Do not pass a nested object
   or HTML. Omit optional defaults and irrelevant theme fields to keep the call
   compact. Treat a returned report ID, version, hash, and message as
   authoritative.
7. If `create_report` returns `ok=false`, correct the listed field paths and
   retry once with a complete specification. Never repeat the same payload and
   do not loop. If the correction still fails, explain the unsupported or
   missing requirement to the user.
8. Tell the user the preview is ready and invite optional feedback or further
   analysis. Do not require approval or finalization.

## Compact automatic report

After an ordinary successful data-bearing analysis, create one concise report
from the exact final evidence without expanding the investigation:

- lead with a short narrative that states the answer and material assumptions;
- reuse the exact successful top-level `ChartSpec` when it adds decision value;
- include one purposeful table block for every material final result, normally
  with a small row limit rather than all rows;
- include the current completed statistical analysis when present;
- use the default theme and omit decorative metrics, callouts, or infographic
  blocks unless they materially improve comprehension.

Do not generate a report for a response without final evidence. Report creation
is presentation, not a reason to run extra SQL or Python after the analysis is
already sufficient.

## Content and artifact rules

- Preserve material qualifications, uncertainty, assumptions, warnings, and
  reproducibility. Distinguish observation, inference, and recommendation.
- The renderer automatically appends one `SQL queries` section containing the
  exact reviewed SQL for every referenced result. Do not add a duplicate
  provenance, result-ID, or SQL appendix block to the `ReportSpec`.
- Use a `table` block for stored result data. Set `include_all_rows=true` only
  when the requested report must show all rows; otherwise select the necessary
  columns and a purposeful `row_limit`.
- Use a `chart` block with a valid `ChartSpec` and a concise text summary of its
  main insight. Provide the table alternative unless the same data table is
  already adjacent and redundant.
- For coordinator-authored report charts, normally omit `chart.palette` so the
  renderer applies the report-safe blue/amber/teal design system consistently.
  Set a non-default palette only when its sequential or diverging meaning is
  analytically useful; do not vary palettes decoratively between blocks.
- Use `statistical_analysis` with `analysis_id` for a prior reusable analysis.
  For reviewed Python completed in this run, use `use_current_run=true` and the
  exact parent result ID. Keep method and interpretation faithful to the
  specialist output.
- Use `metrics` for a small set of decision-relevant values, not decorative
  duplication. Use `infographic` for a visual sequence, comparison, or compact
  explanatory data story.
- Use `previous_report_id` when revising an existing report. Preserve its
  purpose unless the user explicitly changes direction.
- Never place a complete hidden dataset in the document for speculative
  exploration. Embed all data only when the requested presentation needs all
  data.

## Open-ended design behavior

Infographic, statistical analysis report, executive briefing, exploratory
findings, comparison report, and data appendix are examples—not templates or an
allowlist. Translate any appropriate free-form direction into semantic theme
controls and typed blocks.

When the user has not specified a style, recommend or infer a direction suited
to the content, for example:

- **Narrative infographic** — strong visual hierarchy, concise annotated facts,
  a clear sequence, and a memorable takeaway.
- **Statistical analysis report** — restrained styling, prominent method and
  assumptions, diagnostic outputs, uncertainty, and careful interpretation.
- **Executive briefing** — decision-first headline, KPIs, risks, supporting
  evidence, and recommended actions.
- **Analytical deep dive** — denser evidence, several sections, charts with
  accessible data alternatives, and detailed reproducibility notes.

Do not force the user to select one of these labels.

## Safety boundary

The model controls report content and declarative design choices only. The
renderer owns markup, CSP, embedded assets, chart code, theme interaction, and
download bytes. Do not request or emit arbitrary scripts, remote assets,
iframes, raw HTML, or tracking. A render error is a specification error: revise
the typed spec or explain the unsupported requirement; never bypass validation.
