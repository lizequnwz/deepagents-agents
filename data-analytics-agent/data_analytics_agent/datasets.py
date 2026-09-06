"""Typed immutable datasets with bounded previews and disk-backed computations."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from threading import RLock
from collections.abc import Iterable
from typing import Any
import os
from time import perf_counter
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from data_analytics_agent.persistence import LocalStorage
from data_analytics_agent.schemas import SavedResult, ResultPage
from data_analytics_agent.profiling import profile_result


class StoreNotFound(KeyError):
    pass


class ResultStore:
    def __init__(
        self,
        storage: LocalStorage | None = None,
        *,
        max_rows: int = 1_000_000,
        max_bytes: int = 268_435_456,
    ):
        self.storage = storage or LocalStorage()
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self._items = self.storage.load("datasets", SavedResult)
        self._lock = RLock()

    def forget_conversations(self, thread_ids: set[str]) -> None:
        """Evict records after durable history deletion."""
        with self._lock:
            keys = [
                key for key, item in self._items.items() if item.thread_id in thread_ids
            ]
            for key in keys:
                del self._items[key]

    def save(
        self, *, columns: list[str], rows: list[dict[str, Any]], **metadata
    ) -> SavedResult:
        table = (
            pa.Table.from_pylist(rows)
            if rows
            else pa.table({name: pa.array([], type=pa.string()) for name in columns})
        )
        return self.save_batches(
            table.to_batches(max_chunksize=8192), columns=columns, **metadata
        )

    def save_batches(
        self,
        batches: Iterable[pa.RecordBatch],
        *,
        thread_id: str,
        source_id: str,
        executed_sql: str = "",
        columns: list[str] | None = None,
        truncated: bool = False,
        elapsed_ms: float = 0,
        originating_question: str = "",
        purpose: str = "",
        parent_result_ids: list[str] | None = None,
        kind: str = "source_sql",
        execution_id: str | None = None,
        max_rows: int | None = None,
    ) -> SavedResult:
        started = perf_counter()
        result_id = str(uuid4())
        path = self.storage.artifacts / f"{result_id}.parquet"
        temporary = path.with_suffix(".partial")
        count = size = 0
        preview = []
        cap = min(max_rows or self.max_rows, self.max_rows)
        # Spool typed batches, then unify their schemas before the final write.
        # Null-first columns and later Decimal scales must not lose their types.
        try:
            with TemporaryDirectory(
                dir=self.storage.artifacts, prefix="extract-"
            ) as directory:
                parts, schemas = [], []
                for batch in batches:
                    if len(set(batch.schema.names)) != len(batch.schema.names):
                        raise ValueError("Result columns must have unique aliases.")
                    columns = batch.schema.names
                    schemas.append(batch.schema)
                    capped = count + batch.num_rows > cap
                    if capped:
                        batch = batch.slice(0, max(0, cap - count))
                        truncated = True
                    if size + batch.nbytes > self.max_bytes:
                        truncated = True
                        break
                    part = Path(directory) / f"{len(parts)}.parquet"
                    pq.write_table(pa.Table.from_batches([batch]), part)
                    parts.append(part)
                    preview.extend(
                        batch.slice(0, max(0, 10 - len(preview))).to_pylist()
                    )
                    count += batch.num_rows
                    size += batch.nbytes
                    if capped:
                        break
                schema = (
                    pa.unify_schemas(schemas, promote_options="permissive")
                    if schemas
                    else pa.schema([(name, pa.string()) for name in columns or []])
                )
                with pq.ParquetWriter(temporary, schema) as writer:
                    for part in parts:
                        for batch in pq.ParquetFile(part).iter_batches(batch_size=8192):
                            writer.write_table(
                                pa.Table.from_batches([batch]).cast(schema)
                            )
                os.replace(temporary, path)
        finally:
            if hasattr(batches, "close"):
                batches.close()
            temporary.unlink(missing_ok=True)
        # DuckDB computes compact full-artifact summaries without copying rows into Python.
        with duckdb.connect() as db:
            relation = db.read_parquet(str(path))
            profile = profile_result(columns or [], preview)
            summaries = []
            for column in profile.columns:
                name = '"' + column.name.replace('"', '""') + '"'
                values = relation.aggregate(
                    f"count({name}), count(distinct {name}), min({name}), max({name})"
                ).fetchone()
                nonnull_values = (
                    relation.filter(f"{name} IS NOT NULL")
                    .project(name)
                    .limit(100)
                    .to_arrow_table()
                    .to_pylist()
                )
                inferred = profile_result([column.name], nonnull_values).columns[0]
                column = column.model_copy(
                    update={
                        "physical_kind": inferred.physical_kind,
                        "role_candidates": inferred.role_candidates,
                        "temporal_kind": inferred.temporal_kind,
                    }
                )
                if values[1] > 30 and values[1] / max(count, 1) > 0.2:
                    column = column.model_copy(
                        update={
                            "role_candidates": tuple(
                                role
                                for role in column.role_candidates
                                if role.role.value != "discrete_numeric"
                            )
                        }
                    )
                summaries.append(
                    column.model_copy(
                        update={
                            "non_null_count": values[0],
                            "null_count": count - values[0],
                            "distinct_count": values[1],
                            "minimum": values[2],
                            "maximum": values[3],
                        }
                    )
                )
            profile = profile.model_copy(
                update={"row_count": count, "columns": tuple(summaries)}
            )
        clean = " ".join((purpose or originating_question or "Dataset").split())
        result = SavedResult(
            result_id=result_id,
            thread_id=thread_id,
            source_id=source_id,
            executed_sql=executed_sql,
            originating_question=originating_question,
            short_label=clean[:100],
            columns=columns or [],
            parquet_path=str(path),
            preview=preview,
            parent_result_ids=parent_result_ids or [],
            kind=kind,
            execution_id=execution_id,
            byte_count=size,
            profile=profile,
            row_count=count,
            truncated=truncated,
            elapsed_ms=elapsed_ms or (perf_counter() - started) * 1000,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self.storage.put("datasets", result_id, result)
            self._items[result_id] = result
        return result

    def get_unscoped(self, result_id: str) -> SavedResult:
        with self._lock:
            if result_id not in self._items:
                raise StoreNotFound(result_id)
            return self._items[result_id]

    def get(self, result_id: str, thread_id: str, *, source_id: str | None = None):
        result = self.get_unscoped(result_id)
        if result.thread_id != thread_id or (
            source_id is not None and result.source_id != source_id
        ):
            raise StoreNotFound(result_id)
        return result

    def list_for_conversation(self, thread_id: str, *, source_id: str):
        return sorted(
            [
                r
                for r in self._items.values()
                if r.thread_id == thread_id and r.source_id == source_id
            ],
            key=lambda r: r.created_at,
        )

    def page(
        self,
        result_id: str,
        thread_id: str,
        *,
        source_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ):
        result = self.get(result_id, thread_id, source_id=source_id)
        return self._page(result, offset, limit)

    def page_unscoped(self, result_id: str, *, offset: int = 0, limit: int = 100):
        return self._page(self.get_unscoped(result_id), offset, limit)

    def _page(self, result: SavedResult, offset: int, limit: int):
        if offset < 0 or limit < 1:
            raise ValueError("Invalid page bounds.")
        with duckdb.connect() as db:
            rows = (
                db.read_parquet(result.parquet_path)
                .limit(limit, offset)
                .to_arrow_table()
                .to_pylist()
            )
        return ResultPage(
            result_id=result.result_id,
            source_id=result.source_id,
            executed_sql=result.executed_sql,
            columns=result.columns,
            rows=rows,
            profile=result.profile,
            row_count=result.row_count,
            truncated=result.truncated,
            elapsed_ms=result.elapsed_ms,
            offset=offset,
            limit=limit,
        )
