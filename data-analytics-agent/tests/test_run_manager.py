from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from data_analytics_agent.run_manager import (
    DEBUG_STATE_CHAR_LIMIT,
    RunManager,
    _activity_arguments,
    _activity_for_tool,
    _apply_sql_analysis,
    _bounded_debug_value,
    _current_sql_analysis,
    _sanitize_state_snapshot,
)
from data_analytics_agent.profiling import profile_result
from data_analytics_agent.schemas import FinalAnswer, SQLAnalysisResult
from data_analytics_agent.stores import ConversationStore, ResultStore, RunStore


def _manager(results: ResultStore) -> RunManager:
    return RunManager(
        agent=object(),
        conversations=ConversationStore(),
        runs=RunStore(),
        results=results,
    )


def test_stored_executed_sql_overrides_stale_model_sql() -> None:
    results = ResultStore()
    saved = results.save(
        thread_id="thread-a",
        source_id="source-a",
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
        "source-a",
    )

    assert canonical.sql == saved.executed_sql
    assert canonical.result_id == saved.result_id


def test_unknown_or_cross_conversation_result_fails_safely() -> None:
    results = ResultStore()
    saved = results.save(
        thread_id="thread-a",
        source_id="source-a",
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
        _manager(results)._validate_answer_provenance(
            answer,
            "thread-b",
            "source-a",
        )

    with pytest.raises(
        RuntimeError,
        match="unknown or out-of-conversation result",
    ):
        _manager(results)._validate_answer_provenance(
            answer,
            "thread-a",
            "source-b",
        )


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
            "source-a",
        )


def test_no_query_answer_may_omit_sql_and_result_id() -> None:
    answer = FinalAnswer(answer="What would you like to analyze?")

    validated = _manager(ResultStore())._validate_answer_provenance(
        answer,
        "thread-a",
        "source-a",
    )

    assert validated == answer


def test_current_sql_subagent_result_overrides_stale_coordinator_narrative() -> None:
    rows = [{"Name": "AC/DC"}]
    analysis = SQLAnalysisResult(
        answer="The reviewed query returned the top 10 artists.",
        sql="SELECT Name FROM Artist LIMIT 10",
        result_id="result-10",
        columns=["Name"],
        sample_rows=rows,
        profile=profile_result(["Name"], rows),
        row_count=10,
        truncated=False,
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
    rows = [{"value": 1}]
    previous = SQLAnalysisResult(
        answer="Previous answer.",
        sql="SELECT 1",
        result_id="old-result",
        columns=["value"],
        sample_rows=rows,
        profile=profile_result(["value"], rows),
        row_count=1,
        truncated=False,
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


def test_activity_names_specific_skill_and_curates_known_arguments() -> None:
    skill_input = {
        "file_path": "/project/skills/text-to-sql/query-writing/SKILL.md",
        "offset": 0,
        "limit": 1000,
        "api_key": "never-show",
    }

    assert _activity_for_tool("read_file", skill_input) == (
        "skill",
        "Loading skill · query-writing",
    )
    assert _activity_arguments("read_file", skill_input) == {
        "path": "skills/text-to-sql/query-writing/SKILL.md",
        "offset": 0,
        "limit": 1000,
        "skill": "query-writing",
    }
    assert _activity_arguments(
        "task",
        {
            "subagent_type": "text-to-sql",
            "description": "private model-authored assignment",
        },
    ) == {"subagent_type": "text-to-sql"}
    assert _activity_arguments(
        "inspect_result_for_chart", {"result_id": "1234567890abcdef"}
    ) == {"result": "12345678"}
    assert _activity_arguments("unknown_tool", {"rows": [1, 2]}) == {}


def test_debug_tool_input_is_secret_redacted_and_bounded() -> None:
    bounded = _bounded_debug_value(
        {"query": "SELECT 1", "api_key": "never-show", "value": "x" * 5000}
    )

    serialized = json.dumps(bounded)
    assert "never-show" not in serialized
    assert "[REDACTED]" in serialized
    assert "truncated_characters" in bounded


def test_debug_state_snapshot_is_safe_latest_state_shape() -> None:
    snapshot = _sanitize_state_snapshot(
        {
            "thread_id": "thread-1",
            "run_id": "run-1",
            "source_id": "source-1",
            "question": "Analyze revenue",
            "password": "never-show",
            "messages": [
                {"type": "human", "content": f"message-{index}-" + "x" * 500}
                for index in range(12)
            ],
            "memory_contents": {"/project/AGENTS.md": "private policy"},
            "skills_metadata": [
                {
                    "name": "query-writing",
                    "path": "/project/skills/query-writing/SKILL.md",
                    "description": "not needed in debug state",
                }
            ],
            "structured_response": {"answer": "y" * 30_000},
        },
        agent="text-to-sql",
        namespace=["text-to-sql:abc"],
    )

    serialized = json.dumps(snapshot.state)
    assert snapshot.agent == "text-to-sql"
    assert snapshot.namespace == ["text-to-sql:abc"]
    assert snapshot.omitted_messages == 2
    assert len(snapshot.state["messages"]) == 10
    assert snapshot.state["password"] == "[REDACTED]"
    assert "private policy" not in serialized
    assert snapshot.state["memory_contents"] == {
        "/project/AGENTS.md": {"characters": 14}
    }
    assert snapshot.state["skills_metadata"] == [
        {
            "name": "query-writing",
            "path": "/project/skills/query-writing/SKILL.md",
        }
    ]
    assert snapshot.truncated is True
    assert len(serialized) <= DEBUG_STATE_CHAR_LIMIT
