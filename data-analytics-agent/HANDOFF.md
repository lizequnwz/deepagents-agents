# Analytics workspace handoff

This is the active product plan. The [documentation index](doc/README.md) links to
the current user and development guides.

## Product direction

Build on the existing local analytics workspace. The seven delivered capability
families cover exploration, diagnostics, customer and product analysis, statistical
comparison and prediction, time series and scenarios, data preparation, and attached
document context. Choose methods from the question and evidence. Broad requests get
a short plan and proceed within the approved scope and review settings. Clarify
material business ambiguity. Simple descriptive questions use one SQL assignment.

Keep the coordinator, SQL specialist and Python specialist. Extend the analytical
methods with reusable skills and small DataFrame procedures. Keep FastAPI, DuckDB,
Arrow/Parquet, fresh-process Python and the shared evidence, chart, report and export
paths. Reviewed metrics are authoritative. Custom calculations require an explicit
formula, population and units.

Streamlit is the default workbench and includes the shared Saved dashboards panel.
React is the optional full workspace. Both clients use the same services and
evidence. Each conversation uses one
configured warehouse or one file workspace. File workspaces can combine separately
reviewed tables using established business keys and verified cardinality. Documents
can provide context in either workspace. See the [user guide](doc/user/using-the-agent.md).

## Dashboard and interface decisions

- Dashboards are composed by the coordinator over saved evidence, using a typed
  specification and immutable revisions. A new analytical view advances only after
  its evidence and matching HTML report are ready. Direct presentation edits reuse
  saved evidence. SQL owns reusable saved-data filter definitions and configured
  review applies. Source refresh and new calculations use the existing specialists.
- AG-UI events expose the public state of an existing run. Reconnect observes that
  run, while the application retains ownership of execution, reviews and persistence.
  The application exports a bounded A2UI v0.9.1 surface with evidence references.
  The local interface uses its existing React renderer. A maintained A2UI renderer
  requires a supported dependency tree and browser verification before adoption.
  Keep the existing application runtime. See the [architecture](doc/development/architecture.md).
- Lead with the saved title and scope, compact metrics and a primary chart. Place
  supporting data and evidence afterward. Keep required reviews visible and preserve
  exact values and saved layout choices. See the [workspace design system](design-system/analytics-workspace/MASTER.md).

## Next implementation priorities

1. **Assess whole analytical outcomes locally.** Exercise realistic multi-step
   questions across the seven families with independently known answers and difficult
   scope, date and grain cases. Check method choice, interpretations, saved results
   and report agreement. Observe readers finding the main result, changing a filter,
   inspecting evidence and replaying downloads.
2. **Complete unavailable-value presentation.** Show unavailable aggregates explicitly
   and consistently in cards, charts and reports. Preserve their distinction from zero.
3. **Close remaining semantic contracts.** Establish population meaning for general
   and custom counts, preserve authoritative metric identity through saved SQL and
   bind material narrative numbers and units to evidence.
4. **Measure before simplifying.** Isolate changes to prompts or delegation. Track
   redundant calls, latency, memory, all-attempt cost and review effort. For dashboards,
   measure filter completion, report creation, reconnect and time to the first useful chart.
5. **Grow workspace capability when requested.** General project-file inspection,
   external documentation research, code authoring and checks, cross-schema discovery
   and semantic authoring remain planned. Preserve source ownership and evidence
   capture as these workflows expand.

## Verification and acceptance

**Keep verification local.** The user authorized implementation of all seven
analytical capability families. Obtain separate explicit authorization covering the
provider and fixture contents before sending them. Use isolated temporary storage
and the [testing guide](doc/development/testing.md) for reproducible local checks.

- Independently grade saved values, scope, measures, dimensions, dates, joins, grain,
  units, assumptions, method code and report agreement. Preserve failed and partial
  runs. Check held-out chronology and the fitting code for leakage. Verify moved
  bundles and fresh-kernel replay after evidence or export changes.
- The optional [routing](tests/fixtures/ablation/semantic-routing-study.json),
  [role-batching](tests/fixtures/ablation/semantic-role-batching-study.json) and
  [join-feedback](tests/fixtures/ablation/semantic-join-feedback-study.json) protocols
  require three fresh repetitions per variant, with shared product behavior
  held fixed. Review every complete SQL snapshot. Quality candidates must resolve
  their paired target failures without outcome, first-attempt or boundary regressions.
  Speed candidates also need at least **15% lower median paired active time to the
  first correct snapshot**, excluding approval waits. Treat missing telemetry as
  unknown. See the [paired evaluation guide](doc/development/ablation-evaluation.md).
- Preserve the coordinator's terminal-response instruction when testing prompt
  changes. Removing it caused three metadata-only failures in the rejected
  candidate. See the [prompt study and receipts](doc/development/ablation-evaluation.md#historical-prompt-study).

## Boundaries and later decisions

Keep explicit table review, exact scope, complete-population checks, declared units,
source completeness, immutable revisions, lineage and evidence-backed HTML. Establish
completeness through an explicit source cutoff or completeness statement. Treat file
metadata, cells and document text as data. Review extracted tables before calculations.
Scenario grids express assumptions. Forecasts require a validated evaluation to be
published as complete.

Dedicated execution isolation, broader shell or hosted execution, warehouse writes,
warehouse/file enrichment, scheduling, shared workspaces and automatic learning
remain later decisions. Prefer reviewed skills, definitions and examples for reusable
business knowledge.
