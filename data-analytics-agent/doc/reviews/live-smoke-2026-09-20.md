# Live smoke tests and retry repairs — 20 September 2026

These trials used the configured OpenAI model (`gpt-5.6-luna`), the bundled
Chinook sample, and synthetic four-row CSVs. SQL/Python approval was automatic;
tracing remained disabled. They exercise representative paths, not the roadmap's
paired model-quality ablation or a cost benchmark.

## Observed outcomes

| Example | Outcome and independent check |
|---|---|
| Top artists by sales | SQL and HTML report completed. Independent source aggregation matched Iron Maiden 138.60, U2 105.93, Metallica 90.09, Led Zeppelin 86.13 and Lost 81.59. |
| Monthly invoice revenue | Complete 60-month series, 2021-01 through 2025-12; total 2328.60, range 23.76–52.62, median 37.62. Saved chart and report generated. A fresh run exposed a final-response validation failure after report creation; UI Retry report now completes it using the identical report, without another SQL query. |
| Trend and seasonality follow-up | Python reused the saved monthly series without source SQL. Independent statsmodels HAC calculation matched slope −0.00558155 per month, 95% interval [−0.0598624, 0.0486993], p=0.840278. |
| Reviewed CSV with ambiguous dates | Review explicitly chose DD/MM/YYYY and retained leading-zero identifiers. Region totals matched East 40 and West 60. A mistyped artifact ID initially caused publication failure; recovery completed with one saved SQL result. |
| Fresh upload entirely through UI | Native file picker → review → confirmed schema → live question → report completed. `sale_id` remained text. Four sales totaled USD 100: East 40 and West 60. Dollar signs display literally. Opening HTML revealed an incorrect overall metric card (40 instead of 100); the repair is described below. |
| Previously crashing conversation | Both existing report versions and all ten chart editors render without duplicate-form exceptions. No existing report or analysis was rewritten. |

The UI upload trial used:

```csv
sale_id,region,amount
001,East,10
002,West,20
003,East,30
004,West,40
```

The review declared one sale per row and USD amounts. The question requested
regional totals across all four records and a compact report.

Local artifact references (available while this workspace's history is retained):

- Monthly retry: run `a863f90f-81da-46f7-8d6d-e947b63de002`; report
  `a1bfd60c-2e94-4206-8537-d2b0503d9806` retained across retry.
- Python follow-up: run `3d030491-b159-45f1-8ba1-ab231945aa96`.
- Fresh UI upload: run `baed8def-c80f-4671-b661-5f6b6b8a2fbe`; report
  `993fa161-5574-4627-ad14-514bc3da2895` (original, with incorrect overall card).
- Corrected upload report: run `4a0ec600-153a-4d54-934d-3605e99509dc`; report
  `03058c9a-7c57-4db0-98c5-1b4eb210f298`, version 2. Browser inspection verified
  East USD 40, West USD 60 and the USD 100 narrative. The run only read the report
  skill, inspected saved evidence, published findings and created the revision;
  it performed no SQL or Python execution.

## Repairs prompted by the trials

- Fixed the launcher on macOS Bash 3 when reload arguments are empty.
- Retained model, independent SQL/Python review, source registry, time budgets
  and tracing controls in `.env.example`; standardized model selection on `MODEL_ID`.
- Escaped currency signs in chat prose and limited main evidence previews to ten
  rows, while retaining larger previews in the dataset inspector.
- Added guidance against inferring source completeness from the final transaction
  date and against inventing unspecified currencies. The original monthly trial
  made the former mistake; the fresh run preserved the full requested scope and
  used source units. Prompt guidance is not a deterministic correctness guarantee.
- Made invalid publication references recoverable tool errors and gave SQL
  specialists access to saved-result discovery.
- Used LangChain's schema-validation retry through `ToolStrategy` for final answers.
  A deterministic real-harness test deliberately adds an invalid `report_id`, then
  verifies correction without duplicate retrieval or report creation.
- Rejected conflicting metric-card labels that bind to the same saved cell.
  The live report bound both Overall sales and East sales to East's 40. A real
  report-tool regression now rejects that document, saves no invalid HTML, and
  accepts a corrected narrative plus the two regional cards. Report guidance
  explicitly requires overall metric cards to reference separately saved totals;
  cards do not aggregate rows. This catches conflicting bindings, not every
  possible semantic mislabeling; the broader checked-KPI roadmap remains open.
- Scoped chart editor forms by run, report and chart, with a real Streamlit
  regression that edits the intended reused chart instance.
- Retry clears stale errors and cancellation state, reuses intact reports,
  regenerates missing HTML, and repairs invalid/missing report specifications
  using published findings. Resume also selects report recovery after publication.
  Analysis tools reject new computation after publication. Retries reject attempts
  while earlier workers are still exiting and preserve cumulative usage.

## Local verification

`pytest -m 'not live'`: **234 passed, 6 deselected**. Ruff F checks and
`git diff --check` pass. The excluded marked-live tests are separate from the
manual configured-provider trials above. Only existing upstream warning
categories remain. Scope/label correspondence outside the conflicting-binding
check still depends on analytical review; this pass does not implement the full
checked-KPI contract.

## Product recommendations from the first pass

- Keep native UI upload, but make its entry more prominent. The current sidebar
  section is collapsed; Upload is enabled, while Review file requires a selection.
- Keep source assignments sequential. The agent framework supports concurrent tool
  calls, but broader parallel analytical assignments should first isolate their
  execution records and verify cancellation, approval and collection behavior.
  Parallelism is useful for independent saved-data analyses, not dependent steps.
- Keep assumptions and interpretation, collapsed by default. Surface material
  uncertainty and partial-result warnings beside the answer. Do not remove the
  evidence needed to interpret a result.

These changes were subsequently approved and implemented in the follow-up below.


## Approved follow-up: composer, parallel analysis and public plans

The native chat composer now accepts a CSV/Parquet attachment with an optional
question. Browser testing confirmed that schema review blocks analysis and that
confirmation sends the pending question once. An additional text-only follow-up
worked in the same composer. Assumptions start collapsed, while material warnings
remain visible.

The installed Deep Agents base harness did not expose `write_todos`, despite the
application policy referring to it. Explicit `TodoListMiddleware` now provides
that tool. A live 24-month synthetic example visibly progressed through two
independent analysis steps and report synthesis, then marked all three completed.
Both native subagent task starts preceded either completion (about 32.5 and 36.5
seconds per assignment). No tool failed in this run. The resulting report included
both analyses and a chart. Independent SciPy calculations matched Spearman
rho=0.9610617665, p=8.976399e-14, Theil–Sen slope=3, intercept=101.5, and month 20
as the largest positive residual. The report stated the zero-MAD limitation and
distinguished anomaly candidates from confirmed errors.

The subsequent report-title revision reused the same chart and produced version
2 with no SQL/Python execution. Both versions and their chart editors displayed
without duplicate-form exceptions. Calling retry on an already completed run
correctly returned 409 instead of creating another version. Failed-run recovery
is covered by the earlier live trials and the deterministic regression suite.

HTML inspection found intermediate analytical outputs crowding the report body.
Renderer 1.6 moves those into a collapsed inspection section, caps table previews
at ten rows without changing saved evidence, and keeps warnings visible.

Local references (while history is retained):
- Conversation: `7854760a-8d71-40e1-9454-d4081c551dfe`.
- Parallel example: run `25ac5be0-994c-4e64-8528-4cd0e110b8e7`;
  report `127135e9-23a0-45c6-a8ae-e9541df39932`.
- Report-only revision: run `9c688043-c626-4c79-a13e-9fb8112222de`;
  report `fdde1d77-7e94-4acb-a38f-14955adadbf4`.

Deterministic coverage now includes worker limits of one and two, colliding model
call IDs, isolated outputs, approval edits affecting only the selected worker,
Stop cancelling active/queued assignments, native attachment handoff, public plan
rendering, and compact report inspection details. These trials remain smoke checks,
not a benchmark of model accuracy or the roadmap's instruction ablation.

The final browser-verified renderer revision is report
`47aab772-1a52-4b36-8f09-319f09207970` (version 3), run
`e208a662-5716-4a1a-907f-b7765a8c6df5`. Both analysis-output sections and method
sections start collapsed; warnings are visible. This revision performed no SQL
or Python execution. The final deterministic suite passed **243 tests, 6 live
cases deselected**; Ruff F checks and whitespace checks passed.
