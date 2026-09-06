"""Descriptive SQL specialist with source and saved-data execution."""

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.structured_output import ToolStrategy
from data_analytics_agent.agents.text_to_sql.tools import (
    create_execute_sql_tool,
    create_query_saved_results_tool,
    create_inspect_conversation_result_tool,
)
from data_analytics_agent.semantic_tools import (
    create_semantic_tools,
    create_browse_semantic_tool,
    create_lookup_values_tool,
)
from data_analytics_agent.semantic import render_semantic_overview
from data_analytics_agent.schemas import SQLAnalysisResponse


def build_text_to_sql_subagent(
    *,
    source,
    semantic_catalog,
    backend,
    result_store,
    run_store,
    model,
    permissions,
    require_approval,
    middleware=None,
):
    tools = [
        *create_semantic_tools(semantic_catalog, include_physical=True),
        create_browse_semantic_tool(semantic_catalog, include_physical=True),
        create_lookup_values_tool(
            semantic_catalog,
            source,
            backend,
            result_store,
            run_store,
            require_approval=require_approval,
        ),
        create_execute_sql_tool(source, backend, result_store, run_store),
        create_query_saved_results_tool(
            result_store, run_store, source_id=source.source_id
        ),
        create_inspect_conversation_result_tool(
            result_store, source_id=source.source_id
        ),
    ]
    review = (
        [
            HumanInTheLoopMiddleware(
                interrupt_on={
                    name: {"allowed_decisions": ["approve", "edit", "reject"]}
                    for name in ["execute_sql", "query_saved_results"]
                }
            )
        ]
        if require_approval
        else []
    )
    return {
        "name": "text-to-sql",
        "description": "Retrieve source data, answer descriptive questions, discover category values, and reshape saved datasets. Use for show, compare, aggregate, rank, and preparing data for Python.",
        "model": model,
        "tools": tools,
        "permissions": permissions,
        "skills": ["/project/skills/text-to-sql/"],
        "middleware": [*review, *(middleware or [])],
        "system_prompt": f"""You are the text-to-SQL specialist for {source.name}, dialect {source.dialect}.
{render_semantic_overview(semantic_catalog)}
Read the query-writing skill. Fetch exact semantic definitions and declared
relationships needed for source SQL. Use browse when search is insufficient;
lookup_values resolves actual category spellings for data-bearing assignments.
For saved data use query_saved_results with explicit alias-to-artifact bindings.
It uses DuckDB SQL, not the source dialect. IDs are evidence handles, not source
relations. Reuse snapshots when appropriate; query source for fresh data.
Prepare the smallest complete result that answers your assignment. Give each
execution a distinct purpose. Return the executed result ID and exact SQL,
business interpretation and material assumptions. Never infer totals from a
truncated prefix. When a tool reports budget exhaustion, return the evidence
already obtained and explain what remains incomplete; do not keep executing.
Do not run predictive or inferential analysis; the data-analysis specialist
owns that work. Do not create charts or reports. Human edits, when enabled,
define what actually executes. Finish with SQLAnalysisResponse.
""",
        "response_format": ToolStrategy(SQLAnalysisResponse),
    }
