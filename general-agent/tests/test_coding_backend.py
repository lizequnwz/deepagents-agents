from io import BytesIO

import pytest
from langchain_core.messages import AIMessage
from PIL import Image

from general_agent.budgets import RunBudget, RunBudgetCallback, run_budget_scope
from general_agent.coding.agent import build_coding_agent
from general_agent.coding.backend import RepositoryBackend
from tests.test_budgets import ScriptedModel


def test_source_permissions_revision_and_assets(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("old")
    backend = RepositoryBackend(repo, read_only=False)
    assert backend.edit("/code.py", "old", "new").error is None
    assert (repo / "code.py").read_text() == "new"
    (repo / "code.py").write_text("external")
    assert "changed outside" in backend.write("/new.py", "bad").error
    backend.reconcile()
    assert backend.write("/.env", "secret").error
    assert backend.write("/.github/workflows/check.yml", "checks").error is None
    (repo / "escape").symlink_to(tmp_path)
    assert backend.write("/escape/outside", "bad").error
    assert not (tmp_path / "outside").exists()
    data = BytesIO()
    Image.new("RGB", (2, 2)).save(data, format="PNG")
    (repo / "image.png").write_bytes(data.getvalue())
    assert backend.read("/image.png").file_data["encoding"] == "base64"
    (repo / "input.pdf").write_text("%PDF harmless text")
    assert "document skill" in backend.read("/input.pdf").error


def test_mutation_cannot_exceed_storage_limit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("original")
    backend = RepositoryBackend(repo, read_only=False, max_bytes=10)
    assert backend.write("/a.py", "x" * 11).error
    assert (repo / "a.py").read_text() == "original"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["plan", "review"])
async def test_delegated_inspection_mode_cannot_write(settings, tmp_path, mode):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("original")
    model = ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "task", "id": "delegate", "args": {
            "description": "Attempt source mutation", "subagent_type": "general-purpose"}}]),
        AIMessage(content="", tool_calls=[{"name": "write_file", "id": "write", "args": {
            "file_path": "/repo/code.py", "content": "bad"}}]),
        AIMessage(content="Review complete"), AIMessage(content="Complete"),
    ])
    backend = RepositoryBackend(repo, read_only=True)
    graph = build_coding_agent(settings, repository=backend, mode=mode,
                               checkpointer=None, model=model)
    budget = RunBudget(max_model_calls=10, max_tool_calls=10, max_task_calls=5)
    with run_budget_scope(budget):
        await graph.ainvoke({"messages": [{"role": "user", "content": "Inspect"}]},
                           config={"callbacks": [RunBudgetCallback()]})
    assert (repo / "code.py").read_text() == "original"
    assert backend.write("/code.py", "bad").error
    assert backend.edit("/code.py", "original", "bad").error
    assert backend.delete("/code.py").error


@pytest.mark.asyncio
async def test_implementation_graph_edits_only_selected_copy(settings, tmp_path):
    original = tmp_path / "original.py"
    original.write_text("original")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("original")
    model = ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "edit_file", "id": "edit", "args": {
            "file_path": "/repo/code.py", "old_string": "original", "new_string": "changed"}}]),
        AIMessage(content="Done"),
    ])
    graph = build_coding_agent(settings, repository=RepositoryBackend(repo, read_only=False),
                               mode="implement", checkpointer=None, model=model)
    with run_budget_scope(RunBudget(max_model_calls=5, max_tool_calls=5, max_task_calls=2)):
        await graph.ainvoke({"messages": [{"role": "user", "content": "Edit"}]},
                           config={"callbacks": [RunBudgetCallback()]})
    assert (repo / "code.py").read_text() == "changed"
    assert original.read_text() == "original"
