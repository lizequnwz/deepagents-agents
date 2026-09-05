from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from data_analytics_agent.agents.statistical_analysis.agent import (
    _statistical_subagent_prompt,
)
from data_analytics_agent.agents.statistical_analysis.runner import (
    PythonExecutionLimits,
    StatisticalExecutionError,
    execute_reviewed_python,
)
from data_analytics_agent.agents.statistical_analysis.schemas import (
    PythonExecutionResult,
    StatisticalAnalysisResult,
    StatisticalOutput,
)
from data_analytics_agent.agents.statistical_analysis.tools import (
    create_execute_statistical_python_tool,
    create_inspect_result_for_statistics_tool,
)
from data_analytics_agent.config import Settings
from data_analytics_agent.run_manager import (
    _apply_statistical_analysis,
    _conversation_history_answer,
    _current_statistical_analysis,
    _extract_approval,
)
from data_analytics_agent.schemas import (
    FinalAnswer,
    ResultReference,
    SQLAnalysisResponse,
)
from data_analytics_agent.stores import ResultStore, RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_statistical_prompt_prevents_retry_loops_and_redundant_payloads(
    test_settings: Settings,
) -> None:
    source = test_settings.load_catalog().get("test")
    limits = PythonExecutionLimits()
    prompt = _statistical_subagent_prompt(
        source,
        execution_limits=limits,
        require_approval=True,
    )
    normalized = " ".join(prompt.split())

    assert "inspect_result_for_statistics` exactly once" in normalized
    assert "`result_not_found` or `execution_attempts_exhausted`" in normalized
    assert "Do not copy the code, binary figures, or outputs" in normalized
    assert "two-sided alpha 0.05" in normalized
    assert "random seed 0" in normalized
    assert "require repeated observations within categories" in normalized
    assert "one complete execution" in normalized
    assert "execution_attempts_exhausted" in normalized
    assert "references/regression.md" in normalized
    assert "references/time-series.md" in normalized
    assert f"at most {limits.max_output_items} items" in normalized
    assert f"{limits.max_output_rows} rows" in normalized
    assert f"{limits.max_output_columns} columns" in normalized
    assert "Do not replace total revenue with a price tier" in normalized

    skill = (
        PROJECT_ROOT / "skills/statistics/statistical-analysis/SKILL.md"
    ).read_text(encoding="utf-8")
    normalized_skill = " ".join(skill.split())
    assert "descriptive trends" in normalized_skill
    assert "Do not use executions as staged data exploration" in normalized_skill
    assert (
        PROJECT_ROOT
        / "skills/statistics/statistical-analysis/references/regression.md"
    ).is_file()
    assert (
        PROJECT_ROOT
        / "skills/statistics/statistical-analysis/references/time-series.md"
    ).is_file()


def test_runner_executes_exact_code_with_scoped_dataframe_and_compact_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    code = """\
import os
summary = df.groupby("group", as_index=False)["value"].mean()
analysis_outputs = {
    "Group means": summary,
    "Overall mean": float(df["value"].mean()),
    "Inherited API key": os.getenv("OPENAI_API_KEY"),
}
"""

    result = execute_reviewed_python(
        dataframe=pd.DataFrame(
            {"group": ["a", "a", "b"], "value": [1.0, 3.0, 5.0]}
        ),
        code=code,
        parent_result_id="result-1",
        attempt=1,
        limits=PythonExecutionLimits(timeout_seconds=30),
    )

    assert result.executed_python == code
    assert result.parent_result_id == "result-1"
    assert result.outputs[0].kind == "table"
    assert result.outputs[0].rows == [
        {"group": "a", "value": 2.0},
        {"group": "b", "value": 5.0},
    ]
    assert result.outputs[1].value == 3.0
    assert result.outputs[2].value is None


def test_runner_captures_bounded_matplotlib_figure() -> None:
    code = """\
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
ax.scatter(df["x"], df["y"])
ax.set(title="Relationship", xlabel="X", ylabel="Y")
analysis_outputs = {"Relationship diagnostic": fig}
"""
    result = execute_reviewed_python(
        dataframe=pd.DataFrame({"x": [1, 2], "y": [2, 4]}),
        code=code,
        parent_result_id="result-figure",
        attempt=1,
        limits=PythonExecutionLimits(timeout_seconds=30),
    )

    output = result.outputs[0]
    assert output.kind == "figure"
    assert output.media_type == "image/png"
    assert output.image_base64
    assert "image_base64" not in result.model_facing()["outputs"][0]


def test_runner_supports_regression_and_seasonal_decomposition() -> None:
    code = """\
import statsmodels.api as sm
from statsmodels.tsa.seasonal import STL

ordered = df.sort_values("period").reset_index(drop=True)
fit = sm.OLS(ordered["value"], sm.add_constant(ordered[["time_index"]])).fit()
decomposition = STL(ordered["value"], period=12, robust=True).fit()
analysis_outputs = {
    "Trend coefficient": float(fit.params["time_index"]),
    "Trend confidence interval": fit.conf_int().loc[["time_index"]],
    "Seasonal component": pd.DataFrame({
        "period": ordered["period"].tail(12),
        "seasonal": decomposition.seasonal.tail(12),
    }),
}
"""
    periods = pd.date_range("2023-01-01", periods=36, freq="MS")
    values = [100 + index * 2 + (index % 12) * 3 for index in range(36)]

    result = execute_reviewed_python(
        dataframe=pd.DataFrame(
            {
                "period": periods,
                "time_index": range(36),
                "value": values,
            }
        ),
        code=code,
        parent_result_id="result-time-series",
        attempt=1,
        limits=PythonExecutionLimits(timeout_seconds=30),
    )

    assert result.outputs[0].kind == "scalar"
    assert result.outputs[0].value is not None
    assert result.outputs[1].kind == "table"
    assert result.outputs[2].kind == "table"
    assert len(result.outputs[2].rows) == 12


def test_runner_fails_instead_of_silently_truncating_outputs() -> None:
    with pytest.raises(StatisticalExecutionError, match="compact it"):
        execute_reviewed_python(
            dataframe=pd.DataFrame({"value": range(4)}),
            code='analysis_outputs = {"Too many": df.assign(derived=1)}',
            parent_result_id="result-1",
            attempt=1,
            limits=PythonExecutionLimits(
                timeout_seconds=10,
                max_output_rows=2,
            ),
        )


def test_runner_times_out_reviewed_code() -> None:
    with pytest.raises(StatisticalExecutionError, match="timeout") as error:
        execute_reviewed_python(
            dataframe=pd.DataFrame({"value": [1]}),
            code="while True:\n    pass\n",
            parent_result_id="result-timeout",
            attempt=1,
            limits=PythonExecutionLimits(timeout_seconds=0.1),
        )

    assert error.value.code == "python_timeout"


def test_statistical_tools_enforce_scope_and_refuse_truncated_data() -> None:
    results = ResultStore()
    runs = RunStore()
    saved = results.save(
        thread_id="thread-1",
        source_id="source-1",
        executed_sql="SELECT value FROM measurements",
        columns=["value"],
        rows=[{"value": 1}, {"value": 2}],
        truncated=True,
        elapsed_ms=1,
        originating_question="Return all measurements",
    )
    run_id = runs.create("thread-1", "source-1", "Test the values")
    runtime = SimpleNamespace(
        state={
            "thread_id": "thread-1",
            "run_id": run_id,
            "source_id": "source-1",
            "question": "Test the values",
        }
    )
    inspect = create_inspect_result_for_statistics_tool(
        results,
        runs,
        source_id="source-1",
        sample_rows=10,
        maximum_attempts=2,
    )
    inspected = inspect.func(saved.result_id, runtime)
    assert inspected["truncated"] is True
    assert inspected["sample_rows"] == [{"value": 1}, {"value": 2}]

    execute = create_execute_statistical_python_tool(
        results,
        runs,
        source_id="source-1",
        limits=PythonExecutionLimits(),
    )
    assert "at most 10 items" in execute.description
    assert "at most 50 rows and 20 columns" in execute.description
    refused = execute.func(
        saved.result_id,
        'analysis_outputs = {"Mean": df.value.mean()}',
        runtime,
    )
    assert refused["ok"] is False
    assert refused["code"] == "truncated_dataset"
    assert runs.get_statistical_execution(run_id) is None

    wrong_runtime = SimpleNamespace(
        state={**runtime.state, "thread_id": "thread-2"}
    )
    missing = inspect.func(saved.result_id, wrong_runtime)
    assert missing == {
        "ok": False,
        "code": "result_not_found",
        "repairable": False,
        "result_id": saved.result_id,
        "error": (
            "That result does not exist in this data-source conversation."
        ),
    }


def test_statistical_inspection_reports_and_stops_at_run_attempt_budget() -> None:
    results = ResultStore()
    runs = RunStore()
    saved = results.save(
        thread_id="thread-1",
        source_id="source-1",
        executed_sql="SELECT value FROM measurements",
        columns=["value"],
        rows=[{"value": 1}, {"value": 2}],
        truncated=False,
        elapsed_ms=1,
    )
    run_id = runs.create("thread-1", "source-1", "Analyze")
    runtime = SimpleNamespace(
        state={
            "thread_id": "thread-1",
            "run_id": run_id,
            "source_id": "source-1",
            "question": "Analyze",
        }
    )
    inspect = create_inspect_result_for_statistics_tool(
        results,
        runs,
        source_id="source-1",
        sample_rows=10,
        maximum_attempts=2,
    )

    available = inspect.func(saved.result_id, runtime)
    assert available["ok"] is True
    assert available["attempts_used"] == 0
    assert available["remaining_attempts"] == 2

    runs.reserve_statistical_execution_attempt(run_id, maximum=2)
    runs.reserve_statistical_execution_attempt(run_id, maximum=2)
    exhausted = inspect.func(saved.result_id, runtime)
    assert exhausted == {
        "ok": False,
        "code": "execution_attempts_exhausted",
        "repairable": False,
        "result_id": saved.result_id,
        "attempts_used": 2,
        "remaining_attempts": 0,
        "error": (
            "This run has no statistical Python execution attempts "
            "remaining. Return cannot_analyze without proposing code."
        ),
    }


def test_completed_model_result_can_defer_authoritative_execution_fields() -> None:
    result = StatisticalAnalysisResult(
        outcome="analysis_completed",
        parent_result_id="result-1",
        answer="The estimated difference is small.",
        method="Welch's t-test.",
    )

    assert result.executed_python is None
    assert result.outputs == []


def test_python_approval_contains_complete_code_and_bounded_provenance() -> None:
    results = ResultStore()
    saved = results.save(
        thread_id="thread-1",
        source_id="source-1",
        executed_sql="SELECT value FROM measurements",
        columns=["value"],
        rows=[{"value": value} for value in range(12)],
        truncated=False,
        elapsed_ms=1,
        originating_question="Return measurements",
    )
    code = 'analysis_outputs = {"Mean": float(df.value.mean())}\n'
    interrupt = SimpleNamespace(
        id="python-review-1",
        value={
            "action_requests": [
                {
                    "name": "execute_statistical_python",
                    "args": {"result_id": saved.result_id, "code": code},
                }
            ],
            "review_configs": [
                {"allowed_decisions": ["approve", "edit", "reject"]}
            ],
        }
    )

    approval = _extract_approval(
        [interrupt],
        result_store=results,
        thread_id="thread-1",
        statistical_limits=PythonExecutionLimits(timeout_seconds=17),
    )

    assert approval.review_type == "python"
    assert approval.query == code
    assert approval.parent_result_id == saved.result_id
    assert approval.executed_sql == saved.executed_sql
    assert approval.row_count == 12
    assert len(approval.sample_rows) == 10
    assert approval.timeout_seconds == 17


def test_successful_execution_is_authoritative_in_final_result() -> None:
    model_result = StatisticalAnalysisResult(
        outcome="analysis_completed",
        parent_result_id="result-1",
        answer="The groups differ.",
        method="Welch's t-test with a 95% confidence interval.",
        assumptions=["Two-sided alpha = 0.05."],
        interpretation="The estimated difference is positive.",
    )
    output = {
        "messages": [
            HumanMessage(content="Compare the groups"),
            ToolMessage(
                content=model_result.model_dump_json(),
                tool_call_id="statistics-task",
            ),
        ]
    }
    execution = PythonExecutionResult(
        parent_result_id="result-1",
        executed_python='analysis_outputs = {"Estimate": 2.5}',
        attempt=1,
        outputs=[
            StatisticalOutput(
                name="Estimate",
                kind="scalar",
                value=2.5,
            )
        ],
        elapsed_ms=5,
    )
    answer = FinalAnswer(
        answer="Coordinator wording retained.",
        primary_result_id="result-1",
        results=[
            ResultReference(
                result_id="result-1",
                executed_sql="SELECT value FROM measurements",
                originating_question="Compare the groups",
                short_label="Group measurements",
            )
        ],
    )

    authoritative = _apply_statistical_analysis(answer, output, execution)

    assert authoritative.answer == "Coordinator wording retained."
    assert authoritative.statistical_analysis is not None
    assert (
        authoritative.statistical_analysis.executed_python
        == execution.executed_python
    )
    assert authoritative.statistical_analysis.outputs == execution.outputs
    assert _current_statistical_analysis(output) == model_result


def test_statistical_parent_is_canonical_when_run_has_multiple_sql_results(
) -> None:
    statistical_result = StatisticalAnalysisResult(
        outcome="analysis_completed",
        parent_result_id="statistics-result",
        answer="The groups differ.",
        method="Welch's t-test.",
    )
    later_sql_result = SQLAnalysisResponse(
        answer="A second dataset supports another report section.",
        sql="SELECT category, total FROM report_summary",
        result_id="report-result",
    )
    output = {
        "messages": [
            HumanMessage(content="Create a report with statistical analysis"),
            ToolMessage(
                content=statistical_result.model_dump_json(),
                tool_call_id="statistics-task",
            ),
            ToolMessage(
                content=later_sql_result.model_dump_json(),
                tool_call_id="later-sql-task",
            ),
        ]
    }
    execution = PythonExecutionResult(
        parent_result_id="statistics-result",
        executed_python='analysis_outputs = {"p_value": 0.01}',
        attempt=1,
        outputs=[
            StatisticalOutput(
                name="p_value",
                kind="scalar",
                value=0.01,
            )
        ],
        elapsed_ms=5,
    )
    answer = FinalAnswer(
        answer="Coordinator report summary.",
        primary_result_id="report-result",
        results=[
            ResultReference(
                result_id="report-result",
                executed_sql=later_sql_result.sql,
                originating_question="Report summary",
                short_label="Report summary",
            ),
            ResultReference(
                result_id="statistics-result",
                executed_sql="SELECT group_name, value FROM observations",
                originating_question="Compare groups",
                short_label="Group observations",
            ),
        ],
    )

    authoritative = _apply_statistical_analysis(answer, output, execution)

    assert authoritative.primary_result_id == "statistics-result"
    assert authoritative.statistical_analysis is not None
    assert (
        authoritative.statistical_analysis.parent_result_id
        == "statistics-result"
    )


def test_sparse_coordinator_statistical_result_is_tolerated_and_completed() -> None:
    answer = FinalAnswer.model_validate(
        {
            "answer": "There is evidence of a difference.",
            "primary_result_id": "result-1",
            "results": [
                {
                    "result_id": "result-1",
                    "executed_sql": "SELECT value FROM measurements",
                    "originating_question": "Compare groups",
                    "short_label": "Measurements",
                }
            ],
            "statistical_analysis": {
                "outcome": "analysis_completed",
                "parent_result_id": "result-1",
                "method": "Welch's t-test.",
            },
        }
    )
    execution = PythonExecutionResult(
        parent_result_id="result-1",
        executed_python='analysis_outputs = {"p_value": 0.01}',
        attempt=1,
        outputs=[
            StatisticalOutput(
                name="p_value",
                kind="scalar",
                value=0.01,
            )
        ],
        elapsed_ms=5,
    )

    authoritative = _apply_statistical_analysis(answer, {}, execution)

    assert authoritative.statistical_analysis is not None
    assert (
        authoritative.statistical_analysis.answer
        == "There is evidence of a difference."
    )
    assert (
        authoritative.statistical_analysis.executed_python
        == execution.executed_python
    )
    assert authoritative.statistical_analysis.outputs == execution.outputs


def test_run_store_enforces_two_actual_execution_attempts() -> None:
    runs = RunStore()
    run_id = runs.create("thread-1", "source-1", "Analyze")

    assert [
        runs.reserve_statistical_execution_attempt(run_id, maximum=2)
        for _ in range(2)
    ] == [1, 2]
    with pytest.raises(RuntimeError, match="all 2"):
        runs.reserve_statistical_execution_attempt(run_id, maximum=2)


def test_conversation_history_omits_binary_figure_payload() -> None:
    answer = FinalAnswer(
        answer="A diagnostic figure was produced.",
        primary_result_id="result-1",
        results=[
            ResultReference(
                result_id="result-1",
                executed_sql="SELECT value FROM measurements",
                originating_question="Check diagnostics",
                short_label="Measurements",
            )
        ],
        statistical_analysis=StatisticalAnalysisResult(
            outcome="analysis_completed",
            parent_result_id="result-1",
            executed_python="analysis_outputs = {'Diagnostic': fig}",
            answer="A diagnostic figure was produced.",
            outputs=[
                StatisticalOutput(
                    name="Diagnostic",
                    kind="figure",
                    image_base64="aGVsbG8=",
                    media_type="image/png",
                )
            ],
        ),
    )

    history = _conversation_history_answer(answer)

    assert "aGVsbG8=" not in history
    assert '"kind": "figure"' in history
