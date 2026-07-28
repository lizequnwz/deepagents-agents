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
Use `data-visualization` only when the user explicitly asks for a chart, plot,
graph, visualization, or map.
"""
        if visualization_enabled
        else """\

Data visualization is disabled for this deployment. If the user explicitly
requests a chart, say that visualization is unavailable; do not simulate one.
"""
    )
    statistics = (
        """\

Statistical analysis is available. Route requests involving statistical tests,
experiments, correlations, distributions, significance, regression,
uncertainty, or similar inference to `statistical-analysis`.

Assign exactly one source- and conversation-scoped saved SQL result by result
ID. Conservatively reuse an untruncated result only when its provenance,
population, grain, and columns clearly match the requested inference. Otherwise
obtain a new analysis-ready result through `text-to-sql` and human SQL review
first. Never copy a complete dataset into a task description.

Preserve the variation needed for the requested relationship. In particular,
do not reinterpret a categorical predictor versus numeric outcome as a
correlation between two category-level aggregates. Ask `text-to-sql` for a
defensible observational grain with repeated observations within categories;
for a request such as sales versus genre, retain track- or transaction-level
sales observations and include zero-sales entities when the estimand requires
them.

Accept one terminal statistical outcome: `analysis_completed`,
`needs_sql_reshape`, `needs_clarification`, or `cannot_analyze`. On
`needs_sql_reshape`, allow exactly one recovery cycle: obtain one new reviewed
SQL result matching the requested shape, then call statistical analysis once
more. If that attempt is still unsuitable or truncated, stop. Statistical
diagnostic figures may be produced by reviewed Python even without an explicit
chart request when they materially support the analysis.
"""
        if statistical_analysis_enabled
        else """\

Statistical analysis is disabled for this deployment. If the user requests
statistical tests, experiments, correlations, distributions, significance,
regression, uncertainty, or similar inference, say it is unavailable; do not
simulate execution or delegate that request.
"""
    )
    reporting = (
        """\

Reporting is available for explicit requests for a report, infographic,
briefing, findings document, data story, or downloadable HTML. Keep reporting
in the coordinator; do not delegate it to another subagent. Load the
report-design skill, reuse suitable same-conversation artifacts, and obtain new
reviewed SQL or statistical evidence when necessary. Then serialize one
declarative `ReportSpec` as JSON and pass that string to `create_report` as
`report_json`. Trusted application code owns HTML, CSS, JavaScript, artifact
resolution, rendering, and storage. Never write or request arbitrary markup or
scripts.

`create_report` returns `ok=false` with compact field paths for expected
specification, artifact-reference, or rendering errors. Correct those exact
issues and retry once with a complete specification; never repeat the same
payload. If the retry fails, explain the remaining limitation instead of
looping. Omit optional fields and theme overrides that do not materially help
the requested report.

A report may combine multiple result and statistical-analysis artifacts from
this conversation and source. Use `list_conversation_analyses` and
`inspect_conversation_analysis` when a prior statistical artifact is ambiguous.
For a revision, preserve the previous report ID in `ReportSpec`. Every safe
version is immediately downloadable; do not require approval or finalization.
"""
        if reporting_enabled
        else """\

Reporting is disabled for this deployment. If the user requests a report or
infographic, say that downloadable HTML reporting is unavailable.
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
do not call `task`, and leave `sql`, `result_id`, and `chart` empty.

Delegate to `text-to-sql` only when the user asks to retrieve, calculate,
compare, rank, aggregate, filter, or otherwise verify actual database values,
or requests a new result shape. A request about what could be analyzed is not
itself a request to perform that analysis.

Run text-to-SQL delegations sequentially. Never issue more than one `task` call
to `text-to-sql` in the same model response. Wait for the current specialist's
human-reviewed result before starting another text-to-SQL task, including when
gathering several artifacts for a report.

The SQL specialist and saved-result inspection expose a deterministic profile
over all stored rows plus at most the first 10 rows. Use that bounded evidence;
do not request or expose additional rows. Treat reviewed execution and
terminal specialist results as authoritative, including human-edited scope.

Return `CoordinatorResponse` with the direct business answer and, when present,
the reviewed result ID and SQL. The application attaches the exact validated
`ChartSpec`, terminal statistical result, reviewed Python and outputs, and
report reference after parsing. Do not reconstruct any of those artifacts.
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
        middleware=execution_budget_middleware(
            model_calls=settings.coordinator_model_call_limit,
            tool_calls=settings.coordinator_tool_call_limit,
            specific_tool_calls={
                "task": settings.coordinator_task_call_limit,
            },
        ),
        response_format=_final_answer_response_format(),
        state_schema=AnalyticsAgentState,
        checkpointer=checkpointer or InMemorySaver(),
    )
