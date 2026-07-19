"""Source-bound Data Analytics Agent construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain.agents.structured_output import ProviderStrategy
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from data_analytics_agent.agents.text_to_sql.agent import (
    build_text_to_sql_subagent,
)
from data_analytics_agent.agents.text_to_sql.tools import (
    AgentContext,
    create_get_saved_result_tool,
)
from data_analytics_agent.backends import SQLBackend
from data_analytics_agent.config import Settings
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.schemas import FinalAnswer
from data_analytics_agent.stores import ResultStore


def _coordinator_prompt(
    source: DataSource,
    *,
    visualization_enabled: bool,
) -> str:
    visualization = (
        """\

Use the `data-visualization` subagent only when the user explicitly asks to
visualize, chart, plot, graph, or map data. It consumes one saved result and
returns exactly one validated ChartSpec. If the current result is not
chart-ready, first delegate to `text-to-sql` for a new reviewed result, then
delegate that result ID to `data-visualization`. Tell the SQL specialist the
requested chart type and the observation, series, or grid shape it must
preserve. Generic list limits must not discard the rows needed for a complete
series, distribution, relationship, or heatmap grid. For chart-only follow-ups,
reuse the referenced saved result when it already has the required shape.
Never invent, rewrite, or silently alter the generated chart specification.
"""
        if visualization_enabled
        else """\

Data visualization is disabled for this deployment. If the user explicitly
requests a chart, say that visualization is unavailable; do not simulate one.
"""
    )
    return f"""\
You coordinate a conversational data analyst for the selected data source
{source.name!r} (source ID {source.source_id!r}). Delegate every request that
needs database facts or SQL to the `text-to-sql` subagent using the task tool.
You may use get_saved_result for follow-ups about an existing result. Do not
invent database facts, switch data sources, or execute SQL yourself.
{visualization}

Return a FinalAnswer with a direct answer, the exact executed SQL and result ID
when present, the exact generated chart when present, material assumptions, and
a concise interpretation. Do not expose private chain of thought, tool
payloads, or more than
{source.limits.model_sample_rows} database rows.

Human review inside the SQL subagent may change the requested limit, filters,
grouping, or other scope. In that case, the reviewed execution and the
subagent's structured result are authoritative. Describe what actually ran and
what it returned; do not repeat stale scope from the original user message.
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


def _final_answer_response_format() -> ProviderStrategy[FinalAnswer]:
    """Use native JSON Schema without OpenAI's all-fields-required mode.

    FinalAnswer embeds a sparse ChartSpec whose chart-specific fields are
    nullable or defaulted. OpenAI strict schemas require every object property
    to be listed as required, which is incompatible with that declarative
    contract. LangChain still parses the provider JSON, and RunManager applies
    Pydantic and result-provenance validation before completing the turn.
    """

    return ProviderStrategy(FinalAnswer, strict=False)


def build_agent(
    settings: Settings,
    result_store: ResultStore,
    *,
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

    register_harness_profile(
        f"openai:{settings.model}",
        HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
        ),
    )
    chat_model = model or ChatOpenAI(model=settings.model)

    get_saved_result = create_get_saved_result_tool(
        result_store,
        source_id=source.source_id,
        model_sample_rows=source.limits.model_sample_rows,
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
            )
        )

    return create_deep_agent(
        name="data-analytics-agent",
        model=chat_model,
        tools=[get_saved_result],
        system_prompt=_coordinator_prompt(
            source,
            visualization_enabled=settings.enable_data_visualization,
        ),
        memory=["/project/AGENTS.md"],
        subagents=subagents,
        backend=_project_backend(settings.project_root),
        permissions=permissions,
        response_format=_final_answer_response_format(),
        context_schema=AgentContext,
        checkpointer=checkpointer or InMemorySaver(),
    )
