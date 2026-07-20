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
from data_analytics_agent.schemas import FinalAnswer
from data_analytics_agent.stores import ResultStore


def _coordinator_prompt(
    source: DataSource,
    *,
    visualization_enabled: bool,
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
    return f"""\
You are the coordinator for a conversational data analyst permanently bound to
{source.name!r} (source ID {source.source_id!r}). Follow the coordinator policy
in AGENTS.md. Do not execute SQL, invent database facts, or switch sources.
{visualization}

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

The SQL specialist and saved-result inspection expose a deterministic profile
over all stored rows plus at most the first 10 rows. Use that bounded evidence;
do not request or expose additional rows. Treat reviewed execution and
terminal specialist results as authoritative, including human-edited scope.

Return `FinalAnswer` with the direct business answer and, when present, the
exact executed SQL, result ID, and generated `ChartSpec`. Include only material
assumptions and a concise interpretation. Omit private reasoning and raw tool
payloads.
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

    list_results = create_list_conversation_results_tool(
        result_store,
        source_id=source.source_id,
    )
    inspect_result = create_inspect_conversation_result_tool(
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

    return create_deep_agent(
        name="data-analytics-agent",
        model=chat_model,
        tools=[list_results, inspect_result],
        system_prompt=_coordinator_prompt(
            source,
            visualization_enabled=settings.enable_data_visualization,
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
