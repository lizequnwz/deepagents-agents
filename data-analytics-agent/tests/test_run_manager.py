from __future__ import annotations

import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from data_analytics_agent.run_manager import (
    DEBUG_STATE_CHAR_LIMIT,
    RunDiagnosticsCallback,
    RunManager,
    _activity_for_tool,
    _apply_sql_analysis,
    _bounded_tool_value,
    _current_sql_analysis,
    _sanitize_state_snapshot,
    _statistical_execution_completion,
)
from data_analytics_agent.profiling import profile_result
from data_analytics_agent.schemas import (
    CoordinatorResponse,
    FinalAnswer,
    ResultReference,
    SQLAnalysisResult,
)
from data_analytics_agent.stores import ConversationStore, ResultStore, RunStore


def _manager(results: ResultStore) -> RunManager:
    return RunManager(
        agent=object(),
        conversations=ConversationStore(),
        runs=RunStore(),
        results=results,
    )


def _reference(result: object, *, executed_sql: str | None = None) -> ResultReference:
    return ResultReference(
        result_id=result.result_id,
        executed_sql=executed_sql or result.executed_sql,
        originating_question=result.originating_question,
        short_label=result.short_label,
    )


def test_diagnostics_callback_attributes_provider_usage_to_agent() -> None:
    runs = RunStore()
    run_id = runs.create("thread-a", "source-a", "Question")
    callback = RunDiagnosticsCallback(runs, run_id)
    model_call_id = uuid4()

    callback.on_chat_model_start(
        {},
        [[HumanMessage(content="Question")]],
        run_id=model_call_id,
        metadata={"lc_agent_name": "text-to-sql"},
    )
    callback.on_llm_end(
        LLMResult(
            generations=[
                [
                    ChatGeneration(
                        message=AIMessage(
                            content="Answer",
                            usage_metadata={
                                "input_tokens": 12,
                                "output_tokens": 3,
                                "total_tokens": 15,
                            },
                        )
                    )
                ]
            ]
        ),
        run_id=model_call_id,
    )

    diagnostics = runs.diagnostics(run_id)
    assert diagnostics.tokens.total_tokens == 15
    assert diagnostics.token_usage_partial is False
    assert diagnostics.agents[0].agent == "text-to-sql"


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
        primary_result_id=saved.result_id,
        results=[_reference(saved, executed_sql="SELECT stale_model_sql")],
    )

    canonical = _manager(results)._validate_answer_provenance(
        answer,
        "thread-a",
        "source-a",
    )

    assert canonical.results[0].executed_sql == saved.executed_sql
    assert canonical.primary_result_id == saved.result_id


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
        primary_result_id=saved.result_id,
        results=[_reference(saved)],
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


def test_multi_result_claims_are_deduplicated_and_primary_first() -> None:
    results = ResultStore()
    first = results.save(
        thread_id="thread-a",
        source_id="source-a",
        executed_sql="SELECT category, total FROM summary",
        columns=["category", "total"],
        rows=[{"category": "A", "total": 10}],
        truncated=False,
        elapsed_ms=1.0,
        originating_question="Compare categories",
    )
    primary = results.save(
        thread_id="thread-a",
        source_id="source-a",
        executed_sql="SELECT month, total FROM trend",
        columns=["month", "total"],
        rows=[{"month": "2026-01", "total": 10}],
        truncated=False,
        elapsed_ms=1.0,
        originating_question="Show the trend",
    )

    answer = _manager(results)._answer_from_coordinator(
        CoordinatorResponse(
            answer="The trend explains the category change.",
            primary_result_id=primary.result_id,
            supporting_result_ids=[
                first.result_id,
                primary.result_id,
                first.result_id,
            ],
        ),
        thread_id="thread-a",
        source_id="source-a",
    )

    assert answer.primary_result_id == primary.result_id
    assert [item.result_id for item in answer.results] == [
        primary.result_id,
        first.result_id,
    ]
    assert answer.results[0].executed_sql == primary.executed_sql
    assert answer.results[1].originating_question == "Compare categories"


def test_primary_must_appear_in_supporting_result_claims() -> None:
    with pytest.raises(RuntimeError, match="missing from supporting results"):
        _manager(ResultStore())._answer_from_coordinator(
            CoordinatorResponse(
                answer="Invalid evidence.",
                primary_result_id="result-1",
                supporting_result_ids=[],
            ),
            thread_id="thread-a",
            source_id="source-a",
        )


def test_supporting_results_without_primary_fail_safely() -> None:
    answer = FinalAnswer(
        answer="Here is a result.",
        results=[
            ResultReference(
                result_id="result-1",
                executed_sql="SELECT 1",
                originating_question="Question",
                short_label="Result",
            )
        ],
    )

    with pytest.raises(
        RuntimeError,
        match="supporting results without a primary result",
    ):
        _manager(ResultStore())._validate_answer_provenance(
            answer,
            "thread-a",
            "source-a",
        )


def test_no_query_answer_may_omit_evidence() -> None:
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
    coordinator_answer = CoordinatorResponse(
        answer="Top 5 artists were returned.",
        primary_result_id=analysis.result_id,
        supporting_result_ids=[analysis.result_id],
    )

    authoritative = _apply_sql_analysis(coordinator_answer, output)

    assert authoritative.answer == analysis.answer
    assert authoritative.interpretation == analysis.interpretation
    assert authoritative.primary_result_id == analysis.result_id
    assert authoritative.supporting_result_ids == [analysis.result_id]


def test_investigation_synthesis_is_not_replaced_by_last_sql_result() -> None:
    rows = [{"category": "A", "total": 10}]
    latest = SQLAnalysisResult(
        answer="Category A totals 10.",
        sql="SELECT category, total FROM latest_step",
        result_id="latest-result",
        columns=["category", "total"],
        sample_rows=rows,
        profile=profile_result(["category", "total"], rows),
        row_count=1,
        truncated=False,
        assumptions=["Latest step only"],
        interpretation="This describes only the latest subquestion.",
    )
    output = {
        "messages": [
            HumanMessage(content="Investigate the change"),
            ToolMessage(
                content=latest.model_dump_json(),
                tool_call_id="latest-task",
            ),
            AIMessage(content="Synthesis across both results."),
        ]
    }
    coordinator_answer = CoordinatorResponse(
        answer="Synthesis across both results.",
        primary_result_id="primary-result",
        supporting_result_ids=["primary-result", latest.result_id],
        assumptions=["Common date window"],
        interpretation="The two grains reconcile.",
    )

    authoritative = _apply_sql_analysis(coordinator_answer, output)

    assert authoritative.answer == coordinator_answer.answer
    assert authoritative.assumptions == coordinator_answer.assumptions
    assert authoritative.interpretation == coordinator_answer.interpretation


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


def test_activity_names_specific_skill() -> None:
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


def test_statistical_activity_distinguishes_success_failure_and_no_execution(
) -> None:
    assert _statistical_execution_completion(
        {"ok": True, "attempt": 1}
    ) == (
        "Statistical Python succeeded · attempt 1",
        False,
        {"attempt": 1},
    )
    assert _statistical_execution_completion(
        {
            "ok": False,
            "code": "python_execution_failed",
            "attempt": 1,
            "remaining_attempts": 1,
        }
    ) == (
        "Statistical Python execution failed · attempt 1",
        True,
        {
            "attempt": 1,
            "remaining_attempts": 1,
            "code": "python_execution_failed",
        },
    )
    assert _statistical_execution_completion(
        {
            "ok": False,
            "code": "execution_attempts_exhausted",
            "remaining_attempts": 0,
        }
    ) == (
        "Statistical Python was not run · execution budget exhausted",
        True,
        {"remaining_attempts": 0, "code": "execution_attempts_exhausted"},
    )


def test_tool_input_is_secret_redacted_and_bounded() -> None:
    bounded = _bounded_tool_value(
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
