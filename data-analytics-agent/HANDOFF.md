# Deferred next steps

The current release focuses on iterative analysis over one configured SQL source
per conversation. Prioritize these separately after this workflow is verified:

1. File uploads and mixed-source analysis, with explicit dataset lineage.
2. Web/document research with source citations connected to analytical evidence.
3. Scheduling and proactive monitoring of saved investigations.
4. Semantic SQL checks for joins, denominators and time logic.
5. Notebook editing and manual chart-editing controls only if conversational
   refinement proves insufficient.

Cross-conversation automatic learning and persistent live Python kernels are
outside this version. No migration is required from obsolete in-memory state.
Live model evaluations require explicit authorization for fixture contents and
the configured provider. Deterministic tests and local browser verification
should run independently of that external evaluation.

## Implemented and locally verified

The application now uses durable SQLite metadata/checkpoints and typed Parquet
artifacts, an iterative `data-analysis` specialist, scoped saved-data SQL,
shared versioned charts, staged findings and required HTML reports, and saved
Streamlit conversations with Stop/Resume and report retry. See
[architecture](doc/architecture.md) and [operations](doc/operations-and-testing.md).

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
See [live behavior review](doc/live-evaluation-review.md) for individual outcomes,
methodological limitations, and regression verification. Seasonality, predictive
modeling, and conversational refinement still need their opt-in live evaluations.

Provider cancellation remains cooperative: a blocking warehouse request can keep
the UI in Stopping until it returns. LangGraph's v3 streaming API currently emits
an upstream beta warning; deterministic harness and checkpoint tests cover the
installed integration. The older standalone diagram exports are explicitly marked
historical; the current architecture document is authoritative.
