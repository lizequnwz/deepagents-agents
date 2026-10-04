"""Read-only, bounded Python navigation over approved repository source bytes."""

from __future__ import annotations

import ast
import hashlib
import io
import sys
import time
import tokenize
from pathlib import Path

from general_agent.coding.source import source_revision, source_snapshot, validate_source_path


_LIMITATION = (
    "Python bindings are resolved within lexical scopes in one file. Repository-wide name matches "
    "are approximate; attributes, imports across modules, dynamic bindings and runtime behavior "
    "are not resolved. Comments and string contents are excluded."
)
_JAVASCRIPT = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}


class _IndexLimit(ValueError):
    pass


class _PythonIndex(ast.NodeVisitor):
    def __init__(self, path: str, text: str):
        self.path = path
        self.lines = text.splitlines()
        self.scope: tuple[str, ...] = ()
        self.scope_kinds = {(): "module"}
        self.globals: dict[tuple[str, ...], set[str]] = {}
        self.nonlocals: dict[tuple[str, ...], set[str]] = {}
        self.symbols: list[dict] = []
        self.binding_map: dict[tuple[tuple[str, ...], str], list[dict]] = {}
        self.symbol_ids: dict[str, dict] = {}
        self.occurrences: list[dict] = []
        self.nodes = 0
        self.name_tokens: dict[tuple[int, str], list] = {}
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.NAME:
                self.name_tokens.setdefault((token.start[0], token.string), []).append(token)

    def visit(self, node):
        self.nodes += 1
        if self.nodes > 20_000 or len(self.symbols) > 2000 or len(self.occurrences) > 10_000:
            raise _IndexLimit("File exceeds the static index limit.")
        return super().visit(node)

    def position(self, node) -> tuple[int, int, int, int]:
        line = node.lineno
        end_line = getattr(node, "end_lineno", line) or line
        column = self._column(line, node.col_offset)
        end_column = self._column(end_line, getattr(node, "end_col_offset", node.col_offset) or 0)
        return line, column, end_line, end_column

    def _column(self, line: int, byte_column: int) -> int:
        if not 1 <= line <= len(self.lines):
            return byte_column
        return len(self.lines[line - 1].encode("utf-8")[:byte_column].decode("utf-8", "ignore"))

    def _name_position(self, node, name: str, *, last: bool = False) -> tuple[int, int]:
        line, column, end_line, end_column = self.position(node)
        candidates = [token for token in self.name_tokens.get((line, name), ())
                      if token.start[1] >= column and token.start < (end_line, end_column)]
        if candidates:
            token = candidates[-1] if last else candidates[0]
            return token.start
        return line, column

    def _binding_scope(self, name: str) -> tuple[str, ...]:
        if name in self.globals.get(self.scope, ()):
            return ()
        if name in self.nonlocals.get(self.scope, ()):
            scope = self.scope[:-1]
            nearest = None
            while scope:
                if self.scope_kinds.get(scope) != "class":
                    nearest = nearest or scope
                    if (scope, name) in self.binding_map:
                        return scope
                scope = scope[:-1]
            if nearest:
                return nearest
        return self.scope

    def binding(self, name: str, kind: str, node, *, position=None) -> dict:
        scope = self._binding_scope(name)
        line, column = position or self.position(node)[:2]
        scope_names = [item.split("@", 1)[0] for item in scope]
        qualified = ".".join((*scope_names, name))
        symbol_id = hashlib.sha256(f"{self.path}\0{line}\0{column}\0{qualified}".encode()).hexdigest()[:24]
        record = {"id": symbol_id, "name": name, "qualified_name": qualified, "kind": kind,
                  "path": self.path, "line": line, "column": column,
                  "end_line": getattr(node, "end_lineno", line) or line,
                  "end_column": self._column(getattr(node, "end_lineno", line) or line,
                                             getattr(node, "end_col_offset", 0) or 0),
                  "_scope": scope}
        self.symbols.append(record)
        self.binding_map.setdefault((scope, name), []).append(record)
        self.symbol_ids[symbol_id] = record
        self.occurrences.append({"name": name, "path": self.path, "line": line, "column": column,
                                 "end_column": column + len(name), "is_definition": True,
                                 "_scope": scope, "_symbol_id": symbol_id})
        return record

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.binding(node.id, "variable", node)
        else:
            line, column, _, end_column = self.position(node)
            self.occurrences.append({"name": node.id, "path": self.path, "line": line,
                                     "column": column, "end_column": end_column,
                                     "is_definition": False, "_scope": self.scope})

    def _function(self, node):
        self.binding(node.name, "function", node, position=self._name_position(node, node.name))
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                         *((node.args.vararg,) if node.args.vararg else ()),
                         *((node.args.kwarg,) if node.args.kwarg else ())):
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        parent = self.scope
        self.scope += (f"{node.name}@{node.lineno}",)
        self.scope_kinds[self.scope] = "function"
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                         *((node.args.vararg,) if node.args.vararg else ()),
                         *((node.args.kwarg,) if node.args.kwarg else ())):
            self.binding(argument.arg, "parameter", argument)
        for child in node.body:
            self.visit(child)
        self.scope = parent

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node):
        for expression in (*node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        parent = self.scope
        self.scope += (f"<lambda>@{node.lineno}",)
        self.scope_kinds[self.scope] = "function"
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                         *((node.args.vararg,) if node.args.vararg else ()),
                         *((node.args.kwarg,) if node.args.kwarg else ())):
            self.binding(argument.arg, "parameter", argument)
        self.visit(node.body)
        self.scope = parent

    def visit_ClassDef(self, node):
        self.binding(node.name, "class", node, position=self._name_position(node, node.name))
        for expression in (*node.decorator_list, *node.bases, *node.keywords):
            self.visit(expression)
        parent = self.scope
        self.scope += (f"{node.name}@{node.lineno}",)
        self.scope_kinds[self.scope] = "class"
        for child in node.body:
            self.visit(child)
        self.scope = parent

    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname or alias.name.split(".", 1)[0]
            self.binding(name, "import", alias, position=self._name_position(alias, name, last=bool(alias.asname)))

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == "*":
                continue
            name = alias.asname or alias.name
            self.binding(name, "import", alias, position=self._name_position(alias, name, last=bool(alias.asname)))

    def visit_Global(self, node):
        self.globals.setdefault(self.scope, set()).update(node.names)

    def visit_Nonlocal(self, node):
        self.nonlocals.setdefault(self.scope, set()).update(node.names)

    def visit_ExceptHandler(self, node):
        if node.type:
            self.visit(node.type)
        if node.name:
            self.binding(node.name, "variable", node, position=self._name_position(node, node.name, last=True))
        for child in node.body:
            self.visit(child)

    def _comprehension(self, node):
        self.visit(node.generators[0].iter)
        parent = self.scope
        self.scope += (f"<comprehension>@{node.lineno}",)
        self.scope_kinds[self.scope] = "function"
        for number, generator in enumerate(node.generators):
            if number:
                self.visit(generator.iter)
            self.visit(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.scope = parent

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension

    def resolve(self, occurrence: dict) -> list[dict]:
        if occurrence.get("_symbol_id"):
            return [self.symbol_ids[occurrence["_symbol_id"]]]
        name, scope = occurrence["name"], occurrence["_scope"]
        if name in self.globals.get(scope, ()):
            scope = ()
        elif name in self.nonlocals.get(scope, ()):
            scope = scope[:-1]
        starting = scope
        while True:
            if scope == starting or self.scope_kinds.get(scope) != "class":
                candidates = self.binding_map.get((scope, name), ())
                if candidates:
                    return candidates
            if not scope:
                return []
            scope = scope[:-1]


def _public(record: dict) -> dict:
    return {key: value for key, value in record.items() if not key.startswith("_")}


class Navigation:
    """Static tools never execute repository code, imports, hooks or check commands."""

    def __init__(self, repo: Path, tracked_paths: tuple[str, ...] = (), *,
                 max_files: int = 5000, max_bytes: int = 50 * 1024 * 1024):
        self.repo = Path(repo)
        self.tracked_paths = tracked_paths
        self.max_files, self.max_bytes = max_files, max_bytes

    def _index(self, path: str | None = None) -> tuple[dict, list[_PythonIndex]]:
        relative = validate_source_path(path.lstrip("/")).as_posix() if path else None
        source = source_snapshot(self.repo, tracked_paths=self.tracked_paths,
                                 max_files=self.max_files, max_bytes=self.max_bytes)
        output = {"revision": source_revision(source), "language": "python", "approximate": True,
                  "python_version": sys.version.split()[0],
                  "limitations": _LIMITATION, "diagnostics": [], "omitted": [],
                  "columns": "zero-based Unicode characters; lines are one-based", "truncated": False}
        documents = []
        total = 0
        deadline = time.monotonic() + 4
        selected = [relative] if relative else sorted(source)
        for name in selected:
            if name not in source:
                output["omitted"].append({"path": name, "reason": "Not present in the approved source inventory."})
                continue
            suffix = Path(name).suffix.lower()
            if suffix in _JAVASCRIPT:
                output["omitted"].append({"path": name, "reason": "Handled by the configured TypeScript compiler navigation tools."})
                continue
            if suffix != ".py":
                continue
            entry = source[name]
            if entry["size"] > 256 * 1024 or total + entry["size"] > 2 * 1024 * 1024 or len(documents) >= 200 or time.monotonic() >= deadline:
                output["omitted"].append({"path": name, "reason": "Static analysis resource limit."})
                output["truncated"] = True
                continue
            total += entry["size"]
            provenance = {"path": name, "sha256": entry["sha256"]}
            try:
                text = entry["content"].decode("utf-8")
                tree = ast.parse(text, filename=name, type_comments=True)
                # Compile validates Python scope errors without running code.
                compile(tree, name, "exec")
                document = _PythonIndex(name, text)
                document.visit(tree)
                documents.append(document)
            except SyntaxError as exc:
                output["diagnostics"].append({**provenance, "severity": "error", "code": "python-syntax",
                                              "line": exc.lineno or 1, "column": max(0, (exc.offset or 1) - 1),
                                              "message": exc.msg[:1000]})
            except UnicodeDecodeError:
                output["diagnostics"].append({**provenance, "severity": "error", "code": "python-encoding",
                                              "line": 1, "column": 0, "message": "Python source must be UTF-8 for this tool."})
            except (ValueError, RecursionError, tokenize.TokenError) as exc:
                output["omitted"].append({"path": name, "reason": "Python source exceeds supported static analysis constraints."})
                output["truncated"] = True
        if len(output["omitted"]) > 200:
            output["omitted"] = output["omitted"][:200]
            output["truncated"] = True
        output["diagnostics"] = output["diagnostics"][:200]
        return output, documents

    def symbols(self, path: str | None = None, query: str = "") -> dict:
        if len(query) > 200:
            raise ValueError("Symbol query exceeds its size limit.")
        output, documents = self._index(path)
        matches = [symbol for document in documents for symbol in document.symbols
                   if query.casefold() in symbol["qualified_name"].casefold()]
        output["symbols"] = [_public(symbol) for symbol in matches[:500]]
        output["truncated"] |= len(matches) > 500
        return output

    def definition(self, path: str, line: int, column: int) -> dict:
        if line < 1 or column < 0:
            raise ValueError("Definitions require one-based lines and zero-based columns.")
        output, documents = self._index(path)
        candidates = []
        for document in documents:
            occurrence = next((item for item in document.occurrences if item["line"] == line
                               and item["column"] <= column < item["end_column"]), None)
            if occurrence:
                candidates = document.resolve(occurrence)
                output["name"] = occurrence["name"]
        output["definitions"] = [_public(item) for item in candidates[:100]]
        output["ambiguous"] = len(candidates) != 1
        return output

    def references(self, symbol: str) -> dict:
        if not symbol or len(symbol) > 200:
            raise ValueError("A bounded symbol ID or name is required.")
        output, documents = self._index()
        target = next((item for document in documents for item in document.symbols
                       if item["id"] == symbol), None)
        matches = []
        for document in documents:
            for occurrence in document.occurrences:
                if target is not None:
                    if document.path != target["path"]:
                        continue
                    selected = any(item["id"] == target["id"] for item in document.resolve(occurrence))
                else:
                    selected = occurrence["name"] == symbol
                if selected:
                    matches.append(_public(occurrence))
        output["symbol"] = _public(target) if target else symbol
        output["references"] = matches[:1000]
        output["truncated"] |= len(matches) > 1000
        return output

    def diagnostics(self, path: str | None = None) -> dict:
        output, _ = self._index(path)
        output["kind"] = "static_python_syntax_and_scope"
        output["executes_repository_code"] = False
        return output
