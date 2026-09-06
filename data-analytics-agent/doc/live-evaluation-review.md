# Live behavior review — September 6, 2026

Evaluations used the configured OpenAI `gpt-5.6-luna`, generated SQLite data,
and repository instructions. External tracing was disabled. The fixture has
120 monthly rows with revenue `100 + 2*t + 20*sin(2*pi*t/12)`; total revenue is
26,280. This is a useful correctness fixture, not evidence of performance on
messy real-world data. These are individual trials, not reliability estimates.

## Findings and fixes

The first descriptive trial answered correctly with SQL only and produced an
HTML report. It made nine tool calls, including a duplicate coordinator semantic
lookup and a report retry caused by passing a string where a theme object was
required. Clarifying ownership and the report contract reduced the next trial to
seven calls: four coordinator, three SQL specialist. That trial completed in
about 28 seconds, versus 39 seconds initially; model latency makes this an
observation, not a performance benchmark.

The first forecast trial made eight Python attempts and then failed while saving
its analysis: the model copied an execution UUID incorrectly, and the tool raised
an unhandled KeyError. The corrected implementation returns available execution
IDs and a repairable error. `finish_analysis` now returns control to the model,
so a failed save can be corrected. Named-input examples are explicit, and compact
lists/tuples are valid analysis outputs. Exact code and artifacts remain saved.

The next forecast trial completed with a chart and HTML report. Its damped ETS
holdout MAE was 0.307596 versus 24 for seasonal-naive. However, it performed only
one Python execution, so the multi-execution acceptance assertion failed. Its
residual-based intervals were also implausibly narrow compared with holdout
errors. This was an application completion, not an unqualified quality pass.
The evaluation now explicitly requests separate investigation and forecast steps;
the skill now asks the specialist to examine held-out errors and coverage before
presenting uncertainty. Merely increasing the execution count is not a quality goal.

## Why the coordinator appeared to call everything

The old event consumer assumed subgraph namespaces included specialist names.
They contain execution identifiers. As a result, specialist calls were attributed
to the coordinator. Also, LangGraph's tool-finished event omits the tool name;
the consumer replaced it with the literal `tool`, overwriting the original name.

Tool lifecycle recording now uses the framework callback's `lc_agent_name` and
retains the start event's tool identity through completion or failure. Duration
and handled failures are recorded too. The real Deep Agents harness regression
asserts that source SQL belongs to text-to-sql and report generation belongs to
the coordinator. A separate test covers handled and raised tool failures.

Streamlit shows running calls plus the five most recent completed calls directly
under the run phase, with agent, tool name, status, duration, delegation target,
and skill path where applicable. Full input/output remains expandable. Names also
remain visible in the completed-run timeline. The details panel has a stable key.
New backend code requires an API restart; refresh Streamlit. Existing saved
incorrect event labels are not migrated.

More coordinator work is appropriate when it creates charts, inspects relevant
derived evidence, publishes findings, saves an investigation, and renders its
report. Repeated metadata lookups, identical saved-data copies, and preventable
validation retries are overhead, not desirable autonomy. One forecast trial still
made a redundant saved-data copy while repairing SQL; efficiency remains an area
to assess on a broader task set.

## Local verification

152 tests passed, six opt-in tests skipped. Ruff checks and Streamlit AppTest
checks passed. Regression coverage includes tool identity, specialist attribution,
failed tool status, visible activity summaries, repairable execution references,
and scalar-list Python outputs. Live model checks are recorded separately above.

The explicit iterative trial then completed four successful Python steps, reused
derived artifacts, compared multiple models across five rolling forecast origins,
and produced the correct future values. It appropriately left probabilistic
interval bounds null instead of fabricating calibrated uncertainty for noiseless
data. A subsequent coordinator inspection of a nonexistent column exposed another
unhandled validation error. Inspection now returns available column names and a
repairable response; a regression verifies correction succeeds. This failure
reinforces that local happy-path harness checks do not establish live autonomy.


## Final iterative trial

The final opt-in forecasting test passed in 186 seconds. It completed four
successful Python executions in two analytical assignments, reused derived
artifacts, and made one warehouse query. The 12 future predictions match the
known fixture formula to a maximum absolute error of 1.71e-13; their total is
4,212. Trend-plus-month OLS holdout error was effectively zero, compared with
seasonal-naive MAE/RMSE of 24.

The agent distinguished degenerate model-error bounds from a +/-24 planning
sensitivity range anchored to baseline error. It explicitly did not claim this
range was a calibrated prediction interval. The saved HTML contains the shared
Plotly chart and that caveat. This supports the analytical workflow and honest
uncertainty handling on the fixture; it does not validate real-world interval
calibration.

The trace recorded 32 tool calls: 16 coordinator, 12 data-analysis, four SQL
specialist. One wrong artifact reference and two chart validation failures were
corrected without aborting the run or rerunning warehouse retrieval. This verifies
repair behavior, while also showing remaining inspection and formatting overhead.
One successful execution only inspected artifact metadata, which is not an ideal
use of Python. Lowering avoidable calls remains a product-quality improvement.

The final trace, answer, datasets, Python execution records, and HTML are retained
under `/private/tmp/analyst-live-final/`. Earlier trials are retained under
`/private/tmp/analyst-live-review/`, `/private/tmp/analyst-live-review-fixed/`, and
`/private/tmp/analyst-live-iterative/`. Review failures as well as the final pass.
