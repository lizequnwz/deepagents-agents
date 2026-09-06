"""Source-bound coordinator with SQL and iterative Python specialists."""

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
from data_analytics_agent.config import Settings
from data_analytics_agent.schemas import CoordinatorResponse
from data_analytics_agent.agents.text_to_sql.agent import build_text_to_sql_subagent
from data_analytics_agent.agents.data_analysis.agent import build_data_analysis_subagent
from data_analytics_agent.agents.text_to_sql.tools import (
    AnalyticsAgentState,
    create_list_conversation_results_tool,
    create_inspect_conversation_result_tool,
)
from data_analytics_agent.semantic import render_semantic_overview
from data_analytics_agent.semantic_tools import (
    create_semantic_tools,
    create_browse_semantic_tool,
)
from data_analytics_agent.reporting.tools import (
    create_create_report_tool,
    create_list_conversation_analyses_tool,
    create_inspect_conversation_analysis_tool,
)
from data_analytics_agent.presentation import create_presentation_tools
from data_analytics_agent.visualization.tools import create_chart_tool
from data_analytics_agent.stores import (
    RunStore,
    DataAnalysisStore,
    ReportStore,
    ConversationStore,
)
from data_analytics_agent.execution_budget import execution_budget_middleware


def _project_backend(project_root: Path) -> CompositeBackend:
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/project/": FilesystemBackend(root_dir=project_root, virtual_mode=True)
        },
    )


def _final_answer_response_format() -> ProviderStrategy[CoordinatorResponse]:
    """Return the small cross-provider coordinator response contract."""

    return ProviderStrategy(CoordinatorResponse, strict=False)


def _build_chat_model(settings: Settings, model: Any | None = None) -> Any:
    """Construct the configured provider model unless one was injected."""

    if model is not None:
        return model
    options = {"streaming": False}
    if settings.model_provider == "openai":
        options.update(reasoning_effort="medium", use_responses_api=True)
    return init_chat_model(
        settings.model, model_provider=settings.model_provider, **options
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

    identifier = getattr(model, "model_name", None) or getattr(model, "model", None)
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
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
        ),
    )


def build_agent(
    settings,
    result_store,
    run_store=None,
    *,
    analysis_store=None,
    report_store=None,
    conversation_store=None,
    source,
    semantic_catalog,
    backend,
    model=None,
    checkpointer=None,
):
    chat_model = _build_chat_model(settings, model)
    _configure_harness_profile(chat_model, settings)
    runs = run_store or RunStore(result_store.storage)
    analyses = analysis_store or DataAnalysisStore(result_store.storage)
    reports = report_store or ReportStore(result_store.storage)
    conversations = conversation_store or ConversationStore(result_store.storage)
    permissions = [
        FilesystemPermission(
            operations=["read"],
            paths=["/project/AGENTS.md", "/project/skills/**"],
            mode="allow",
        ),
        FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
    ]
    tools = [
        *create_semantic_tools(semantic_catalog, include_physical=False),
        create_browse_semantic_tool(semantic_catalog),
        create_list_conversation_results_tool(result_store, source_id=source.source_id),
        create_inspect_conversation_result_tool(
            result_store, source_id=source.source_id
        ),
        create_list_conversation_analyses_tool(analyses, source_id=source.source_id),
        create_inspect_conversation_analysis_tool(analyses, source_id=source.source_id),
        *create_presentation_tools(
            result_store, analyses, runs, conversations, source_id=source.source_id
        ),
        create_create_report_tool(
            result_store, analyses, runs, reports, source_id=source.source_id
        ),
    ]
    if settings.enable_data_visualization:
        tools.append(create_chart_tool(result_store, runs, source_id=source.source_id))
    subagents = [
        build_text_to_sql_subagent(
            source=source,
            semantic_catalog=semantic_catalog,
            backend=backend,
            result_store=result_store,
            run_store=runs,
            model=chat_model,
            permissions=permissions,
            require_approval=settings.require_sql_approval,
            middleware=execution_budget_middleware(
                model_calls=settings.sql_agent_model_call_limit,
                tool_calls=settings.sql_agent_tool_call_limit,
            ),
        )
    ]
    if settings.enable_data_analysis:
        subagents.append(
            build_data_analysis_subagent(
                source=source,
                result_store=result_store,
                run_store=runs,
                analysis_store=analyses,
                execution_limits=settings.python_execution_limits(),
                model=chat_model,
                permissions=permissions,
                require_approval=settings.require_python_approval,
                middleware=execution_budget_middleware(
                    model_calls=settings.analysis_agent_model_call_limit,
                    tool_calls=settings.analysis_agent_tool_call_limit,
                ),
            )
        )
    prompt = f"""You coordinate a source-bound analyst for {source.name} ({source.source_id}).
{source.description}
{render_semantic_overview(semantic_catalog)}
Examples: {[example.question for example in source.examples]}
Follow AGENTS.md. Handle greetings, help, and metadata research directly. Never
claim observed database values without saved evidence. Metadata-only questions
need neither execution nor an empty report.
Delegate retrieval/descriptive questions and dataset shaping to text-to-sql.
Delegate exploration, inference, prediction, trend/seasonality investigation,
forecasting and model evaluation to data-analysis. Choose by required work,
not keywords alone. SQL requests must be sequential and complete. Multiple
SQL and Python assignments are allowed; revise the plan after observing results.
Keep a compact investigation record with save_investigation for complex work.
Use saved-result and analysis discovery to resolve follow-ups. Reuse suitable
snapshots; fresh/current requests need new source SQL. Saved IDs are opaque
artifacts, never warehouse tables. Python can consume multiple same-source
saved inputs and save derived datasets. Supply IDs rather than copying rows.
Load chart-design when useful. create_chart is a shared tool, not an agent;
create as many purposeful charts as needed, including forecasts over derived
datasets. Preserve explicit chart types. Ask SQL for saved-data reshaping if
needed. Scalar or non-chartable evidence needs no artificial chart.
After selecting final evidence, call publish_findings with the answer and all
material result, analysis and chart IDs. Then load report-design and create the
required HTML report using those same artifacts. Use saved chart_id references,
not copied chart specifications. Reports may include several analyses.
For uncertainty, preserve the method, sample/population, assumptions, validation
and limitations. Explain association as association, not causation. If analysis
is incomplete, publish partial=true with unresolved_questions and report the
supported findings. When tools report budget exhaustion, stop analysis and
proceed to publication and reporting. A report failure must not trigger data
re-execution: correct the reported problem and retry the report.
Finish with the same CoordinatorResponse used to publish the findings. The
application owns exact SQL, Python, outputs, charts and report references.
"""
    return create_deep_agent(
        name="data-analytics-agent",
        model=chat_model,
        tools=tools,
        system_prompt=prompt,
        memory=["/project/AGENTS.md"],
        skills=["/project/skills/reporting/", "/project/skills/data-visualization/"],
        subagents=subagents,
        backend=_project_backend(settings.project_root),
        permissions=permissions,
        middleware=execution_budget_middleware(
            model_calls=settings.coordinator_model_call_limit,
            tool_calls=settings.coordinator_tool_call_limit,
        ),
        response_format=_final_answer_response_format(),
        state_schema=AnalyticsAgentState,
        checkpointer=checkpointer or InMemorySaver(),
    )
