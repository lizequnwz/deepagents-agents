from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from text2sql_agent.run_manager import (
    RunManager,
    _apply_sql_analysis,
    _current_sql_analysis,
)
from text2sql_agent.schemas import FinalAnswer, SQLAnalysisResult
from text2sql_agent.stores import ConversationStore, ResultStore, RunStore


def _manager(results: ResultStore) -> RunManager:
    return RunManager(
        agent=None,
        conversations=ConversationStore(),
        runs=RunStore(),
        results=results,
    )


def test_stored_executed_sql_overrides_stale_model_sql() -> None:
    results = ResultStore()
    saved = results.save(
        thread_id="thread-a",
        executed_sql="SELECT Name FROM Artist ORDER BY Name",
        columns=["Name"],
        rows=[{"Name": "AC/DC"}],
        truncated=False,
        elapsed_ms=1.0,
    )
    answer = FinalAnswer(
        answer="One artist was returned.",
        sql="SELECT stale_model_sql",
        result_id=saved.result_id,
    )

    canonical = _manager(results)._validate_answer_provenance(
        answer,
        "thread-a",
    )

    assert canonical.sql == saved.executed_sql
    assert canonical.result_id == saved.result_id


def test_unknown_or_cross_conversation_result_fails_safely() -> None:
    results = ResultStore()
    saved = results.save(
        thread_id="thread-a",
        executed_sql="SELECT 1",
        columns=["1"],
        rows=[{"1": 1}],
        truncated=False,
        elapsed_ms=1.0,
    )
    answer = FinalAnswer(
        answer="A result was returned.",
        sql="SELECT 1",
        result_id=saved.result_id,
    )

    with pytest.raises(
        RuntimeError,
        match="unknown or out-of-conversation result",
    ):
        _manager(results)._validate_answer_provenance(answer, "thread-b")


def test_sql_without_result_id_is_not_presented_as_executed() -> None:
    answer = FinalAnswer(
        answer="Here is a proposed query.",
        sql="SELECT Name FROM Artist",
    )

    with pytest.raises(
        RuntimeError,
        match="SQL without an executed result",
    ):
        _manager(ResultStore())._validate_answer_provenance(
            answer,
            "thread-a",
        )


def test_no_query_answer_may_omit_sql_and_result_id() -> None:
    answer = FinalAnswer(answer="What would you like to analyze?")

    validated = _manager(ResultStore())._validate_answer_provenance(
        answer,
        "thread-a",
    )

    assert validated == answer


def test_current_sql_subagent_result_overrides_stale_coordinator_narrative() -> None:
    analysis = SQLAnalysisResult(
        answer="The reviewed query returned the top 10 artists.",
        sql="SELECT Name FROM Artist LIMIT 10",
        result_id="result-10",
        row_count=10,
        interpretation="Ten artists were returned.",
    )
    output = {
        "messages": [
            HumanMessage(content="Show the top 5 artists"),
            AIMessage(content="", tool_calls=[]),
            ToolMessage(
                content=analysis.model_dump_json(),
                tool_call_id="task-call",
            ),
            AIMessage(content="Top 5 artists were returned."),
        ]
    }
    coordinator_answer = FinalAnswer(
        answer="Top 5 artists were returned.",
        sql=analysis.sql,
        result_id=analysis.result_id,
    )

    authoritative = _apply_sql_analysis(coordinator_answer, output)

    assert authoritative.answer == analysis.answer
    assert authoritative.interpretation == analysis.interpretation
    assert authoritative.result_id == analysis.result_id


def test_previous_turn_sql_analysis_is_not_reused_for_a_followup() -> None:
    previous = SQLAnalysisResult(
        answer="Previous answer.",
        sql="SELECT 1",
        result_id="old-result",
        row_count=1,
    )
    output = {
        "messages": [
            HumanMessage(content="Run SQL"),
            ToolMessage(
                content=previous.model_dump_json(),
                tool_call_id="old-task",
            ),
            HumanMessage(content="Explain what this metric means"),
            AIMessage(content="It means one."),
        ]
    }

    assert _current_sql_analysis(output) is None
