# Deferred next steps

The current release supports iterative analysis over one configured SQL source
or one reviewed CSV/Parquet file per conversation. Read the
[implementation log](doc/roadmap/implementation-progress.md) for delivered work
and remaining gates, then the [19 September roadmap](doc/roadmap/roadmap.md)
for the priority order of subsequent work.

Start with an inspectable metric definition, a checked comparison, outcome-based
evaluations, and scope-aware result controls. Direct chart-title/style edits
and explicit forecast interval labeling have already been delivered.

Then add selected-scope follow-ups, shared filters, and manual report refresh.
Reviewed context improvements and metric-driver investigations build on those
contracts. Web/document evidence, additional export formats, and integrations
remain demand-led expansions. Scheduling depends on validated refresh; mixed-source
analysis requires an explicit change to the source-isolation policy. Notebook
editing remains deferred.

Cross-conversation automatic learning and persistent live Python kernels are
outside this version. No migration is required from obsolete in-memory state.
Live model evaluations require explicit authorization for fixture contents and
the configured provider. Deterministic tests and local browser verification
should run independently of that external evaluation.

## Implemented and locally verified

The initial roadmap increments now include minimal onboarding, direct chart
presentation edits with matching immutable report revisions and failure/retry,
collapsed report previews, explicit interval/range labels and methods, and
isolated CSV/Parquet uploads with mandatory schema review. Subsequent work added
chat attachments, bounded independent analysis assignments, and visible plans.
See the [implementation log](doc/roadmap/implementation-progress.md) for verification
and the remaining gates. Checked KPI comparisons and prompt ablations
remain open; direct presentation editing does not replace agent report composition.

The application now uses durable SQLite metadata/checkpoints and typed Parquet
artifacts, an iterative `data-analysis` specialist, scoped saved-data SQL,
shared versioned charts, staged findings and required HTML reports, and saved
Streamlit conversations with Stop/Resume and report retry. See
[architecture](doc/development/architecture.md),
[backend development](doc/development/backend-development.md), and
[user workflow](doc/user/using-the-agent.md).

Local verification covers the actual Deep Agents descriptive workflow with a
scripted model; real Python forecasting and seasonal-baseline evaluation;
100,000-row extraction, storage, analysis and full downloads; restart/checkpoint
resumption and exact reviewed edits; budget/cancellation behavior; report retry;
and Streamlit navigation and controls. The tutorial executes without model calls.
Browser checks used a separate synthetic fixture server, including report preview
and an HTML download. This does not establish live-model analytical quality.

Provider-invocation evaluations in `tests/test_live_evaluations.py` use only
synthetic fixtures and repository instructions. The user authorized live trials
on September 6, 2026. Descriptive and forecasting trials were run against the
configured OpenAI `gpt-5.6-luna`, with external tracing disabled. They exposed
activity attribution/name loss and repairable tool-input errors, now corrected.
Later configured-provider trials are recorded in the
[20 September smoke-test record](doc/reviews/live-smoke-2026-09-20.md), including
trend analysis, uploads, parallel analysis, and report-only revisions. These smoke
checks do not establish predictive accuracy or replace held-out evaluations.
The [improvement roadmap](doc/roadmap/roadmap.md) records the remaining quality
work and its methodological limits.

Provider cancellation remains cooperative: a blocking warehouse request can keep
the UI in Stopping until it returns. LangGraph's v3 streaming API currently emits
an upstream beta warning; deterministic harness and checkpoint tests cover the
installed integration. The current architecture document is authoritative;
the [diagram index](doc/diagrams/README.md) identifies the retained visual sources.
