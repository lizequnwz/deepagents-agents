"""Statistical-analysis specialist definition."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.structured_output import ToolStrategy

from data_analytics_agent.agents.statistical_analysis.runner import (
    PythonExecutionLimits,
)
from data_analytics_agent.agents.statistical_analysis.schemas import (
    StatisticalAnalysisResponse,
)
from data_analytics_agent.agents.statistical_analysis.tools import (
    create_execute_statistical_python_tool,
    create_inspect_result_for_statistics_tool,
)
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.stores import ResultStore, RunStore

def _statistical_output_retry_message(require_approval: bool) -> str:
    review_recovery = (
        "After rejection, revise the code from the feedback and request "
        "review again. "
        if require_approval
        else ""
    )
    return (
        "Use `analysis_completed` only after `execute_statistical_python` "
        "returns `ok: true`. Return the parent result ID and analytical "
        "narrative only; the application attaches its authoritative executed "
        f"code and outputs. {review_recovery}"
        "After a repairable execution failure, make one targeted repair while "
        "an attempt remains. Never claim success for truncated data."
    )


def _statistical_subagent_prompt(
    source: DataSource,
    *,
    maximum_attempts: int,
    require_approval: bool,
) -> str:
    execution_mode = (
        "Execution pauses for human approve/edit/reject. The exact reviewed "
        "text executes; human edits are authoritative. A rejected proposal "
        "must be revised from the feedback and reviewed again."
        if require_approval
        else "Validated Python executes immediately without a human "
        "interrupt. The exact submitted text executes."
    )
    retry_mode = "reviewed" if require_approval else "executed"
    return f"""\
You are the isolated statistical-analysis specialist for {source.name!r},
permanently bound to source ID {source.source_id!r}. Analyze exactly one saved
SQL result assigned by the coordinator and return one terminal
`StatisticalAnalysisResponse`.

Your first action must read the `statistical-analysis` skill with `limit=1000`;
then call `inspect_result_for_statistics` exactly once for the assigned result
ID. Do not use `write_todos` for this bounded workflow. Its profile covers all
stored rows and its sample contains at most 10 rows. If inspection returns
`result_not_found` or `execution_attempts_exhausted`, return `cannot_analyze`
immediately without proposing Python.
Do not query the database, switch sources, invent columns, or request the
complete dataset in a message. If a figure is requested or methodologically
useful, also read `references/statistical-graphics.md` from the skill folder
before writing code.

Choose the simplest defensible method for the question and data. Apply only the
diagnostics, uncertainty estimates, multiplicity handling, or sensitivity
checks that materially affect that method or the claims being made. Default to
95% confidence intervals, two-sided alpha 0.05, causal restraint, and random
seed 0 when those choices are relevant and the user did not specify otherwise.

Read `references/regression.md` before regression or predictive modeling. Read
`references/time-series.md` before trend inference, seasonality, anomaly
detection, or forecasting. Read only the relevant method reference.

Dataset and execution contract:
- The isolated runtime loads the complete scoped saved result as pandas `df`.
- `pd` and `np` are preloaded; pandas, NumPy, SciPy, statsmodels,
  scikit-learn, matplotlib, and seaborn are available for import.
- Write general Python appropriate to the question. You may reshape data,
  handle missing values, derive fields, test assumptions, fit models, and make
  compact tables or figures.
- Aim for one complete execution that produces the result and its necessary
  diagnostics. Do not use Python executions as staged data exploration.
- Set `analysis_outputs` to a dictionary mapping human-readable names to
  compact strings, scalars, pandas DataFrames/Series, JSON record lists, or
  matplotlib Figures/Axes.
- Call `execute_statistical_python` with only the assigned result ID and the
  complete proposed code. {execution_mode}
- A repairable failure may receive one targeted repair and be {retry_mode}
  again, up to {maximum_attempts} actual executions total. Never repeat
  unchanged failing code or start a different analysis after attempts are
  exhausted.

Completeness and terminal outcomes:
- If `truncated` is true, do not propose or execute Python. Return
  `needs_sql_reshape` and specify the required population, grain, and columns.
- Return `needs_sql_reshape` when the untruncated result still lacks the grain,
  observations, columns, or structure needed for a defensible analysis.
- For a categorical predictor and numeric outcome, require repeated
  observations within categories. One aggregate row per category cannot
  estimate within-category variability and must not be replaced by a
  correlation between two derived numeric totals.
- Return `needs_clarification` when a user choice would materially change the
  dataset or method.
- Return `cannot_analyze` when the data cannot support the inference or all
  execution attempts fail.
- Return `analysis_completed` only after executed code succeeds. Do not copy
  the code, binary figures, or outputs into the terminal model response. The
  application will attach the exact executed code and authoritative bounded
  outputs it already captured.

The coordinator owns the final user-facing response. Provide authoritative,
concise evidence: direct answer, method, assumptions, interpretation, warnings,
and compact outputs. Do not return `df`, unbounded stdout, private reasoning, or
unsupported causal claims.
"""


def build_statistical_analysis_subagent(
    *,
    source: DataSource,
    result_store: ResultStore,
    run_store: RunStore,
    execution_limits: PythonExecutionLimits,
    model: Any,
    permissions: list[Any],
    require_approval: bool,
    middleware: list[Any] | None = None,
) -> dict[str, Any]:
    """Build the source-bound statistical specialist."""

    inspect_result = create_inspect_result_for_statistics_tool(
        result_store,
        run_store,
        source_id=source.source_id,
        sample_rows=min(source.limits.model_sample_rows, 10),
        maximum_attempts=execution_limits.max_execution_attempts,
    )
    execute_python = create_execute_statistical_python_tool(
        result_store,
        run_store,
        source_id=source.source_id,
        limits=execution_limits,
    )
    agent_middleware: list[Any] = []
    if require_approval:
        agent_middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "execute_statistical_python": {
                        "allowed_decisions": ["approve", "edit", "reject"]
                    }
                }
            )
        )
    agent_middleware.extend(middleware or [])
    return {
        "name": "statistical-analysis",
        "description": (
            "Use when uncertainty or modeling materially helps: statistical "
            "tests, experiments, regression, predictive modeling, trend "
            "inference, seasonality, forecasting, distributions, and "
            "diagnostics over one source/thread-scoped saved SQL result. It "
            "writes general Python and "
            + (
                "requires human review before execution."
                if require_approval
                else "executes it automatically after validation."
            )
        ),
        "system_prompt": _statistical_subagent_prompt(
            source,
            maximum_attempts=execution_limits.max_execution_attempts,
            require_approval=require_approval,
        ),
        "tools": [inspect_result, execute_python],
        "model": model,
        "skills": ["/project/skills/statistics/"],
        "permissions": permissions,
        # after_model hooks run in reverse order. When present, keep HITL first
        # so budget checks happen before an approval is exposed.
        "middleware": agent_middleware,
        "response_format": ToolStrategy(
            StatisticalAnalysisResponse,
            handle_errors=_statistical_output_retry_message(
                require_approval
            ),
            tool_message_content=(
                "Statistical analysis reached a terminal outcome."
            ),
        ),
    }
