"""Source-bound Data Analytics Agent construction."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
)
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.profiles import register_harness_profile
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.structured_output import ProviderStrategy
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver

from data_analytics_agent.agents.statistical_analysis.agent import (
    build_statistical_analysis_subagent,
)
from data_analytics_agent.agents.text_to_sql.agent import (
    build_text_to_sql_subagent,
)
from data_analytics_agent.agents.text_to_sql.tools import (
    AnalyticsAgentState,
    create_inspect_conversation_result_tool,
    create_list_conversation_results_tool,
)
from data_analytics_agent.backends import SQLBackend
from data_analytics_agent.config import Settings
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.execution_budget import (
    execution_budget_middleware,
)
from data_analytics_agent.reporting.tools import (
    create_create_report_tool,
    create_inspect_conversation_analysis_tool,
    create_list_conversation_analyses_tool,
)
from data_analytics_agent.schemas import CoordinatorResponse
from data_analytics_agent.stores import (
    ReportStore,
    ResultStore,
    RunStore,
    StatisticalAnalysisStore,
)


def _coordinator_prompt(
    source: DataSource,
    *,
    visualization_enabled: bool,
    statistical_analysis_enabled: bool = True,
    reporting_enabled: bool = True,
) -> str:
    curated_examples = (
        "\n".join(
            f"- {example.label}: {example.question}"
            for example in source.examples
        )
        or "- No curated example questions are configured."
    )
    visualization = (
        """\

Visualization is available.
For every ordinary successful database-answer turn, automatically attempt one
useful chart after the final evidence is selected. Do not chart intermediate
investigation results. Choose the primary or most explanatory chart-ready
result and delegate once to `data-visualization`, passing the original question,
selected result ID, its role in the answer, required result shape, the explicit
row count or `no row count requested`, and any explicit chart type. Explicit
chart types are authoritative; otherwise let the specialist choose a supported
type. A `cannot_create` outcome is acceptable for empty, scalar-only,
identifier-heavy, or otherwise non-chartable data. Do not fabricate a chart.

On `needs_sql_reshape`, allow one recovery cycle: obtain one new chart-ready SQL
result from the configured source tables, then delegate once more. The prior
result ID identifies evidence; it is not a table that SQL can query. Count the
new result as investigation evidence only when it materially supports the
answer. Explicit report turns use charts inside `ReportSpec`; do not add a
redundant top-level visualization. For an ordinary analysis, keep the successful
top-level chart and reuse its exact `ChartSpec` in the automatic report when it
helps the document.
"""
        if visualization_enabled
        else """\

Data visualization is disabled for this deployment. Complete database answers
without delegating to `data-visualization`. If the user explicitly requests a
chart, say that visualization is unavailable; do not simulate one.
"""
    )
    statistics = (
        """\

Statistical analysis is available. Invoke `statistical-analysis` when
uncertainty or modeling materially improves the answer: tests, experiments,
regression, predictive modeling, trend inference, seasonality, forecasting, or
similar analysis. A descriptive trend, ranking, comparison, or distribution
that SQL and the normal visualization can answer does not need statistical
Python.

Delegate to `statistical-analysis` at most once in a user turn. The only
exception is when that delegation returns `needs_sql_reshape`: obtain exactly
one new validated SQL result with the requested shape, then delegate once more
using that new result. Do not make a second delegation after
`analysis_completed`, `cannot_analyze`, or `needs_clarification`, and do not try
a different saved result as an execution-error recovery.

Assign exactly one source- and conversation-scoped saved SQL result by result
ID. Conservatively reuse an untruncated result only when its provenance,
population, grain, and columns clearly match the requested inference. Otherwise
obtain a new analysis-ready result through `text-to-sql` under the configured
approval policy. Never copy a complete dataset into a task description.

Preserve the variation needed for the requested relationship. In particular,
do not reinterpret a categorical predictor versus numeric outcome as a
correlation between two category-level aggregates. Ask `text-to-sql` for a
defensible observational grain with repeated observations within categories;
for a request such as sales versus genre, retain track- or transaction-level
sales observations and include zero-sales entities when the estimand requires
them.

Accept one terminal statistical outcome: `analysis_completed`,
`needs_sql_reshape`, `needs_clarification`, or `cannot_analyze`. On
`needs_sql_reshape`, allow exactly one recovery cycle: obtain one new validated
SQL result from the configured source tables matching the requested shape, then
call statistical analysis once more. The previous result ID identifies evidence,
not a queryable relation. If that attempt is still unsuitable or truncated,
stop. Statistical diagnostic figures may be produced by executed Python even
without an explicit chart request when they materially support the analysis.
"""
        if statistical_analysis_enabled
        else """\

Statistical analysis is disabled for this deployment. If the user requests
statistical tests, experiments, correlations, distributions, significance,
regression, trend inference, seasonality, forecasting, uncertainty, or similar
inference, say it is unavailable; do not simulate execution or delegate that
request.
"""
    )
    reporting = (
        """\

Reporting is available. After every successful data-bearing analysis, create
one downloadable HTML report as the final presentation step. Do not create a
report for greetings, help, brainstorming, clarification-only responses,
failed analysis, or any answer with no final evidence. Keep reporting in the
coordinator; do not delegate it to another subagent. Load the report-design
skill after final evidence, statistics, and any ordinary top-level
visualization are complete. Reuse the same material same-conversation evidence
selected for the answer. Then serialize one declarative `ReportSpec` as JSON
and pass that string to `create_report` as `report_json`. Trusted application
code owns HTML, CSS, JavaScript, artifact resolution, rendering, and storage.
Never write or request arbitrary markup or scripts.

For an ordinary analysis, use the report skill's compact automatic-report
default: answer-first narrative, the exact successful visualization spec when
useful, a purposeful table for each material final result, and the completed
statistical analysis when present. For an explicit report, infographic,
briefing, findings document, data story, downloadable HTML, or report revision,
honor the user's audience, structure, and visual direction; those turns use
report-owned charts and skip the ordinary top-level visualization.

`create_report` returns `ok=false` with compact field paths for expected
specification, artifact-reference, or rendering errors. Correct those exact
issues and retry once with a complete specification; never repeat the same
payload. If the retry fails, complete the underlying data answer and briefly
explain that the report could not be generated instead of looping. Omit
optional fields and theme overrides that do not materially help the report.

A report may combine multiple result and statistical-analysis artifacts from
this conversation and source. Use `list_conversation_analyses` and
`inspect_conversation_analysis` when a prior statistical artifact is ambiguous.
For a revision, preserve the previous report ID in `ReportSpec`. Every safe
version is immediately downloadable; do not require approval or finalization.
"""
        if reporting_enabled
        else """\

Reporting is disabled for this deployment. Complete data answers without
calling `create_report`. If the user requests a report or infographic, say
that downloadable HTML reporting is unavailable.
"""
    )
    return f"""\
You are the coordinator for a conversational data analyst permanently bound to
{source.name!r} (source ID {source.source_id!r}). Follow the coordinator policy
in AGENTS.md. Do not execute SQL, invent database facts, or switch sources.
{visualization}
{statistics}
{reporting}

Source context available without database execution:
- Description: {source.description}
- SQL dialect: {source.dialect}
- Semantic model: `{source.semantic_virtual_path}`

Curated example questions:
{curated_examples}

Handle greetings, help, capability or architecture questions, requests for
example questions, and analysis brainstorming yourself. These requests do not
ask for database values. Use the source context and curated examples above,
do not call `task`, and leave `primary_result_id` empty with no supporting
result IDs.

Delegate to `text-to-sql` only when the user asks to retrieve, calculate,
compare, rank, aggregate, filter, or otherwise verify actual database values,
or requests a new result shape. A request about what could be analyzed is not
itself a request to perform that analysis.

Choose the smallest complete path:
- Direct analysis: use one text-to-SQL assignment when one result completely
  answers the business question.
- Investigation: for root-cause, broad comparison, multi-part, report, or
  different-grain questions, use `write_todos`. Define the business objective,
  subquestions, required result shapes, and material assumptions. Gather
  evidence one step at a time and revise the plan after each result.

Run text-to-SQL delegations sequentially. Never issue more than one `task` call
to `text-to-sql` in the same model response. Each assignment must be complete
because specialists are stateless. Wait for the current validated result before
starting another text-to-SQL task. Inspect its deterministic profile and bounded
sample before selecting the next step. Later assignments may cite earlier result
IDs to identify evidence, plus labels, findings, and required shapes, but must
state that result IDs are opaque application artifacts, never source table or
view names. Every new SQL assignment must restate the required business query
over the configured source. Never copy complete datasets into task messages.

Reuse suitable untruncated results and avoid duplicate queries. Reconcile
totals, populations, filters, date windows, and grains before synthesis. Stop
when the evidence supports the answer, a configured execution budget ends the
run, or a material ambiguity requires clarification. Preserve every result ID
that materially supports a final claim and omit investigative dead ends.

The SQL specialist and saved-result inspection expose a deterministic profile
over all stored rows plus at most the first 10 rows. Use that bounded evidence;
do not request or expose additional rows. Treat executed code and
terminal specialist results as authoritative, including human-edited scope.

Return `CoordinatorResponse` with the direct business answer,
`primary_result_id`, and `supporting_result_ids`. For a data-bearing answer, the
primary ID must also appear in the supporting list. Put every material evidence
ID in that list and no others. When statistical analysis completes, use its
parent result ID as primary while retaining other material SQL evidence. The
application resolves exact SQL and metadata from storage and attaches the exact
validated `ChartSpec`, terminal statistical result, executed Python and outputs,
and report reference after parsing. Do not reconstruct those artifacts.
Include only material assumptions and a concise interpretation. Omit private
reasoning and raw tool payloads.
"""


def _project_backend(project_root: Path) -> CompositeBackend:
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/project/": FilesystemBackend(
                root_dir=project_root, virtual_mode=True
            )
        },
    )


def _final_answer_response_format() -> ProviderStrategy[CoordinatorResponse]:
    """Return the small cross-provider coordinator response contract."""

    return ProviderStrategy(CoordinatorResponse, strict=False)


def _build_chat_model(settings: Settings, model: Any | None = None) -> Any:
    """Construct the configured provider model unless one was injected."""

    if model is not None:
        return model
    return init_chat_model(
        settings.model,
        model_provider=settings.model_provider,
        streaming=False,
        reasoning_effort="medium",
        use_responses_api=True
    )


def _model_harness_profile_key(model: Any, settings: Settings) -> str:
    """Resolve the registry key DeepAgents will use for a model instance."""

    provider: str | None = None
    try:
        params = model._get_ls_params()
    except (AttributeError, TypeError, NotImplementedError):
        params = None
    if isinstance(params, Mapping):
        candidate = params.get("ls_provider")
        if isinstance(candidate, str) and candidate:
            provider = candidate

    identifier = getattr(model, "model_name", None) or getattr(
        model, "model", None
    )
    if provider and isinstance(identifier, str) and identifier:
        return f"{provider}:{identifier}"
    if provider:
        return provider
    return f"{settings.model_provider}:{settings.model}"


def _configure_harness_profile(model: Any, settings: Settings) -> None:
    """Disable only the default general-purpose subagent for this model."""

    register_harness_profile(
        _model_harness_profile_key(model, settings),
        HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(
                enabled=False
            )
        ),
    )


def build_agent(
    settings: Settings,
    result_store: ResultStore,
    run_store: RunStore | None = None,
    *,
    analysis_store: StatisticalAnalysisStore | None = None,
    report_store: ReportStore | None = None,
    source: DataSource,
    backend: SQLBackend,
    model: Any | None = None,
    checkpointer: InMemorySaver | None = None,
):
    """Build one cached coordinator graph bound to one registered source."""

    if not source.semantic_model_path.is_file():
        raise FileNotFoundError(
            f"OSI semantic model not found at {source.semantic_model_path}"
        )
    backend_errors = backend.readiness_errors()
    if backend_errors:
        raise RuntimeError(" ".join(backend_errors))

    chat_model = _build_chat_model(settings, model)
    _configure_harness_profile(chat_model, settings)

    list_results = create_list_conversation_results_tool(
        result_store,
        source_id=source.source_id,
    )
    inspect_result = create_inspect_conversation_result_tool(
        result_store,
        source_id=source.source_id,
        model_sample_rows=source.limits.model_sample_rows,
    )
    shared_run_store = run_store or RunStore()
    shared_analysis_store = analysis_store or StatisticalAnalysisStore()
    shared_report_store = report_store or ReportStore()
    coordinator_tools = [list_results, inspect_result]
    if settings.enable_reporting:
        coordinator_tools.extend(
            [
                create_list_conversation_analyses_tool(
                    shared_analysis_store,
                    source_id=source.source_id,
                ),
                create_inspect_conversation_analysis_tool(
                    shared_analysis_store,
                    source_id=source.source_id,
                ),
                create_create_report_tool(
                    result_store,
                    shared_analysis_store,
                    shared_run_store,
                    shared_report_store,
                    source_id=source.source_id,
                ),
            ]
        )

    permissions = [
        FilesystemPermission(
            operations=["read"],
            paths=[
                "/project/AGENTS.md",
                "/project/semantic/**",
                "/project/skills/**",
            ],
            mode="allow",
        ),
        FilesystemPermission(
            operations=["read", "write"],
            paths=["/project/**"],
            mode="deny",
        ),
        FilesystemPermission(
            operations=["read", "write"],
            paths=["/**"],
            mode="deny",
        ),
    ]

    subagents = [
        build_text_to_sql_subagent(
            source=source,
            backend=backend,
            result_store=result_store,
            model=chat_model,
            permissions=permissions,
            require_approval=settings.require_sql_approval,
            middleware=execution_budget_middleware(
                model_calls=settings.sql_agent_model_call_limit,
                tool_calls=settings.sql_agent_tool_call_limit,
                specific_tool_calls={
                    "execute_sql": settings.sql_execute_call_limit,
                },
            ),
        )
    ]
    if settings.enable_data_visualization:
        from data_analytics_agent.agents.visualization.agent import (
            build_visualization_subagent,
        )

        subagents.append(
            build_visualization_subagent(
                source=source,
                result_store=result_store,
                model=chat_model,
                permissions=permissions,
                middleware=execution_budget_middleware(
                    model_calls=(
                        settings.visualization_agent_model_call_limit
                    ),
                    tool_calls=(
                        settings.visualization_agent_tool_call_limit
                    ),
                ),
            )
        )

    if settings.enable_statistical_analysis:
        subagents.append(
            build_statistical_analysis_subagent(
                source=source,
                result_store=result_store,
                run_store=shared_run_store,
                execution_limits=settings.statistical_execution_limits(),
                model=chat_model,
                permissions=permissions,
                require_approval=settings.require_python_approval,
                middleware=execution_budget_middleware(
                    model_calls=(
                        settings.statistical_agent_model_call_limit
                    ),
                    tool_calls=(
                        settings.statistical_agent_tool_call_limit
                    ),
                ),
            )
        )

    return create_deep_agent(
        name="data-analytics-agent",
        model=chat_model,
        tools=coordinator_tools,
        system_prompt=_coordinator_prompt(
            source,
            visualization_enabled=settings.enable_data_visualization,
            statistical_analysis_enabled=(
                settings.enable_statistical_analysis
            ),
            reporting_enabled=settings.enable_reporting,
        ),
        skills=(
            ["/project/skills/reporting/"]
            if settings.enable_reporting
            else None
        ),
        memory=["/project/AGENTS.md"],
        subagents=subagents,
        backend=_project_backend(settings.project_root),
        permissions=permissions,
        middleware=[
            TodoListMiddleware(),
            *execution_budget_middleware(
                model_calls=settings.coordinator_model_call_limit,
                tool_calls=settings.coordinator_tool_call_limit,
                specific_tool_calls={
                    "task": settings.coordinator_task_call_limit,
                },
            ),
        ],
        response_format=_final_answer_response_format(),
        state_schema=AnalyticsAgentState,
        checkpointer=checkpointer or InMemorySaver(),
    )
