# Reporting capability

## Status

Reporting is implemented as a feature-flagged coordinator capability with a
lazy-loaded report-design skill, strict declarative contracts, scoped artifact
resolution, a trusted HTML renderer, process-local versioned storage, and
Streamlit preview/download. The analytical topology remains one coordinator
and three specialists.

## Product goal

A user can ask for a report at any point in a conversation. The request may use
analysis that already exists or require the coordinator to plan additional SQL,
visualization, or statistical work first. The result is a professional,
responsive, self-contained HTML document that Streamlit can preview and the
user can immediately download.

The request language stays open-ended. Examples include:

- an infographic that explains the most important findings visually;
- a statistical analysis report with method, assumptions, diagnostics,
  estimates, uncertainty, and interpretation;
- an executive briefing organized around decisions, KPIs, and risks;
- an exploratory findings report with evidence and follow-up questions;
- a comparison, trend, operational, or audit-oriented report;
- a data appendix or another structure described by the user.

These are suggestions, not an allowlist or fixed template catalog. The user may
specify any appropriate audience, tone, style, structure, density, format, or
visual direction. When a request is sufficiently clear, the coordinator infers
a professional direction. It asks a focused clarification only when ambiguity
would materially change the result, and may recommend a few relevant
directions with short descriptions.

## Why this begins as a coordinator skill

Reporting is initially a synthesis capability, not a fourth analytical domain.
The coordinator already owns conversational intent and receives the artifacts
produced by the text-to-SQL, visualization, and statistical-analysis
specialists. Keeping reporting in the coordinator avoids another model call,
handoff contract, context transfer, prompt, and failure path.

The lazy-loaded skill lives at `skills/reporting/report-design/` and is exposed
to the coordinator only. Detailed report instructions stay in the skill rather
than permanently expanding the coordinator prompt.

The skill may later move unchanged into a reporting specialist if one or more
of these conditions becomes material:

- report composition regularly consumes too much coordinator context;
- report jobs need independent queuing, cancellation, budgets, or retries;
- users need long-running or independently revisable report workspaces;
- report generation develops specialist tools or an artifact lifecycle that
  obscures ordinary coordinator routing;
- measured quality improves enough with an isolated report model to justify
  the extra latency and orchestration.

Creating a specialist before those conditions appear would add complexity
without establishing a useful isolation boundary.

## Ownership model

| Component | Responsibility |
| --- | --- |
| Coordinator | Understand the report request, retain conversational context, identify evidence gaps, invoke existing specialists, ask material clarifications, and own user-facing wording |
| Report-design skill | Turn free-form requirements and available evidence into a `ReportBrief` and validated `ReportSpec`; apply layout, visual, accessibility, and content-quality guidance |
| Existing specialists | Produce reviewed SQL results, chart specifications, and reviewed statistical outputs through their existing contracts |
| Artifact resolver | Resolve only same-thread, same-source artifact references and supply full required data to trusted application code without copying it through model messages |
| Trusted renderer | Convert the validated specification and resolved artifacts into one deterministic, self-contained HTML file |
| `ReportStore` | Retain report ID, thread/source provenance, specification, HTML, version lineage, input references, renderer version, and content hash for the process-local POC |
| Streamlit | Show an isolated preview, collect optional feedback, request revisions or further analysis, and offer the current safe version for download |

The report skill does not execute SQL or statistical Python. When evidence is
missing, the coordinator invokes the existing specialist and preserves its
ordinary review boundary. Report generation itself is read-only and does not
need a new security approval step.

## User and orchestration flow

1. The user asks for a report or infographic, optionally specifying audience,
   purpose, content, tone, style, structure, or visual treatment.
2. The coordinator discovers relevant artifacts from the current conversation
   and source. A report may combine multiple compatible artifacts, but never
   cross a thread or source boundary.
3. If evidence is missing, the coordinator briefly states the analysis plan
   and invokes text-to-SQL, visualization, or statistical analysis. Existing
   SQL and Python approve/edit/reject flows remain authoritative.
4. The coordinator loads the report-design skill and produces a structured
   brief and specification. It does not write arbitrary executable HTML.
5. Application code validates the specification, resolves its scoped artifact
   references, and renders self-contained HTML.
6. Streamlit presents the safe preview and an immediately available HTML
   download. The coordinator may invite feedback, propose further analysis, or
   create a revised version; no mandatory approval or finalization state exists.

Every revision is independently downloadable. Version metadata should retain
the previous report ID or version, its inputs, and renderer version so the
application can explain what changed without treating one version as formally
approved.

## Structured contracts

Use an open, versioned schema rather than a closed set of templates. A useful
contract split is:

### `ReportBrief`

Captures the interpreted request before layout decisions:

- purpose and intended audience;
- primary questions and key messages;
- requested or inferred tone, style, density, and reading order;
- required evidence and available artifact references;
- requested sections, constraints, and optional calls to action;
- unresolved questions that materially affect the result.

### `ReportSpec`

Describes the rendered document declaratively:

- schema version, title, subtitle, locale, and document metadata;
- semantic design tokens for color, typography, spacing, radius, elevation,
  motion, and light/dark behavior;
- responsive layout regions and an ordered list of typed content blocks;
- scoped bindings to SQL results, chart specs, statistical outputs, and safe
  media assets;
- accessibility text, chart summaries, table alternatives, footnotes,
  methodology, and provenance;
- renderer-owned interaction options selected from an audited capability set.

The block model is extensible rather than tied to named report types. The first
renderer supports narrative, metric grid, callout, infographic composition,
table, chart, and statistical-analysis blocks. Headings, methodology,
provenance, and appendices can be expressed through those semantic blocks. New
block types extend the schema and renderer without granting the model an
executable-code escape hatch.

The model may define content, composition, semantic tokens, safe chart
bindings, and inline SVG instructions supported by the schema. It may not
provide arbitrary JavaScript, event handlers, remote embeds, or unsanitized
HTML.

## Artifact and data rules

- Reports may combine multiple artifacts only when every artifact belongs to
  the current conversation and immutable source.
- Every evidence-bearing block retains its input artifact references so
  provenance can be displayed or inspected.
- Full result rows remain outside model messages. The model works from bounded
  samples and profiles; the trusted renderer resolves referenced data directly
  from application stores.
- The self-contained HTML includes exactly the data required by the requested
  presentation. If the report must display or operate over every row, every row
  is embedded. Otherwise it includes only the required aggregates, chart data,
  and displayed table rows. It must not attach an undisclosed full dataset for
  speculative offline exploration.
- Completed statistical outputs receive reusable same-thread/source analysis
  IDs in `StatisticalAnalysisStore`. A report created in the same reviewed run
  may also bind the authoritative current execution before that turn is saved.
- Chart references should retain both the source result ID and exact validated
  `ChartSpec`; the report renderer, not the model, converts them into document
  visuals.

## Trusted self-contained HTML renderer

HTML is the canonical output. The file must open without the application or a
network connection. Inline or embed all required CSS, audited renderer-owned
JavaScript, SVG, chart data, images, and fonts or font fallbacks. Do not emit
remote scripts, stylesheets, tracking, analytics, iframes, or asset URLs.

Use a restrictive Content Security Policy generated by the renderer. Model
content is data, never code. Any optional interaction—such as disclosure
panels, table sorting, series toggles, or accessible chart details—comes from a
small versioned renderer library and an audited option in `ReportSpec`. It must
work with a keyboard and without hover, and meaningful content must remain
available when scripting is disabled.

The renderer should also provide:

- semantic HTML and sequential heading hierarchy;
- responsive, mobile-first layout with no horizontal page scrolling;
- print CSS even though first-class PDF or PNG export is deferred;
- locale-aware number, date, and currency formatting;
- deterministic output for the same spec, renderer version, and artifacts;
- visible generation and provenance metadata appropriate to the report;
- safe failure output when a referenced artifact is missing or out of scope.

## Design-quality contract

Use the UI/UX Pro Max guidance as design intelligence, not as a template
restriction. The skill should choose a coherent design system for each report
and validate at least these rules:

- normal text contrast of at least 4.5:1 and non-text/data contrast of at least
  3:1 where applicable;
- information never conveyed by color alone;
- readable typography with at least 16px body text on small screens, roughly
  1.5–1.75 line height, and controlled long-form line length;
- semantic color and type tokens rather than scattered component values;
- a consistent 4/8px spacing rhythm and responsive content hierarchy;
- one coherent visual style, icon family, elevation scale, and chart language;
- vector icons rather than emoji used as structural interface symbols;
- appropriate chart selection: trends as lines, comparisons as bars,
  proportions limited to a small number of categories, and dense data split
  when necessary;
- visible legends, units, exact-value access, chart summaries, and accessible
  table alternatives;
- keyboard-reachable interactions, visible focus states, and 44px minimum
  interactive targets;
- motion limited to meaningful 150–300ms transitions, with
  `prefers-reduced-motion` respected and no content-dependent layout shift;
- independent light/dark contrast verification when both themes are supplied.

The coordinator can recommend design directions using descriptions—for
example, a narrative infographic with strong hierarchy and annotated evidence,
or a dense statistical report with restrained styling and prominent methods—
while remaining open to any user-defined direction.

## Streamlit integration

Render dynamic report HTML in an isolated frame. Do not inject model-influenced
report markup into the main Streamlit DOM with `st.html`: that API is not
iframed, and JavaScript requires an explicitly unsafe mode. For the first
implementation, use a tall `st.iframe` with the trusted rendered HTML inside an
expanded-by-default, collapsible preview, plus `st.download_button` for the
exact same HTML bytes. Keep the download control available when the preview is
collapsed.

Keep review lightweight:

- show the current report version and preview;
- make every successfully rendered preview downloadable;
- accept ordinary chat feedback such as “make this more concise,” “use an
  editorial infographic,” or “run another comparison first”;
- preserve prior versions in the process-local store while the session lives;
- avoid mandatory approve or finalize controls.

If future interactions need a two-way bridge between the report and Streamlit,
use a trusted Streamlit Custom Component v2. A component is still trusted
application code and is not a sandbox for model-authored JavaScript.

## Implementation map

- `data_analytics_agent/reporting/schemas.py` defines `ReportBrief`, versioned
  `ReportSpec`, strict typed blocks, themes, references, and stored artifacts.
- `data_analytics_agent/reporting/tools.py` exposes scoped result/analysis
  discovery and the coordinator-owned `create_report` terminal tool. The
  provider-facing tool accepts one `report_json` string, avoiding unsupported
  nested union schemas; trusted application code then parses and validates the
  full `ReportSpec` while LangGraph injects `ToolRuntime` privately. Expected
  validation, artifact-reference, and rendering problems return compact
  `ok=false` repair guidance instead of failing the tool call; the coordinator
  may make one corrected attempt.
- `data_analytics_agent/reporting/renderer.py` escapes model text, resolves
  validated blocks, embeds Plotly and statistical figures, emits print and
  responsive CSS, hashes renderer-owned scripts into a restrictive CSP, and
  returns one standalone HTML string.
- `StatisticalAnalysisStore` and `ReportStore` retain reusable analyses and
  exact report bytes with source/thread provenance, version lineage, renderer
  version, and SHA-256 content hash.
- FastAPI exposes report metadata/content and byte-identical download routes;
  Streamlit verifies the hash, previews in a tall collapsible `st.iframe`, and
  downloads those exact bytes. Statistical notes are deduplicated and grouped
  in collapsed disclosure panels in both the chat result and report HTML.
- `ENABLE_REPORTING=false` removes the reporting tools and skill namespace
  without changing SQL, visualization, or statistical behavior.

The automated suite covers schema and contrast rejection, text escaping,
self-contained output, full-row inclusion when requested, scoped artifact
rejection, revision lineage, statistical figure embedding, authoritative tool
result attachment, API byte identity, and Streamlit preview/download.

Useful follow-up hardening includes browser-based accessibility and responsive
visual regression, durable authorized artifact storage, offline geographic
topology embedding for map blocks, and routing evaluations over real-model
report requests.

## Explicit non-goals for the first release

- a fourth reporting sub-agent;
- arbitrary model-authored HTML, CSS escape hatches, or JavaScript;
- mandatory approval or finalization workflow;
- first-class PDF, PNG, or slide export;
- remote assets, analytics, or network-dependent reports;
- durable, multi-user report storage before the rest of the POC stores are
  hardened.
