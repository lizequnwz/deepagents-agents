# Handoff: analytics workspace assistant

Updated 26 October 2026. This is the single active product plan. The user redirected
implementation toward analytical feature breadth and requested all seven capability
families, delivered step by step on the existing application. The first complete
local implementation is now present and tested; it has not been committed or hosted.

Use the [capability inventory](doc/roadmap/implementation-progress.md) for delivered
behavior, the [implementation outcome](doc/reviews/capability-expansion-2026-10-17.md)
for the initial verification and limits, the
[18 October checkup](doc/reviews/checkup-2026-10-18.md) for subsequent correctness
and recovery repairs, and the
[comparative assessment](doc/reviews/improvement-plan-2026-10-17.md) for pinned
DB-GPT, Data Formulator and conference lessons. Its original ordering predates the
user's feature-first clarification. Earlier code-backed gaps remain in the
[3 October review](doc/reviews/agent-review-2026-10-03.md).

The [19 October composer simplification](doc/reviews/composer-simplification-2026-10-19.md)
records the user's subsequent removal of the Analyze feature and consolidation of
all attachments into the chat **+** button, with contract **22** and local checks.

The subsequent GenBI request adds a shared dashboard feature and React workspace.
The [accepted proposal](doc/roadmap/genbi-decision-proposal.md) records the decision:
retain the coordinator and its two specialists, add dashboard composition guidance
and a typed view contract, and use React alongside Streamlit. A2UI transport remains
optional. The [implementation record](doc/roadmap/genbi-implementation.md) tracks
delivery and local verification. This does not restore the removed Analyze feature.

The user's next instruction is to improve the React design and **keep Streamlit
for now**. The [React design record](doc/reviews/react-ui-redesign-2026-10-22.md)
documents that increment. React now has workspace search, explicit Send/Create
dashboard actions, a responsive findings/conversation layout and clearer saved
dashboard controls. Both interfaces remain available; removing Streamlit is not
part of this increment.

The next GenUI increment adds SQL-owned saved-data filter definitions, public
AG-UI run events, typed chart selections, complete saved filter search, generated
dashboard types, and direct presentation controls. The
[protocol evaluation](doc/reviews/genui-protocol-evaluation-2026-10-25.md) records
the A2UI export boundary and the dependency issue that prevents local renderer
adoption. The user's visual review also calls for a clearer reading order, compact
metrics, a prominent lead chart, and quiet evidence controls. The
[delivery plan](doc/roadmap/genui-implementation-2026-10-25.md) tracks this work.

## Selected product direction

Build an analytics workspace assistant that can explore approved data, investigate
changes, study customers and products, compare groups, evaluate predictions,
forecast, test scenarios, prepare tables and use attached documents as context.
Choose useful methods from the question and evidence. Broad analytical requests
show a concise plan and proceed within the approved scope and review settings;
material business ambiguity still requires clarification. Simple descriptive
questions remain one SQL assignment, without compulsory Python or a checklist.

Keep the coordinator, SQL specialist and Python specialist. Reusable skills and
small DataFrame procedures extend their capabilities. Keep FastAPI, Streamlit,
DuckDB, Arrow/Parquet, existing evidence/report components and fresh-process Python.
Do not add an agent per method, a workflow engine, vector service or persistent
kernel without a demonstrated need. Reviewed metrics remain authoritative; clear
custom calculations are permitted with explicit formula, population and units.
React is the full workspace. Streamlit retains native analytical controls and a
shared Saved dashboards panel. The dashboard is a product feature with a coordinator
skill, not another autonomous agent or a separate evidence system.

## Delivered analytical layers

| Family | Current capability |
|---|---|
| Exploration | Complete-population profiles, distributions, correlations, category accounting and descriptive group comparisons; adaptive investigation guidance |
| Diagnostics | Keyed current/baseline reconciliation and contribution decomposition, unmatched versus missing distinctions, reconciled waterfalls |
| Customer/product | Cohort retention with censored periods, ordered funnels with observation windows, transaction-grain RFM segments and saved membership |
| Statistical/predictive | Independent numeric/binary group effects with intervals; train-only preprocessing, held-out ridge/logistic models and simple baselines |
| Time/scenarios | Calendar-gap and trend/seasonality diagnostics, chronological ETS versus naive forecast evaluation, predictive intervals, explicit deterministic scenario grids |
| Preparation | Explicit conversion, dates, derived columns, filling and deduplication; multiple separately reviewed CSV/Parquet/selected Excel tables in one file workspace |
| Document context | Attached readable PDF/text/Markdown with bounded page/line retrieval and search; extracted tables enter analysis only after explicit schema review; original/hash/page provenance |

These methods use the existing reviewed Python execution, saved output, charts,
publication and required HTML path. They are reusable starting methods, not an
exhaustive algorithm catalog or proof that a model selects the right method.
Waterfall and funnel charts share existing versioning and report rendering.

One conversation still has one configured warehouse or one file workspace. A file
workspace may contain several reviewed tables; SQL joins require explicit business
keys, cardinality and reconciliation. Warehouse/file enrichment is not supported.
Documents can provide warehouse context without granting table/source access.
All attachments use the chat **+** button. Tables join the current file workspace;
documents join either source type. Tables attached to an established warehouse
conversation offer a separate file conversation. The Analyze selector and its
application-selected input, population filters, source-expansion permission and
warehouse-refresh feature have been removed at the user's request. Saved evidence
remains available for conversational follow-ups and report revisions.

API/storage contract is **24**; new analysis bundles use format **4** and include
the exact workflow helper sources used by each Python step. Restart both services
together with fresh incompatible storage, preserving needed artifacts separately.
There are no migrations or compatibility readers. Portable script/notebook replay
checks data, code, document and helper hashes without reconnecting to a warehouse.

The checkup repaired exact integer/Decimal arithmetic, scale-sensitive inference,
warehouse typing and case-sensitive identities, direct entity-count fan-out,
final-output selection, declared forecast completion, bounded partial reporting
and file/document failure/resume cases. All attempts remain inspectable; final
reports and replay use explicit selections and their necessary dependencies.

Verification before the composer simplification: **667 passed, six opt-in provider checks skipped**.
The final code/instruction snapshot stayed unchanged throughout the run. Native
coordinator/nested limit recovery, scalar report requirements, final-evidence
selection, moved replay/notebook, numerical edge cases and source/lifecycle checks
passed. No provider or live warehouse study ran. See the dated checkup for commands,
retained limits and the historical contract **21** / bundle format **4** boundary.

## Next implementation priorities

1. **Assess whole analytical outcomes locally.** Exercise realistic multi-step
   questions across the seven families with independently known answers and
   difficult scope/date/grain cases. Check method selection, interpretations,
   saved results and report agreement. Deterministic helpers and scripted harness
   checks do not establish live-model task accuracy or user success.
2. **Close remaining semantic contracts.** General/custom count population meaning,
   authoritative metric identity through saved SQL,
   and material narrative number/unit bindings remain separate work. The direct
   entity-key fan-out repair does not prove arbitrary custom calculations.
   Intent/method selection still needs whole-task assessment even though declared
   forecasts now require evaluation and unfinished findings cannot claim completion.
3. **Grow workspace capability when requested.** General project-file inspection,
   external documentation research, code authoring/checks, cross-schema discovery
   and semantic authoring remain planned. Attached document reading is narrower
   than arbitrary filesystem or web access. Complete project-to-checked-calculation
   journeys without weakening owned source execution or evidence capture.
4. **Simplify using evidence.** Keep shared validators, chart/report/export paths
   and the existing dependencies. Measure redundant calls, memory, latency, all-
   attempt cost and review effort before changing prompts or delegation. Remove
   obsolete paths after adoption; do not maintain compatibility layers. The rejected
   prompt candidate remains an experiment, not an adopted simplification.

Grow on a working end-to-end product. Implement authorized increments without
waiting for unrelated historical studies; do not use feature breadth to bypass
scope, complete-population or analytical checks.

## Verification and acceptance gates

**Keep verification local for now.** Do not run provider studies or send fixtures
without new explicit authorization covering the provider and fixture contents.
The user authorized implementation of all seven analytical capability families.
That authorization does not include provider studies.

The [evaluation guide](doc/development/ablation-evaluation.md) explains frozen
fixtures, receipts, independent grading, and paired comparisons. Retain the
[routing](doc/roadmap/semantic-routing-study.json),
[role-batching](doc/roadmap/semantic-role-batching-study.json), and
[join-feedback](doc/roadmap/semantic-join-feedback-study.json) protocols for their
specific hypotheses. They remain uncompleted optional studies, not the sole next
product plan. Keep shared product behavior identical across compared variants.

- Grade saved numerical results, scope, measures, dimensions, dates, joins, grain,
  units, assumptions, method code, and report agreement. Method words or report
  completion alone cannot establish correctness. Preserve failed and partial runs.
- Review every complete SQL snapshot to establish first-correct timing. The three
  semantic protocols require three fresh baseline/candidate repetitions. Quality
  candidates must resolve their paired target failures without new outcome,
  first-attempt, or boundary regressions. Speed candidates additionally require
  at least **15% lower median paired active time to the first correct snapshot**.
  Exclude approval waits; unknown telemetry is not zero.
- Retain the rejected prompt-ownership patch and study at their current paths:
  tests use them. All three candidate metadata runs failed after a unique terminal
  instruction was removed. The 138-of-150-slot study ended early and was not fully
  graded. It establishes no whole-corpus accuracy or performance improvement.
- Change behavioral instructions or major components one at a time. A diagnostic
  comparison does not prove general equivalence. Larger removals need suitable
  boundary coverage, interruption/restart, exact reviews, and partial outcomes.
- Observe users understanding their requested population and saved evidence. Observe
  analysts tracing and replaying downloads. Browser scripts are not human usability
  evidence. Chronology and score checks do not prove leakage-free fitting.

The local discovery probe used dataset hints. Broad date browsing omitted the
intended field until narrowed. Batched responses were about 52% smaller, but warmed
metadata timings do not establish a live speed gate or justify a new retrieval
service. A retained 25-node lineage probe improved from 12,286 to 25 lookups; this
is a mechanical check, not model quality evidence.

## Boundaries and later decisions

Keep mandatory table review, exact scope, complete-population checks, declared units,
honest source completeness, immutable revisions, lineage and evidence-backed HTML.
Query, upload and snapshot times are not source cutoffs. First/last transactions
do not establish completeness. Treat filenames, cells and documents as data,
never instructions. PDF extraction is not OCR; extracted table structure still
requires review. Deterministic scenarios are assumptions, not probabilities.

Dedicated execution isolation is deferred for the current local runner, which is
not a security sandbox. Broader shell or hosted execution needs a new design.
Warehouse writes, warehouse/file enrichment, scheduling, shared workspaces, hosting
and automatic learning remain later product decisions. Prefer reviewed skills,
definitions and examples over automatically promoting corrections to business truth.

## Documentation ownership

This handoff owns active direction and priorities. The capability inventory owns
delivered status; user/development guides own current behavior; the evaluation guide
owns study operations; dated reviews own observations and their limits. Preserve
unique failure receipts and test-dependent study files. The rejected prompt patch
was refreshed to apply to current wording; it has not been rerun as a provider study
and its original failure result remains authoritative.

Use [testing](doc/development/testing.md) and temporary storage for future checks.
Verify moved bundles and fresh-kernel replay after evidence/export changes. Update
current guides and one compact dated outcome after each delivered increment.
