# Deep-dive questions to test the agent

These are copy-ready manual test scenarios, not guaranteed answers or automated
benchmarks. Choose the stated source and start a new conversation for each
scenario unless it explicitly says to continue. Use Financial services only if
that source is available in your installation.

Start with **6** for a small, checkable upload, or **1 → 2 → 3** for a progressively
deeper Chinook investigation. Then try the report and run-control checks below.
Model calls use your configured provider. Forecasting and parallel investigations
usually take more work than descriptive questions.

| Scenario | Source | Main functionality |
|---|---|---|
| 1. Revenue change investigation | Chinook | Plans, SQL, multiple questions, reconciliation |
| 2. Trend and unusual months | Continue 1 | Saved-data reuse, Python, parallel assignments |
| 3. Forecast with a baseline | Continue 2 | Holdout evaluation, uncertainty, analytical limitations |
| 4. Artist and genre concentration | Chinook | Complete populations, correct joins, descriptive routing |
| 5. Clarification before analysis | Chinook | Metadata-only work and business clarification |
| 6. Checkable monthly upload | Attached CSV | Composer upload, schema review, parallel analysis |
| 7. Cash-flow investigation | Financial services | Signed flows, SQL → Python, anomalies |
| 8. Loan portfolio composition | Financial services | Status meaning, distinct counts, scope discipline |

For complex work, watch **Analysis plan** and **Work progress** without opening
Activity. Open **Activity** to inspect actual tool calls and SQL/Python. A plan
should advance as work finishes; a completed data-backed answer should have an
HTML report. Partial findings must identify unfinished work. Numerical results,
charts, scope and units should agree across the answer, saved evidence and report.

## 1. What explains the largest annual revenue change?

**Source:** Chinook music store.

> Investigate how invoice revenue changed across the calendar years represented
> in this source. Show a plan. First save a complete monthly series with invoice
> revenue, invoice count and average invoice value. Identify the largest absolute
> year-over-year revenue change, showing both its amount and percentage. For
> those two years, quantify the contribution of each billing country to the
> change and reconcile the country contributions to the overall change. Discuss
> whether invoice volume or average invoice value moved with revenue, without
> claiming causation. Keep all countries in the calculation. State whether source
> completeness is known; do not drop a year merely because its last transaction
> precedes year-end. Produce a compact report with useful charts and limitations.

**Check:** Detailed grounding and retrieval belong to the SQL specialist. This
is descriptive work; Python is not required. Invoice totals must not multiply
when joined to invoice lines. Country contributions should sum to the total
change. Top-country displays must not silently exclude the rest of the population.

**Follow-up:**

> Using the saved evidence, compare the country rankings by revenue and by
> contribution to the change. Explain why the largest market need not be the
> largest contributor. Query additional data only if the saved scope is insufficient.

## 2. Is the monthly pattern a trend or a few unusual observations?

**Continue scenario 1** so the monthly series already exists.

> Reuse the complete saved monthly invoice series. Show a plan and run two
> independent saved-data analyses in parallel: one assessing trend and possible
> seasonality, and one identifying unusual months after accounting for trend.
> Each analysis should explain its method, uncertainty or screening threshold,
> and limitations. Preserve every requested month and distinguish missing months
> from confirmed zero-activity months. Synthesize where the analyses agree or
> disagree, and produce a report with the original series and useful diagnostics.
> Do not treat an unusual value as a confirmed data error or a causal explanation.

**Check:** With `ANALYSIS_PARALLEL_WORKERS=2`, independent analysis assignments
can overlap. Source retrieval stays sequential. Suitable saved data should be
reused; new warehouse SQL needs a scope or freshness reason. Both analyses should
appear in the final evidence, with no results mixed between workers. Inspect
whether seasonality claims are supported by enough cycles.

**Follow-up:**

> Keep the original full-series findings. As a separate sensitivity analysis,
> estimate the trend after excluding only the single strongest unusual month
> identified above. Compare the estimates and explain how this changes the
> population and interpretation. Preserve the original artifacts.

## 3. Would a forecast beat a simple baseline?

**Continue scenario 2.** This probes analytical quality; a dedicated forecast
evaluation workspace is still roadmap work.

> Using the saved monthly invoice revenue, assess whether a six-month forecast
> is defensible. If the history is sufficient, reserve the last six observations
> as a chronological holdout and compare a simple baseline with one reasonable
> alternative. Use a seasonal-naive baseline only if there is enough seasonal
> history; otherwise explain the baseline you choose. Report MAE on the same
> holdout, avoid leakage, and do not select a method solely on training fit.
> Then refit the chosen approach on the full history and forecast the next six
> months with clearly labeled prediction intervals and their assumptions. Show
> actuals, the forecast boundary and forecast values. If a meaningful forecast
> or interval cannot be supported, explain why instead of inventing one. Include
> the comparison, limitations and report.

**Check:** Python owns modeling. Training and holdout periods must be distinct;
both methods must be scored on the same observations. Nominal interval coverage
is not measured forecast accuracy. A baseline winning, or a supported decision
not to forecast, is an acceptable analytical result.

## 4. How concentrated are sales, and does the aggregation matter?

**Source:** New Chinook conversation.

> Analyze sales concentration across all recorded invoice lines, first by artist
> and then by genre. Use line-item price times quantity as revenue. Calculate
> each group's revenue share, the top-five and top-ten cumulative shares where
> enough groups exist, and HHI on a declared scale. Use the complete populations
> for every denominator. Show a cumulative-share chart and a compact report.
> Explain how grouping artists into genres affects interpretation. Reconcile
> aggregate line-item revenue to invoice-header revenue without duplicating
> invoice totals; report any mismatch rather than assuming equality. Do not use
> playlist membership as evidence of purchases.

**Check:** Aggregations, ranking and descriptive concentration can stay in SQL.
The agent should declare whether HHI uses fractional shares or percentages.
Country, artist and genre joins must respect their grains. A top-ten preview is
not sufficient input for a full-population concentration calculation.

## 5. Does the agent clarify the question before measuring it?

**Source:** New Chinook conversation. Send these in sequence.

> Without querying transaction values, explain which measures could help assess
> sales performance and what business definitions you would need from me.

**Check:** Metadata discussion should not execute source-value SQL or produce an
empty report.

Then ask:

> Are we doing better? Ask me to define the metric and comparison period before
> calculating anything.

Answer the clarification with:

> Compare total invoice revenue in calendar 2025 with calendar 2024 across all
> billing countries. Use the full requested periods and the source's declared
> monetary units. Report the absolute and percentage change, with a country
> breakdown and a compact report. If source completeness is unknown, say so.

**Check:** The business question appears inline and resumes the investigation
when answered. The final scope should match the clarification. These dates target
the bundled Chinook example; adjust them if you replaced its data.

## 6. Upload a small dataset with known trend and anomaly checks

**Source:** Attach [monthly-index.csv](examples/monthly-index.csv) using the upload
button beside the chat input. This is synthetic data, not observed business data.
Include the question below with the attachment.

> Analyze all 24 complete monthly observations. month_index orders months 1–24;
> revenue_units is an index, not currency. Show a plan. Run two independent
> saved-data analyses in parallel: assess monotonic trend using Spearman
> correlation, and investigate unusual values using a Theil–Sen trend with
> residual-based screening. Explain tied values, any degenerate residual scale,
> and the limitations of inference from a short time series. Keep all rows,
> synthesize both findings, and create a compact report with a line chart.

In schema review, choose **Whole number** for both columns, declare one complete
month per row, and select `month_index` as the row key. Confirm the schema.

**Check:** Analysis must wait for confirmation, then the attached question should
start once. The file should have its own conversation with no warehouse access.
No currency should be invented. Open both analysis evidence panels.

Independent checks for this exact fixture:

- 24 rows, unique month indices 1–24, no missing values.
- Spearman correlation is approximately **0.9610617665**.
- SciPy's default Theil–Sen estimate has slope **3** and intercept **101.5**.
- Month **20** has value **225** and the largest positive residual, **63.5**.
- The residual MAD is **0**. Conventional robust z-scores are undefined; the
  report must explain any alternative screening rule instead of inventing a scale.

The p-value's interpretation still depends on assumptions about the time series;
matching a number alone is not enough to validate the analysis.

## 7. What explains unusual cash-flow months?

**Source:** New Financial services conversation.

> Investigate monthly cash flow during calendar 1998. Show a plan. Retrieve a
> complete monthly series of inflow, outflow magnitude, net cash flow and
> transaction count using the catalog's transaction-type definitions. Reconcile
> net cash flow to inflow minus outflow. Then use Python to screen for unusual
> months in net flow and explain the method's limitations with only 12 monthly
> observations. For the strongest candidate, ask SQL for a breakdown by operation
> and account branch district, and compare it with the preceding month when that
> month falls within 1998. Preserve the original monthly scope and distinguish
> descriptive contributors from causes. Report in the database's monetary unit.

**Check:** This is dependent work: SQL → Python → targeted SQL → synthesis, not
three independent assignments. PRIJEM is inflow; VYDAJ and VYBER are outflows
whose stored amounts are non-negative magnitudes. Gross activity must not be
presented as net flow. A small sample or weak anomaly evidence must be disclosed.

## 8. How does loan portfolio composition differ across districts?

**Source:** New Financial services conversation.

> Describe the recorded loan portfolio by the account's branch district and loan
> repayment status. Show a plan. Report distinct loan counts, approved principal,
> and count-based versus principal-based status shares. Keep completed contracts
> separate from active contracts and explain status codes A, B, C and D using the
> semantic catalog. Show both the largest portfolios and districts with unusual
> status composition, including their denominators so tiny portfolios are clear.
> Check that any joins to account relationships do not duplicate loans. Use the
> database's monetary unit. Produce an aggregate report; do not describe these
> recorded statuses as future default probabilities or recommend individual
> lending decisions.

**Check:** District means the account's branch district, not a client's residence.
Completed and active contracts have different meanings. The source does not
establish a currency or provide a longitudinal status history merely because
loans have approval dates. Detailed analysis remains descriptive unless a
separate, justified inferential question is posed.

## Follow-ups for reports, reuse and run controls

Use these after any scenario with a saved report and chart.

**Report-only revision:**

> Keep the findings, saved analyses and existing chart unchanged. Revise only the
> report title to “Investigation review”. Reuse the saved evidence; do not rerun
> SQL or Python.

Check that a new report version links to the previous version. Both turns should
render without duplicate chart-form errors. Open **Edit chart** on the new report;
change a title or axis label and save. This direct edit should require no model,
SQL or Python execution and should update the chart and report together.

**Correction during work:** Start scenario 1, then send this before findings are
published:

> Correction: restrict this investigation to invoices billed to the USA and
> Canada. Apply that scope consistently to the comparison and report, and state
> the scope change explicitly.

Check **Received** then **Applied**. An executing step may finish before the
correction takes effect. If findings were already published, the correction
belongs to a separate follow-up rather than rewriting the original answer.

**Stop and Resume:** Start scenario 2 or 6 and click **Stop** while work is active.
Wait until it pauses, then **Resume**. Saved evidence should remain available;
an interrupted step whose output was not committed may execute again. If the
example finishes before Stop is clicked, that run does not test cancellation.

**Separate approvals and worker limits:** In `.env`, set
`REQUIRE_SQL_APPROVAL=true`, `REQUIRE_PYTHON_APPROVAL=true`, and
`ANALYSIS_PARALLEL_WORKERS=2`, then restart both services. Scenario 1 should pause
for SQL review; scenario 6 should expose separate Python proposals. Approving one
worker must not approve another. Repeat scenario 6 in a fresh file conversation
with `ANALYSIS_PARALLEL_WORKERS=1` to check sequential execution. Restore your
preferred settings afterward; see [run controls](../development/configuration.md#controlling-a-run).

**Retry report:** If a real report-rendering failure occurs after findings are
saved, click **Retry report**. Previously completed SQL/Python must not run again;
the report should recover and the stale error clear. A successful report-only
revision is a different path and does not test failure recovery. Do not damage
saved files just to trigger a failure. Deterministic failure cases are covered by
the project's regression tests.

When reporting a problem, include the exact question, source, conversation/run
ID from the diagnostic panels, the relevant Activity error, and whether the issue
occurred before or after findings were published. Avoid including credentials.
