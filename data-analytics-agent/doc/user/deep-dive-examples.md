# Example questions: simple answers to complex reports

Updated 27 September 2026. Copy a question into the app after selecting its data
source. Start with the simple questions below; then try an investigation or a
sequence of follow-ups. Data-backed answers include an HTML report automatically,
so a simple total does not need a request for a large report or a plan.

**Sources:** choose **Chinook music store** (`chinook`) for music sales and
**Financial services** (`financial`) for transactions and loans. The bundled
Chinook dates are 2021–2025; the financial cash-flow example uses 1998. Amounts
remain in source units unless the catalog declares a currency. If you replace a
database, recheck its dates and expected values.

## Choose where to start

| What you want to try | Source | Example | Conversation |
|---|---|---|---|
| A simple annual revenue answer | Chinook | S1 below | New |
| A simple reconciliation | Chinook | S2 below | New |
| Customer ranking with clarification | Chinook | S3 below | New; answer the clarification |
| A small portfolio summary | Financial | S4 below | New |
| A KPI card with calculation details | Chinook | S5 below | New |
| A multi-part revenue report | Chinook | 01 | New |
| Trend, seasonality and unusual-month analysis | Chinook | 02 | Continue 01 |
| Forecast feasibility and holdout comparison | Chinook | 03 | Continue 01–02 |
| Artist/genre concentration report | Chinook | 04 | New |
| Business-definition discussion | Chinook | 05–06 | New, then continue |
| Analysis of your uploaded data | File upload | 07 | New file conversation |
| Cash-flow investigation with drill-down | Financial | 08 | New |
| Loan portfolio and district comparison | Financial | 09 | New |
| A title-only report revision | Chinook | 10 | Continue 01–03 |

Simple questions generally need fewer steps. Complex reports can involve several
source queries, Python analyses and presentation steps. Open Activity to inspect
progress, and use the evidence downloads to inspect complete results.

## Simple questions

These exact S1–S4 prompts were live-tested in the
[held-out corpus](../../tests/fixtures/held_out_examples.json). S5 was separately
[live-tested](../reviews/roadmap-evidence/comparison-final-manifest.json).

### S1: Annual revenue

**Source:** Chinook music store. Start a new conversation.

> For each represented calendar year, what was the sum of invoice totals? Include all countries and all years, label monetary units only if declared, and report the largest absolute change between adjacent years. Explain whether data completeness is known.

**What to look for:** Look for one row per year and a clear comparison. For the bundled database, annual revenue is 449.46, 481.45, 469.58, 477.53 and 450.58 for 2021–2025; the largest absolute adjacent-year change is +31.99.

### S2: Do the two revenue totals agree?

**Source:** Chinook music store. Start a new conversation.

> Compare total invoice-header revenue with the sum of invoice-line unit price times quantity. Check totals independently so joining the two grains cannot multiply invoice totals. Include every recorded purchase.

**What to look for:** Expect two independently calculated totals of 2328.60, with difference 0. This tests whether the agent avoids multiplying invoice totals when working with line items.

### S3: Most valuable customers — clarify first

**Source:** Chinook music store. Start a new conversation.

> Which customers are most valuable? Ask which business definition of value I intend before calculating.

When asked to clarify, reply:

> Use lifetime sum of recorded invoice-header totals per customer, not customer profitability or a future prediction. Show the top five with customer IDs and full-period revenue; do not infer a currency.

**What to look for:** The agent should ask for the meaning of value before calculating. With the clarification above, the top customer IDs are 6, 26, 57, 45 and 46; totals are 49.62, 47.62, 46.62, 45.62 and 45.62. The last two are tied.

### S4: Loan status summary

**Source:** Financial services. Start a new conversation.

> Count recorded loans and sum approved principal for each repayment status A, B, C and D. Include full-portfolio count shares and principal shares separately. Define the codes using the catalog; these are recorded statuses rather than predictions.

**What to look for:** Expect four status rows totaling 682 loans and 103,261,740 approved principal. Count shares and principal shares have different denominators.

### S5: Revenue comparison with How calculated?

**Source:** Chinook music store. Start a new conversation.

> Compare canonical total_revenue for calendar 2022 with 2021, over all invoice headers and all billing countries. Save one complete annual aggregate with one row per year. In the report, include a revenue metric card for 2022 with an evidence-bound period comparison to 2021 and a How calculated? disclosure. Use source units only, and leave source completeness unknown.

**What to look for:** Expect 2022 revenue 481.45 versus 449.46 in 2021, a change of +31.99 (+7.12%). Expand How calculated? to inspect saved values, formula and checks. Canonical binding may be disclosed as unverified for a transformed query; calculation checks do not prove source-join correctness.

## Complex reports and follow-up analysis

The following ten prompts keep their original IDs and exact wording for
reproducible testing in the [documented corpus](../../tests/fixtures/documented_examples.json).
For a first complex report, try **01**, **04** or **09**. For iterative analysis,
run **01 → 02 → 03 → 10** in one conversation. Run **05 → 06** in a separate
conversation; the other examples each start fresh.

**Latest verification:** the [27 September delivery review](../reviews/roadmap-implementation-2026-09-27.md)
records corrected units, undefined screening flags and title-only editing, plus
remaining repair and methodology limits. The [26 September review](../reviews/documentation-live-tests-2026-09-26.md)
is the historical baseline, not current failure status. A forecast refusal can be
a valid outcome; a completed report alone is not a correctness guarantee.

For exact reruns, use the [testing guide](../development/testing.md). SQL wording,
analytical method and report layout may vary across runs. These prompts were not
rerun as part of this documentation-only refresh; the linked dated trials provide
the observed live evidence.

## 01-revenue: Annual revenue change and reconciliation

**Source:** chinook. **Conversation group:** `revenue`.

> Investigate how invoice revenue changed across the calendar years represented in this source. Show a plan. First save a complete monthly series with invoice revenue, invoice count and average invoice value. Identify the largest absolute year-over-year revenue change, showing both its amount and percentage. For those two years, quantify the contribution of each billing country to the change and reconcile the country contributions to the overall change. Discuss whether invoice volume or average invoice value moved with revenue, without claiming causation. Keep all countries in the calculation. State whether source completeness is known; do not drop a year merely because its last transaction precedes year-end. Produce a compact report with useful charts and limitations.

**Check:** Expect 60 monthly observations spanning 2021–2025. The largest absolute annual change is 2022 versus 2021: +31.99 (+7.11743%). Country contributions must sum to 31.99. Invoice counts are 83 in both years. Source completeness is unknown; the final transaction date does not justify excluding a period.

## 02-trend: Trend, seasonality, and unusual months

**Source:** chinook. **Conversation group:** `revenue`.

> Reuse the complete saved monthly invoice series. Show a plan and run two independent saved-data analyses in parallel: one assessing trend and possible seasonality, and one identifying unusual months after accounting for trend. Each analysis should explain its method, uncertainty or screening threshold, and limitations. Preserve every requested month and distinguish missing months from confirmed zero-activity months. Synthesize where the analyses agree or disagree, and produce a report with the original series and useful diagnostics. Do not treat an unusual value as a confirmed data error or a causal explanation.

**Check:** Reuse the complete monthly result from example 01. Inspect separate Python evidence for trend/seasonality and residual screening. Verify all 60 months remain, methods and uncertainty are stated, and flagged values are not called proven errors or causes. Check overlap in worker events rather than assuming that two analyses ran concurrently.

## 03-forecast: Forecast against a baseline

**Source:** chinook. **Conversation group:** `revenue`.

> Using the saved monthly invoice revenue, assess whether a six-month forecast is defensible. If the history is sufficient, reserve the last six observations as a chronological holdout and compare a simple baseline with one reasonable alternative. Use a seasonal-naive baseline only if there is enough seasonal history; otherwise explain the baseline you choose. Report MAE on the same holdout, avoid leakage, and do not select a method solely on training fit. Then refit the chosen approach on the full history and forecast the next six months with clearly labeled prediction intervals and their assumptions. Show actuals, the forecast boundary and forecast values. If a meaningful forecast or interval cannot be supported, explain why instead of inventing one. Include the comparison, limitations and report.

**Check:** Inspect the generated Python: training excludes the last six observations, both methods use the same holdout, and the chosen approach is refit on the full history. Recompute MAE from saved predictions if supplied. A defensible refusal to forecast is acceptable. A nominal interval is not measured coverage.

## 04-concentration: Artist and genre concentration

**Source:** chinook. **Conversation group:** `04-concentration`.

> Analyze sales concentration across all recorded invoice lines, first by artist and then by genre. Use line-item price times quantity as revenue. Calculate each group's revenue share, the top-five and top-ten cumulative shares where enough groups exist, and HHI on a declared scale. Use the complete populations for every denominator. Show a cumulative-share chart and a compact report. Explain how artist-level and genre-level concentration differ; an artist may have tracks in several genres. Reconcile aggregate line-item revenue to invoice-header revenue without duplicating invoice totals; report any mismatch rather than assuming equality. Do not use playlist membership as evidence of purchases.

**Check:** Both artist and genre totals must reconcile to line revenue and invoice revenue of 2328.60. Share denominators use the entire purchased population. HHI declares its scale. Artist and genre are separate track attributes; there is no artist-to-single-genre hierarchy.

## 05-metadata: Metadata-only business discussion

**Source:** chinook. **Conversation group:** `clarify`.

> Without querying transaction values, explain which measures could help assess sales performance and what business definitions you would need from me.

**Check:** No warehouse-value query, Python execution, chart, or report should be created. Semantic discovery is appropriate. This checks routing, not numeric correctness.

## 06-clarification: Clarification before calculation

**Source:** chinook. **Conversation group:** `clarify`.

> Are we doing better? Ask me to define the metric and comparison period before calculating anything.

When the inline clarification appears, answer:

> Compare total invoice revenue in calendar 2025 with calendar 2024 across all billing countries. Use the full requested periods and the source's declared monetary units. Report the absolute and percentage change, with a country breakdown and a compact report. If source completeness is unknown, say so.

**Check:** The app should pause for a business clarification and resume the same run after the answer above. Calendar 2025 revenue is 450.58 versus 477.53 in 2024: −26.95 (about −5.64362%). Country contributions reconcile to that difference.

## 07-upload: Checkable uploaded monthly series

**Source:** upload. **Conversation group:** `07-upload`.

Attach [monthly-index.csv](examples/monthly-index.csv). It is synthetic index data, not currency. Confirm its schema before analysis.

> Analyze all 24 complete monthly observations. month_index orders months 1–24; revenue_units is an index, not currency. Show a plan. Run two independent saved-data analyses in parallel: assess monotonic trend using Spearman correlation, and investigate unusual values using a Theil–Sen trend with residual-based screening. Explain tied values, any degenerate residual scale, and the limitations of inference from a short time series. Keep all rows, synthesize both findings, and create a compact report with a line chart.

**Check:** Before analysis, review both columns as Whole number, declare one complete month per row, and choose month_index as the key. There are 24 rows. Spearman rho is approximately 0.9610617665. SciPy default Theil–Sen slope is 3, intercept 101.5; month 20 has the largest positive residual, 63.5. Residual MAD is zero, so conventional robust z-scores are undefined. The model must either leave scores and decisions missing when the rule is undefined, or explain a justified alternative rule and save its corresponding flags. False must not stand in for unassessed. Time-series inference limits must be stated.

## 08-cash-flow: Cash-flow investigation

**Source:** financial. **Conversation group:** `08-cash-flow`.

> Investigate monthly cash flow during calendar 1998. Show a plan. Retrieve a complete monthly series of inflow, outflow magnitude, net cash flow and transaction count using the catalog's transaction-type definitions. Reconcile net cash flow to inflow minus outflow. Then use Python to screen for unusual months in net flow and explain the method's limitations with only 12 monthly observations. For the strongest candidate, ask SQL for a breakdown by operation and account branch district, and compare it with the preceding month when that month falls within 1998. Preserve the original monthly scope and distinguish descriptive contributors from causes. Report in the database's monetary unit.

**Check:** Use PRIJEM as inflow and VYDAJ/VYBER as positive outflow magnitudes. Inflow minus outflow must equal net flow for every month. There are 12 months in 1998. A breakdown after screening is dependent on the Python result, so it must use the identified month and preserve branch-district meaning. Do not invent a currency.

## 09-loans: Loan portfolio composition

**Source:** financial. **Conversation group:** `09-loans`.

> Describe the recorded loan portfolio by the account's branch district and loan repayment status. Show a plan. Report distinct loan counts, approved principal, and count-based versus principal-based status shares. Keep completed contracts separate from active contracts and explain status codes A, B, C and D using the semantic catalog. Show both the largest portfolios and districts with unusual status composition, including their denominators so tiny portfolios are clear. Check that any joins to account relationships do not duplicate loans. Use the database's monetary unit. Produce an aggregate report; do not describe these recorded statuses as future default probabilities or recommend individual lending decisions.

**Check:** Count each loan once. Group by the account branch district, not client residence. Explain A/B as completed and C/D as active with their actual catalog meanings. Distinct loan counts, approved principal, and both share denominators must reconcile to source totals. Recorded statuses are not predicted default probabilities.

## 10-report-revision: Report-only revision

**Source:** chinook. **Conversation group:** `revenue`.

> Keep the findings, saved analyses and existing chart unchanged. Revise only the report title to “Investigation review”. Reuse the saved evidence; do not rerun SQL or Python.

**Check:** Reuse the preceding revenue/forecast conversation. The report title must change to Investigation review with previous_report_id lineage. Existing selected chart IDs and analysis IDs should be retained; no SQL or Python should execute. This tests the conversational title-edit tool. The direct **Edit report title → Save title** control changes the title without a model call. Neither path tests report-failure recovery.

## Additional interaction checks

These are control checks, not additional tested question variants. Their live
coverage is listed separately in the test record.

- Inspect a completed answer, its assumptions, full CSV/Parquet evidence, and HTML report.
- Use **Edit chart** to change a chart title and save the matching chart/report revision.
- Use **Edit report title** to change only the report title; findings, analyses and charts should remain unchanged.
- Expand **How calculated?** on a comparison card to inspect its saved current/baseline bindings.
- During an active run, Stop, wait for pause, then Resume; a completed run does not test cancellation.
- With review enabled, each SQL/Python proposal requires its own decision. Restore your chosen settings after the check.
- Use Retry report only when a presentation failure actually occurs. A report-only title revision is not a failure-recovery test.
- Dictation should fill the editable composer without sending. Test microphone permission, stop, retry, and explicit Send separately from analytical correctness.

For a problem report, record the example ID, exact prompt, source, conversation/run
IDs, relevant Activity error, and whether findings had already been published.
