from __future__ import annotations

import io

import pytest

from general_agent.schemas import RunStatus
from general_agent.store import ActiveRunError, Store
from general_agent.workspace import Workspace


def test_per_user_active_run_and_restart_recovery(settings) -> None:
    store = Store(settings.application_db, settings.data_root)
    first = store.create_conversation("First")
    second = store.create_conversation("Second")
    run_id, _ = store.create_run(first.conversation_id, "hello")
    with pytest.raises(ActiveRunError):
        store.create_run(second.conversation_id, "blocked")
    other = store.create_conversation("Other", corp_id="B654321")
    other_run, _ = store.create_run(
        other.conversation_id, "allowed", corp_id="B654321"
    )
    store.close()

    recovered = Store(settings.application_db, settings.data_root)
    run = recovered.get_run(run_id)
    assert run.status == RunStatus.FAILED
    assert "restarted" in (run.error or "")
    assert recovered.get_run(other_run, corp_id="B654321").status == RunStatus.FAILED
    with pytest.raises(KeyError):
        recovered.get_run(run_id, corp_id="B654321")
    recovered.close()


def test_completed_history_usage_and_conversation_cleanup(settings) -> None:
    store = Store(settings.application_db, settings.data_root)
    workspace = Workspace(settings.workspace_root, settings.data_root)
    conversation = store.create_conversation()
    run_id, _ = store.create_run(conversation.conversation_id, "remember only complete")
    attachment, protected = workspace.upload(
        corp_id="A123456",
        conversation_id=conversation.conversation_id,
        original_name="note.txt",
        content_type="text/plain",
        source=io.BytesIO(b"hello"),
        max_bytes=100,
    )
    store.add_attachment(run_id, attachment, protected)
    store.record_model_call(
        run_id,
        "advisor-match-agent",
        {
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "input_token_details": {"cache_read": 2},
            "output_token_details": {"reasoning": 1},
        },
    )
    store.finish_run(run_id, RunStatus.COMPLETED, assistant_text="done")
    assert store.completed_history(conversation.conversation_id)[-1]["content"] == "done"
    diagnostics = store.get_run(run_id).diagnostics
    assert diagnostics.tokens.total_tokens == 14
    assert diagnostics.tokens.cached_input_tokens == 2
    assert diagnostics.token_usage_partial is False
    store.delete_conversation(conversation.conversation_id)
    assert not protected.parent.exists()
    assert (workspace.user_root("A123456") / attachment.relative_path).exists()
    store.close()
