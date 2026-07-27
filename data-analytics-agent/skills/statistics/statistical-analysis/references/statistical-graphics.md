# Statistical graphics

Create figures that answer an analytical or diagnostic question. Avoid
decorative charts and redundant panels.

## Choose the graph from the analytical purpose

- Show distributions with points, ECDFs, histograms using defensible bins, or
  density estimates paired with raw-data context. Do not use density curves for
  very small samples.
- Compare groups with raw observations plus compact summaries and uncertainty.
  Avoid bar charts of means when the distribution or sample size matters.
- Show relationships with scatterplots and an appropriate fitted trend. Display
  transformed scales honestly and do not extrapolate beyond observed support.
- Diagnose models with residual-versus-fitted, Q-Q, scale-location, influence,
  calibration, or partial-effect plots as the method requires.
- Show estimates with confidence intervals for coefficients, contrasts, and
  subgroup effects. Include a meaningful reference line when one exists.
- For repeated or paired data, connect matched observations or show within-unit
  changes. Do not plot them as independent groups.

## Make the figure interpretable

- Use matplotlib or seaborn and return the underlying Figure or Axes through
  `analysis_outputs`.
- Give the figure a descriptive title and label axes with readable names and
  units. State transformations in the label.
- Use consistent encodings, accessible contrast, and restrained color. Do not
  rely on color alone when groups can be distinguished another way.
- Make uncertainty bands and interval definitions clear. Do not imply that a
  fitted line is causal.
- Annotate sample sizes or major exclusions when they affect interpretation.
- Keep legends concise and avoid truncated axes that exaggerate differences.
- Keep each figure within 1600x1200 pixels and 1 MB; return at most four figures.

## Preserve analytical honesty

Choose scales and ranges before looking for the most dramatic presentation.
Show influential observations when they are part of the analysis. If privacy or
density makes raw points inappropriate, explain the aggregation or sampling used
for display; never sample the data used for the statistical calculation unless
the method explicitly requires it.
