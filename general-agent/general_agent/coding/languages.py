"""Read-only Python and compiler-backed JS/TS navigation over source snapshots."""

import asyncio
from pathlib import Path

from general_agent.coding.navigation import Navigation
from general_agent.coding.source import source_revision, source_snapshot, validate_source_path

JAVASCRIPT = {".js", ".jsx", ".cjs", ".mjs", ".ts", ".tsx"}


class Languages:
    def __init__(self, python: Navigation, javascript_probe):
        self.python, self.javascript_probe = python, javascript_probe

    def _documents(self):
        source = source_snapshot(self.python.repo, tracked_paths=self.python.tracked_paths,
            max_files=self.python.max_files, max_bytes=self.python.max_bytes)
        documents, omitted, total = [], [], 0
        for path, entry in sorted(source.items()):
            if Path(path).suffix.lower() not in JAVASCRIPT:
                continue
            if entry["size"] > 256 * 1024 or total + entry["size"] > 2 * 1024 * 1024 or len(documents) >= 200:
                omitted.append({"path": path, "reason": "Compiler snapshot resource limit."})
                continue
            try:
                text = entry["content"].decode("utf-8")
            except UnicodeError:
                omitted.append({"path": path, "reason": "Compiler snapshots require UTF-8 source."})
                continue
            documents.append({"path": path, "text": text})
            total += entry["size"]
        return source_revision(source), documents, omitted[:200]

    async def _typescript(self, operation: str, **arguments):
        revision, documents, omitted = await asyncio.to_thread(self._documents)
        response = await self.javascript_probe({"operation": operation, "documents": documents, **arguments})
        current, _, _ = await asyncio.to_thread(self._documents)
        return {**response, "revision": revision, "omitted": omitted,
                "status": "current" if current == revision else "stale",
                "truncated": response["truncated"] or bool(omitted)}

    async def symbols(self, path: str | None = None, query: str = ""):
        if len(query) > 200:
            raise ValueError("Symbol query exceeds its size limit.")
        if path:
            path = validate_source_path(path.lstrip("/")).as_posix()
            if Path(path).suffix.lower() in JAVASCRIPT:
                return await self._typescript("symbols", path=path, query=query)
            return await asyncio.to_thread(self.python.symbols, path, query)
        python = await asyncio.to_thread(self.python.symbols, None, query)
        _, documents, _ = await asyncio.to_thread(self._documents)
        if not documents:
            return python
        typescript = await self._typescript("symbols", query=query)
        return {"languages": {"python": python, "typescript": typescript},
                "symbols": [*python["symbols"], *typescript["symbols"]][:500],
                "truncated": python["truncated"] or typescript["truncated"] or len(python["symbols"]) + len(typescript["symbols"]) > 500}

    async def definition(self, path: str, line: int, column: int):
        path = validate_source_path(path.lstrip("/")).as_posix()
        if Path(path).suffix.lower() in JAVASCRIPT:
            return await self._typescript("definition", path=path, line=line, column=column)
        return await asyncio.to_thread(self.python.definition, path, line, column)

    async def references(self, symbol: str, language: str = "python"):
        if not symbol or len(symbol) > 200:
            raise ValueError("A bounded symbol name or ID is required.")
        if language == "typescript" or symbol.startswith("ts:"):
            return await self._typescript("references", symbol=symbol)
        if language != "python":
            raise ValueError("Select Python or TypeScript navigation.")
        return await asyncio.to_thread(self.python.references, symbol)

    async def diagnostics(self, path: str | None = None):
        if path:
            path = validate_source_path(path.lstrip("/")).as_posix()
            if Path(path).suffix.lower() in JAVASCRIPT:
                return await self._typescript("diagnostics", path=path)
            return await asyncio.to_thread(self.python.diagnostics, path)
        python = await asyncio.to_thread(self.python.diagnostics)
        _, documents, _ = await asyncio.to_thread(self._documents)
        if not documents:
            return python
        return {"languages": {"python": python, "typescript": await self._typescript("diagnostics")},
                "executes_repository_code": False}
