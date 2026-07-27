"""Statistical-analysis specialist definition."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.structured_output import ToolStrategy

from data_analytics_agent.agents.statistical_analysis.runner import (
    PythonExecutionLimits,
)
from data_analytics_agent.agents.statistical_analysis.schemas import (
    StatisticalAnalysisResult,
)
from data_analytics_agent.agents.statistical_analysis.tools import (
    create_execute_statistical_python_tool,
    create_inspect_result_for_statistics_tool,
)
from data_analytics_agent.data_sources import DataSource
from data_analytics_agent.stores import ResultStore, RunStore

STATISTICAL_OUTPUT_RETRY_MESSAGE = """\
Use `analysis_completed` only after `execute_statistical_python` returns
`ok: true`. Return the parent result ID and analytical narrative, but leave
`executed_python` null and `outputs` empty; the application attaches its
authoritative execution record. After rejection, revise the code from the
feedback and request review again. After an execution failure, repair the code
and request a fresh review while attempts remain. Never claim success for
truncated data.
"""


def _statistical_subagent_prompt(
    source: DataSource,
    *,
    maximum_attempts: int,
) -> str:
    return f"""\
You are the isolated statistical-analysis specialist for {source.name!r},
permanently bound to source ID {source.source_id!r}. Analyze exactly one saved
SQL result assigned by the coordinator and return one terminal
`StatisticalAnalysisResult`.

Your first action must read the `statistical-analysis` skill with `limit=1000`;
then call `inspect_result_for_statistics` exactly once for the assigned result
ID. Do not use `write_todos` for this bounded workflow. Its profile covers all
stored rows and its sample contains at most 10 rows. If inspection returns
`result_not_found`, return `cannot_analyze` immediately without retrying the ID.
Do not query the database, switch sources, invent columns, or request the
complete dataset in a message. If a figure is requested or methodologically
useful, also read `references/statistical-graphics.md` from the skill folder
before writing code.

Unless the user specifies otherwise, explicitly state and apply 95% confidence
intervals, two-sided alpha 0.05, effect sizes with uncertainty, deliberate
missingness and outlier handling, multiplicity control when applicable,
assumption diagnostics and robust sensitivity checks, causal restraint, and
random seed 0 for stochastic methods.

Dataset and execution contract:
- The reviewed runtime loads the complete scoped saved result as pandas `df`.
- `pd` and `np` are preloaded; pandas, NumPy, SciPy, statsmodels,
  scikit-learn, matplotlib, and seaborn are available for import.
- Write general Python appropriate to the question. You may reshape data,
  handle missing values, derive fields, test assumptions, fit models, and make
  compact tables or figures.
- Set `analysis_outputs` to a dictionary mapping human-readable names to
  compact strings, scalars, pandas DataFrames/Series, JSON record lists, or
  matplotlib Figures/Axes.
- Call `execute_statistical_python` with only the assigned result ID and the
  complete proposed code. Execution pauses for human approve/edit/reject.
- The exact reviewed text executes. Human edits are authoritative.
- A rejected proposal must be revised from the feedback and reviewed again.
- A failed execution may be repaired and reviewed again, up to
  {maximum_attempts} actual executions total. Never repeat unchanged failing
  code.

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
- Return `analysis_completed` only after reviewed code succeeds. Do not copy
  the code, binary figures, or outputs into the terminal model response: leave
  `executed_python` null and `outputs` empty. The application will attach the
  exact reviewed code and authoritative bounded outputs it already captured.

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
    middleware: list[Any] | None = None,
) -> dict[str, Any]:
    """Build the source-bound, human-reviewed statistical specialist."""

    inspect_result = create_inspect_result_for_statistics_tool(
        result_store,
        source_id=source.source_id,
        sample_rows=min(source.limits.model_sample_rows, 10),
    )
    execute_python = create_execute_statistical_python_tool(
        result_store,
        run_store,
        source_id=source.source_id,
        limits=execution_limits,
    )
    review_middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "execute_statistical_python": {
                "allowed_decisions": ["approve", "edit", "reject"]
            }
        }
    )
    return {
        "name": "statistical-analysis",
        "description": (
            "Use for statistical tests, experiments, correlations, "
            "distributions, significance, regression, uncertainty, and "
            "similar statistical inference over one source/thread-scoped "
            "saved SQL result. It writes general Python and always requires "
            "human review before execution."
        ),
        "system_prompt": _statistical_subagent_prompt(
            source,
            maximum_attempts=execution_limits.max_execution_attempts,
        ),
        "tools": [inspect_result, execute_python],
        "model": model,
        "skills": ["/project/skills/statistics/"],
        "permissions": permissions,
        # after_model hooks run in reverse order. Keep HITL first so budget
        # checks happen before an approval is exposed.
        "middleware": [review_middleware, *(middleware or [])],
        "response_format": ToolStrategy(
            StatisticalAnalysisResult,
            handle_errors=STATISTICAL_OUTPUT_RETRY_MESSAGE,
            tool_message_content=(
                "Statistical analysis reached a terminal outcome."
            ),
        ),
    }
