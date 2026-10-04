from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from general_agent.coding.navigation import Navigation
from general_agent.coding.source import source_revision, source_snapshot
from general_agent.workspace import WorkspacePathError


@pytest.fixture
def repo(settings) -> Path:
    root = settings.project_root / "repo"
    root.mkdir()
    return root


def test_scoped_symbols_definitions_and_references(repo):
    text = (
        "value = 1\n"
        "def outer(value):\n"
        "    def inner():\n"
        "        return value\n"
        "    return value + inner()\n"
        "result = outer(value)\n"
        "# value in a comment\n"
        "label = 'value in a string'\n"
    )
    (repo / "main.py").write_text(text)
    navigation = Navigation(repo)
    symbols = navigation.symbols("main.py")
    assert {item["qualified_name"] for item in symbols["symbols"]} >= {
        "value", "outer", "outer.value", "outer.inner", "result", "label",
    }
    definition = navigation.definition("main.py", 4, 15)
    assert definition["definitions"][0]["qualified_name"] == "outer.value"
    parameter = definition["definitions"][0]
    references = navigation.references(parameter["id"])
    assert [(item["line"], item["is_definition"]) for item in references["references"]] == [
        (2, True), (4, False), (5, False),
    ]
    assert [item["line"] for item in navigation.references("value")["references"]] == [1, 2, 4, 5, 6]
    assert references["approximate"]
    assert "cross" not in references["limitations"] or "imports across modules" in references["limitations"]
    assert references["revision"] == source_revision(source_snapshot(repo))


def test_python_analysis_never_imports_or_runs_source(repo):
    marker = repo.parent / "executed"
    (repo / "danger.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
        "def task():\n    return 1\n"
    )
    navigation = Navigation(repo)
    assert navigation.symbols()["symbols"]
    assert navigation.diagnostics()["executes_repository_code"] is False
    assert not marker.exists()


def test_diagnostics_syntax_scope_and_sha_provenance(repo):
    source = "def broken(:\n    pass\n"
    (repo / "broken.py").write_text(source)
    (repo / "scope.py").write_text("return 1\n")
    diagnostics = Navigation(repo).diagnostics()["diagnostics"]
    assert {item["path"] for item in diagnostics} == {"broken.py", "scope.py"}
    assert all(item["severity"] == "error" for item in diagnostics)
    assert next(item for item in diagnostics if item["path"] == "broken.py")["sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert "outside function" in next(item for item in diagnostics if item["path"] == "scope.py")["message"]


def test_unicode_character_columns_and_alias_declarations(repo):
    (repo / "unicode.py").write_text(
        "π = 3\n"
        "value = π\n"
        "import os.path as fs\n"
        "result = fs.exists('π')\n"
    )
    navigation = Navigation(repo)
    declaration = navigation.definition("unicode.py", 2, 8)["definitions"][0]
    assert declaration["name"] == "π"
    assert declaration["column"] == 0
    alias = navigation.definition("unicode.py", 4, 10)["definitions"][0]
    assert alias["name"] == "fs" and alias["line"] == 3 and alias["column"] == 18
    refs = navigation.references("π")["references"]
    assert [(item["line"], item["column"]) for item in refs] == [(1, 0), (2, 8)]


def test_lexical_shadowing_comprehensions_and_class_scope(repo):
    (repo / "scope.py").write_text(
        "name = 1\n"
        "items = [name for name in range(3)]\n"
        "class A:\n"
        "    name = 2\n"
        "    def method(self):\n"
        "        return name\n"
        "result = name\n"
    )
    navigation = Navigation(repo)
    method_reference = navigation.definition("scope.py", 6, 15)["definitions"]
    assert [item["line"] for item in method_reference] == [1]
    comprehension = navigation.definition("scope.py", 2, 10)["definitions"]
    assert len(comprehension) == 1 and comprehension[0]["line"] == 2
    assert "<comprehension>" in comprehension[0]["qualified_name"]


def test_revision_changes_and_stale_symbol_position_does_not_claim_references(repo):
    path = repo / "main.py"
    path.write_text("def task():\n    pass\ntask()\n")
    navigation = Navigation(repo)
    before = navigation.symbols(query="task")
    symbol_id = before["symbols"][0]["id"]
    path.write_text("\n\ndef task():\n    pass\ntask()\n")
    after = navigation.references(symbol_id)
    assert after["revision"] != before["revision"]
    assert not after["references"]


def test_secure_policy_and_tracked_ignored_source(repo):
    (repo / ".env").write_text("SECRET")
    (repo / "main.py").write_text("safe = 1\n")
    (repo / ".gitignore").write_text("ignored.py\n")
    (repo / "ignored.py").write_text("retained = 1\n")
    foreign = repo.parent / "foreign.py"
    foreign.write_text("foreign_secret = 1\n")
    (repo / "alias.py").symlink_to(foreign)
    assert {item["name"] for item in Navigation(repo).symbols()["symbols"]} == {"safe"}
    retained = Navigation(repo, tracked_paths=("ignored.py",)).symbols()
    assert {item["name"] for item in retained["symbols"]} == {"safe", "retained"}
    with pytest.raises(WorkspacePathError):
        Navigation(repo).symbols(".env")
    assert Navigation(repo).symbols("alias.py")["omitted"]
    assert "SECRET" not in str(retained) and "foreign_secret" not in str(retained)


def test_javascript_requires_compiler_and_analysis_has_resource_bounds(repo, monkeypatch):
    (repo / "main.ts").write_text("export function work() {}")
    (repo / "large.py").write_text("#" + "x" * (256 * 1024))
    parsed = []
    original = ast.parse
    def parse(source, *args, **kwargs):
        parsed.append(source)
        return original(source, *args, **kwargs)
    monkeypatch.setattr(ast, "parse", parse)
    output = Navigation(repo).symbols()
    assert not parsed
    assert output["truncated"]
    omitted = {item["path"]: item["reason"] for item in output["omitted"]}
    assert "TypeScript compiler" in omitted["main.ts"]
    assert "resource limit" in omitted["large.py"]
    assert not output["symbols"]


def test_navigation_inputs_and_output_caps(repo):
    (repo / "main.py").write_text("\n".join(f"name_{number} = {number}" for number in range(600)))
    output = Navigation(repo).symbols()
    assert len(output["symbols"]) == 500 and output["truncated"]
    for operation in (
        lambda: Navigation(repo).definition("main.py", 0, 0),
        lambda: Navigation(repo).symbols("../foreign.py"),
        lambda: Navigation(repo).references(""),
        lambda: Navigation(repo).symbols(query="x" * 201),
    ):
        with pytest.raises(ValueError):
            operation()
