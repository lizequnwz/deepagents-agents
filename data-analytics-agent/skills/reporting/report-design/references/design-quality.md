# Report design-quality checklist

Apply these rules when constructing `ReportTheme` and choosing report blocks.

## Information design

- Lead with the report's decision, question, or primary finding.
- Establish hierarchy through type scale, spacing, and contrast rather than
  decoration or color alone.
- Keep one coherent visual language across the document.
- Prefer a readable narrative sequence: context, evidence, interpretation, and
  implications. Move secondary detail to methodology, provenance, or appendix
  blocks.
- Use a bento-style metric or infographic grid only when its cards form a clear
  group. Avoid a dashboard-like grid for long-form narrative.

## Typography and layout

- Use `modern` for broad professional use, `editorial` for narrative reports,
  `technical` sparingly for engineering/audit material, and `humanist` for a
  warmer explanatory tone.
- Use balanced density by default. Choose dense only for genuine analytical
  depth; choose spacious for short executive or infographic formats.
- Keep body copy concise and scannable. Use sequential headings and short
  paragraphs; avoid wall-of-text blocks.
- Make the mobile reading order identical to the semantic order.

## Color and accessibility

- Choose semantic colors with sufficient text/background contrast. Normal text
  requires at least 4.5:1; meaningful graphical elements require at least 3:1.
- Never encode status or series identity with color alone. Reinforce it with
  labels, text, position, or shape.
- Avoid red/green-only comparisons and low-contrast gray-on-gray text.
- Keep focus states and keyboard interaction available. Do not rely on hover.
- Write useful chart summaries and figure descriptions. Provide table
  alternatives for charts.
- Respect reduced motion. Motion may clarify interaction but must not decorate
  or delay comprehension.

## Charts and tables

- Match the chart to the question: trend → line; category comparison → bar;
  relationship → scatter; distribution → histogram or box; matrix → heatmap.
- Avoid pie/donut when there are more than five categories; use a bar chart.
- Label axes and units. Keep legends close to the chart and exact values
  reachable.
- Do not overload one chart with unrelated measures or excessive categories.
- Use tabular figures for numbers. Choose the smallest useful column set and
  preserve a logical column order.
- A chart's summary should state the finding, not merely describe its geometry.

## Professional finish

- Use concise titles and sentence casing.
- Use whitespace to group related evidence and separate conceptual sections.
- Avoid emoji as structural icons and avoid mixed visual effects.
- Include material caveats near the affected evidence rather than hiding them
  only in a footer.
- End with the implication, action, or next analytical question when the
  audience benefits from one.
