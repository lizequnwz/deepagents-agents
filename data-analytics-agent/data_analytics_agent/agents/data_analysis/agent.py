"""Generic iterative analysis specialist, distinct from descriptive SQL."""

from langchain.agents.middleware import HumanInTheLoopMiddleware
from data_analytics_agent.agents.data_analysis.tools import create_analysis_tools
from data_analytics_agent.agents.text_to_sql.tools import (
    create_inspect_conversation_result_tool,
    create_list_conversation_results_tool,
)


def build_data_analysis_subagent(
    *,
    source,
    result_store,
    run_store,
    analysis_store,
    execution_limits,
    model,
    permissions,
    require_approval,
    middleware=None,
):
    tools = create_analysis_tools(
        result_store,
        run_store,
        analysis_store,
        source_id=source.source_id,
        limits=execution_limits,
    )
    tools += [
        create_inspect_conversation_result_tool(
            result_store, source_id=source.source_id, model_sample_rows=10
        ),
        create_list_conversation_results_tool(result_store, source_id=source.source_id),
    ]
    review = (
        [
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "execute_analysis_python": {
                        "allowed_decisions": ["approve", "edit", "reject"]
                    }
                }
            )
        ]
        if require_approval
        else []
    )
    return {
        "name": "data-analysis",
        "description": "Explore datasets, investigate trends and seasonality, test hypotheses, evaluate predictive models and forecasts with iterative Python. Source data retrieval remains with text-to-SQL.",
        "model": model,
        "tools": tools,
        "skills": ["/project/skills/analysis/"],
        "permissions": permissions,
        "middleware": [*review, *(middleware or [])],
        "system_prompt": f"""You are the data-analysis specialist for {source.name}.
Load the data-analysis skill. Inspect the assigned datasets, execute Python,
examine the results, and revise as needed. Each call starts a fresh process
with named DataFrames in datasets. For inputs={{'sales': '<saved ID>'}}, access
the frame as datasets['sales']; no bare variable sales/source/data is created. Save intermediate data in output_datasets;
reuse those artifact IDs in later inputs. Return compact analysis_outputs.
Use the simplest defensible methods. Distinguish associations from causes.
Keep scope aligned with the business question. Do not replace the requested
outcome with a convenient proxy. Do not analyze incomplete prefixes.
You may execute several successful steps. Use failures to repair the code;
do not repeat unchanged failing code. Stop when evidence is sufficient or
execution reports that the analysis budget is exhausted.
If source data is missing, finish with needs_sql_reshape and a complete business
request specifying population, grain, dates, fields and intended analysis.
Do not query source databases yourself. The coordinator will retrieve data and
may assign you again with the saved findings and execution IDs.
Finish using finish_analysis, preserving all material execution IDs. The
coordinator owns the user-facing answer, shared charts, and HTML report.
If finish_analysis returns ok=false, correct its exact references and retry.
After it saves successfully, return its analysis ID and a concise summary; stop calling tools.
""",
    }
