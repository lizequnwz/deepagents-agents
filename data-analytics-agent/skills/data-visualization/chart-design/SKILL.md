---
name: chart-design
description: Design one validated declarative ChartSpec from an existing chart-ready saved result. Use for chart selection, field-role mapping, heatmaps, maps, readability limits, and deciding whether SQL reshaping is required.
---

# Chart Design

## Respect the data boundary

- Design from the assigned saved result and its full-result profile. The sample
  rows illustrate values but do not define the full distribution.
- Keep business filters, aggregation, formulas, pivots, grain changes, missing
  value filling, and non-chart-native statistics in reviewed SQL.
- Use only presentation operations supported by `ChartSpec`: meaningful sort,
  category limit, bar orientation, labels, legend grouping, and palette.
  Histograms may bin one numeric observation column; box plots may calculate
  their native quartiles and whiskers.
- Request SQL reshaping when the result lacks the required columns or grain.

## Map fields by analytical role

- Bar: categorical, temporal, or discrete-numeric x; numeric y.
- Line or area: temporal, numeric, or meaningfully ordered categorical x;
  numeric y.
- Scatter: numeric x and one numeric y; optional nonnegative numeric size.
- Pie or donut: unique categorical x and one nonnegative numeric y.
- Histogram: one numeric observation x and a bin count; no y.
- Box: optional categorical x and one numeric observation y.
- Heatmap: categorical, temporal, or already-binned numeric x and y; one
  numeric value; exactly one row per x/y cell.
- Map: use valid location roles for the selected mode and a numeric value when
  the mode requires one.

Treat an explicitly requested chart type as a constraint. If its required
roles can be produced by SQL, request reshaping; if the source cannot support
them, report that the chart cannot be created.

## Keep the chart readable

- Use at most five y series.
- Use `category_limit` only with an explicit meaningful `sort_by`; retain both
  in the final spec. Do not limit categories when the user asks for all.
- Prefer line/area for ordered trends, bar for category comparisons, scatter
  for numeric relationships, histogram/box for distributions, and heatmap for
  a two-dimensional grid when the user did not prescribe a type.
- Pie/donut supports at most 12 slices. Bar and box support at most 30 displayed
  categories. Heatmaps support at most 500 populated cells.
- Use centroid markers for US ZIP and city/state maps. Use built-in
  choropleths only for US states and ISO countries. Coordinate maps require
  latitude and longitude. Do not request ZIP-boundary choropleths.

Use column names exactly as returned by the saved result. Give the chart a
specific title and concise axis labels; do not encode unsupported styling or
invent fields.
