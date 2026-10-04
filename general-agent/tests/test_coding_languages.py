"""Compiler snapshot scope, fresh source evidence and Python-only operation."""

import pytest

from general_agent.coding.languages import Languages
from general_agent.coding.navigation import Navigation


async def test_python_navigation_needs_no_container(tmp_path):
    (tmp_path / "app.py").write_text("def greet():\n    return 'hello'\n")
    async def unavailable(request):
        raise AssertionError("A Python-only query must not start a container.")
    tools = Languages(Navigation(tmp_path), unavailable)
    assert (await tools.symbols())["symbols"][0]["name"] == "greet"
    assert (await tools.diagnostics())["executes_repository_code"] is False


async def test_javascript_probe_receives_only_approved_bounded_source(tmp_path):
    (tmp_path / "app.ts").write_text("export const value = 2;\n")
    (tmp_path / ".env").write_text("SECRET=private")
    (tmp_path / "large.js").write_text("x" * (256 * 1024 + 1))
    (tmp_path / "linked.ts").symlink_to(tmp_path / "app.ts")
    observed = []
    async def probe(request):
        observed.append(request)
        return {"protocol": 1, "typescript_version": "5.9.3", "symbols": [], "truncated": False}
    tools = Languages(Navigation(tmp_path), probe)
    result = await tools.symbols("app.ts")
    assert [item["path"] for item in observed[0]["documents"]] == ["app.ts"]
    assert result["status"] == "current"
    assert result["truncated"] and result["omitted"][0]["path"] == "large.js"
    with pytest.raises(ValueError):
        await tools.definition("../outside.ts", 1, 0)


async def test_source_change_marks_compiler_result_stale(tmp_path):
    source = tmp_path / "app.ts"
    source.write_text("const value = 1;\n")
    async def probe(request):
        source.write_text("const value = 2;\n")
        return {"protocol": 1, "typescript_version": "5.9.3", "references": [], "truncated": False}
    result = await Languages(Navigation(tmp_path), probe).references("value", "typescript")
    assert result["status"] == "stale"
