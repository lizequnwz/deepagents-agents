# Chart Numeric Validation and Visualization Prompt Design

## Objective

Correct chart numeric validation so it follows each chart type's semantic
encodings, and strengthen agent instructions so chart-ready SQL and declarative
chart specifications preserve useful data shapes.

## Scope

- Replace blanket numeric validation of every `y` field with chart-specific
  numeric roles.
- Strengthen the visualization specialist prompt for chart selection, field
  mapping, readability, validation recovery, and heatmap grids.
- Strengthen upstream chart-ready SQL guidance so dimensional limits do not
  become arbitrary top-level row limits.
- Preserve the existing declarative `ChartSpec`, deterministic renderer,
  source/result provenance, feature flag, and one-chart-per-request contract.
- Do not add a regression test in this change.

## Numeric Encoding Rules

Validation will derive required numeric columns from chart semantics:

| Chart type | Required numeric encodings |
| --- | --- |
| Bar | every `y` series |
| Line | every `y` series |
| Area | every `y` series |
| Scatter | `x`, the single `y`, and optional `size` |
| Pie/donut | the single `y` value |
| Histogram | `x` |
| Box | the single `y` value |
| Heatmap | `value` only |
| Marker map | optional `value`; latitude/longitude for coordinate maps |
| Choropleth map | `value` |

`color` remains flexible because Plotly supports categorical and continuous
color encodings. Categorical or temporal axes remain valid where the chart
semantics permit them.

Existing special validation remains authoritative, including nonnegative pie,
marker-size, and marker-map values; coordinate ranges; unique heatmap cells;
chart readability limits; and result provenance.

## Implementation Shape

Add a small pure helper in visualization validation that returns the
deduplicated numeric columns required by a `ChartSpec`. `validate_chart_spec`
will apply the existing usable-numeric check to that result.

This keeps numeric role selection separate from value validation and makes a
future chart type or encoding a localized extension.

## Prompt Behavior

The visualization specialist will:

- inspect the saved result before choosing a chart or mappings;
- honor an explicitly requested chart type when it is compatible with the
  available fields;
- use semantic encoding guidance for all supported chart types;
- keep business aggregation, calculations, joins, and pivots in reviewed SQL;
- treat heatmap `x` and `y` as dimensions and `value` as the numeric measure;
- require unique heatmap `(x, y)` cells and preserve the useful grid;
- correct validation errors against the same saved result before generating;
- use readable titles, labels, orientation, ordering, category limits, and
  curated palettes without inventing data.

The text-to-SQL specialist will be told that chart limits apply to meaningful
dimensions or series. For heatmaps, it must not use a blind top-level row limit
that discards most grid cells. When dimensional reduction is necessary, it
must select the intended categories in SQL and retain all resulting grid cells.

## Error Handling

Validation errors will continue to identify the incompatible column. A
categorical heatmap axis will no longer produce a numeric-value error. Truly
non-numeric measures, invalid coordinates, duplicate heatmap cells, and empty
presentations will continue to fail before deterministic rendering.

## Verification

- Run the complete existing pytest suite.
- Run Python compilation checks.
- Re-run the supplied Chinook monthly-genre query shape without the blind
  `LIMIT 5`.
- Validate a heatmap with `x=month`, `y=genre`, and `value=sales`.
- Confirm deterministic Plotly rendering succeeds.

