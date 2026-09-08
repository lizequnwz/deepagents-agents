"""Descriptive SQL specialist with source and saved-data execution."""

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.structured_output import ToolStrategy
from data_analytics_agent.agents.text_to_sql.tools import (
    create_execute_sql_tool,
    create_query_saved_results_tool,
    create_inspect_conversation_result_tool,
)
from data_analytics_agent.semantic_tools import (
    create_semantic_context_tool,
    create_browse_semantic_tool,
    create_lookup_values_tool,
)
from data_analytics_agent.semantic_context import render_sql_context
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
        create_semantic_context_tool(
            semantic_catalog,
            source_id=source.source_id,
            dialect=source.dialect,
            include_physical=True,
        ),
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
        "middleware": [*review, *(middleware or [])],
        "system_prompt": f"""You are the text-to-SQL specialist for {source.name}, dialect {source.dialect}.
{render_sql_context(semantic_catalog, source_id=source.source_id, dialect=source.dialect)}
Own semantic grounding, retrieval, descriptive calculations, category lookup,
and saved-data shaping. Use supplied exact definitions when sufficient; otherwise
use get_semantic_context for relevant definitions and declared relationships. Browse when vocabulary
is unknown; lookup_values discovers actual category spellings. Never guess a
physical source, field, metric meaning, or join, or probe undeclared objects.
Use the source dialect for execute_sql and DuckDB for query_saved_results with
explicit alias-to-artifact bindings. Saved IDs are evidence handles, not tables.
Reuse suitable snapshots; fresh/current requests require source execution.
Execute one read-only SELECT/CTE/set query per call: no SELECT *, DML, DDL,
metadata/session commands or multiple statements. Add LIMIT only for an explicit
requested row count; top/highest alone needs deterministic ordering, not a hidden
limit. Preserve business grain and avoid join fan-out. Put filters, grouping and
business transformations in SQL. Return the smallest complete population at the
requested grain, including all observations needed by Python. Never infer totals
or statistics from truncated results; preserve filters, missingness and lineage.
Simple totals, rankings and descriptive monthly series normally need no todos or
investigation record. Repair or refine when necessary; do not impose a query-count
ceiling. Give executions distinct purposes. Repair expected failures using tool feedback,
preserving successful evidence. Reviewed edits are authoritative: describe the
exact SQL that executed. On budget exhaustion return saved evidence and explain
unfinished work. Return result IDs, business interpretation and material
assumptions with the existing compact SQLAnalysisResponse. Do not create charts,
reports, or perform predictive/inferential analysis; data-analysis owns that work.
""",
        "response_format": ToolStrategy(SQLAnalysisResponse),
    }
