# ReportSpec JSON contract

Pass one valid JSON-encoded string as `create_report(report_json=...)`. The
decoded value must be an object with `title` and `blocks`. Omit optional fields
when they are not useful; application defaults will apply. Shorter payloads are
more reliable, so do not restate default theme or block values.

Expected validation and rendering problems return `ok=false` with compact
`issues` containing JSON-style field paths. Correct those exact issues and
retry once; do not repeat an unchanged specification.

## Top level

```json
{
  "title": "Required report title",
  "subtitle": "Optional subtitle",
  "eyebrow": "Optional short category",
  "audience": "Optional intended reader",
  "design_direction": "Optional free-form visual direction",
  "theme": {
    "primary_color": "#1E40AF",
    "accent_color": "#D97706",
    "font_style": "modern",
    "density": "balanced",
    "corner_style": "soft",
    "color_mode": "adaptive"
  },
  "blocks": [],
  "footer": "Optional closing note",
  "previous_report_id": null
}
```

Theme fields are optional. Colors use six-digit hex notation and must pass
4.5:1 text contrast validation. `font_style` is `modern`, `editorial`,
`technical`, or `humanist`; `density` is `spacious`, `balanced`, or `dense`;
`corner_style` is `square`, `soft`, or `rounded`; and `color_mode` is `light`,
`dark`, or `adaptive`.

## Blocks

Use any ordered combination of these objects.

Narrative:

```json
{"type":"narrative","title":"Optional heading","body":"Paragraphs and simple Markdown lists.","emphasis":"lead"}
```

`emphasis` is `standard`, `lead`, or `muted`.

Metrics:

```json
{
  "type": "metrics",
  "title": "Key measures",
  "columns": 3,
  "metrics": [
    {"label":"Revenue","value":"$1.2M","change":"+8%","context":"versus prior period"}
  ]
}
```

Callout:

```json
{"type":"callout","title":"Decision","body":"Prioritize the highest-growth segment.","variant":"action"}
```

`variant` is `insight`, `note`, `warning`, or `action`.

Infographic:

```json
{
  "type": "infographic",
  "title": "Three-part story",
  "introduction": "Optional context.",
  "layout": "cards",
  "items": [
    {"label":"Signal","value":"42%","description":"What the evidence means."},
    {"label":"Response","description":"What to do next."}
  ]
}
```

`layout` is `steps`, `cards`, or `flow`.

Saved-result table:

```json
{
  "type": "table",
  "result_id": "scoped-result-id",
  "title": "Supporting data",
  "caption": "Optional caption",
  "columns": ["column_a", "column_b"],
  "include_all_rows": false,
  "row_limit": 25
}
```

Chart:

```json
{
  "type": "chart",
  "summary": "State the finding, not just the geometry.",
  "show_data_table": true,
  "chart": {
    "result_id": "scoped-result-id",
    "chart_type": "bar",
    "title": "Comparison",
    "x": "category",
    "y": ["value"],
    "x_label": "Category",
    "y_label": "Value",
    "sort_by": "value",
    "sort_direction": "descending"
  }
}
```

Use the established `ChartSpec` rules. Common chart types are `bar`, `line`,
`area`, `scatter`, `pie`, `histogram`, `box`, and `heatmap`. Self-contained map
reports are currently unsupported. Optional mappings include `color`, `size`,
`value`, `secondary_y`, labels, sorting, category limit, bin count, palette,
orientation, donut, and box-point behavior.
Sorting uses `sort_by` and `sort_direction`; there is no `sort` field. A
`category_limit` requires `sort_by` so the retained categories are
deterministic.

Statistical analysis:

```json
{
  "type": "statistical_analysis",
  "title": "Inference",
  "analysis_id": "prior-analysis-id",
  "summary": "Evidence-backed result summary.",
  "method": "Optional method detail.",
  "assumptions": ["Material assumption"],
  "interpretation": "Careful interpretation.",
  "include_outputs": true
}
```

For reviewed statistical Python completed in the current run, omit
`analysis_id` and instead set `use_current_run` to `true` plus the exact
`parent_result_id`. Use exactly one of those two reference forms.

## Minimal valid report

The `report_json` string may decode to only:

```json
{"title":"Findings","blocks":[{"type":"narrative","body":"The main finding."}]}
```

Do not add raw HTML, CSS, JavaScript, event handlers, remote URLs, or unknown
fields. The renderer owns executable and presentation code.
