"""Scoped Snowflake SQL API reads compiled from bounded structured requests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections import deque
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from general_agent.coding.http import tls_context
from general_agent.coding.runtime import _shielded
from general_agent.coding.store import CodingConflict, now
from general_agent.workspace import validate_corp_id

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_$]{0,127}\Z")
_MAX_BYTES = 1024 * 1024


def quoted(name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("Snowflake identifiers must be simple, case-sensitive names within 128 characters.")
    return '"' + name + '"'


class SnowflakeConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    account: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    token: SecretStr = Field(repr=False, exclude=True)
    token_type: str = Field(default="OAUTH", pattern=r"^(OAUTH|PROGRAMMATIC_ACCESS_TOKEN|KEYPAIR_JWT)$")
    role: str
    warehouse: str
    database: str
    schema_name: str = Field(alias="schema")
    tables: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("token")
    @classmethod
    def validate_token(cls, token):
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{1,8192}", token.get_secret_value()):
            raise ValueError("A bounded bearer token is required.")
        return token

    @field_validator("role", "warehouse", "database", "schema_name")
    @classmethod
    def validate_name(cls, name):
        quoted(name)
        return name

    @field_validator("tables")
    @classmethod
    def validate_tables(cls, tables):
        for table in tables:
            parts = table.split(".")
            if len(parts) != 3:
                raise ValueError("Approve database.schema.table names explicitly.")
            for part in parts:
                quoted(part)
        return tuple(dict.fromkeys(tables))

    @model_validator(mode="after")
    def credentials_are_separate(self):
        if self.token.get_secret_value() in json.dumps(self.profile()):
            raise ValueError("Connection credentials cannot appear in the read profile.")
        return self

    def profile(self):
        return {**self.model_dump(by_alias=True), "policy": "bounded-read-v1", "query_timeout_seconds": 10,
                "max_rows": 100, "max_response_bytes": _MAX_BYTES}

    def digest(self):
        return hashlib.sha256(json.dumps(self.profile(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SnowflakeError(ValueError):
    def __init__(self, message: str, provenance: dict):
        super().__init__(message)
        self.provenance = provenance


class SnowflakeConnector:
    def __init__(self, corp_id: str, connection: SnowflakeConnection, *, transport=None, observer=None):
        self.corp_id, self.connection = validate_corp_id(corp_id), connection
        self.observer = observer
        self._client = httpx.AsyncClient(base_url=f"https://{connection.account}.snowflakecomputing.com",
            timeout=5, trust_env=False, follow_redirects=False, verify=tls_context(), transport=transport,
            headers={"Authorization": "Bearer " + connection.token.get_secret_value(),
                     "X-Snowflake-Authorization-Token-Type": connection.token_type,
                     "Accept": "application/json", "User-Agent": "general-agent-coding/0.1"})

    def _table(self, corp_id: str, table: str):
        if validate_corp_id(corp_id) != self.corp_id:
            raise KeyError("Snowflake connection not found.")
        if table not in self.connection.tables:
            raise ValueError("The requested table is outside the approved Snowflake scope.")
        return table.split(".")

    async def _request(self, method: str, path: str, *, body=None, params=None):
        async with asyncio.timeout(5), self._client.stream(method, path, json=body, params=params) as response:
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > _MAX_BYTES:
                    raise ValueError("Snowflake response exceeds its one MiB bound.")
            if response.status_code not in {200, 202}:
                raise ValueError(f"Snowflake read failed (HTTP {response.status_code}); no automatic resubmission.")
            try:
                record = json.loads(data)
            except ValueError:
                raise ValueError("Snowflake returned an invalid JSON response.") from None
            if not isinstance(record, dict):
                raise ValueError("Snowflake returned an invalid result object.")
            return response.status_code, record

    async def _query(self, statement: str, bindings: dict, *, limit: int):
        request_id = str(uuid4())
        provenance = {"account": self.connection.account, "role": self.connection.role,
                      "warehouse": self.connection.warehouse, "policy_digest": self.connection.digest(),
                      "request_id": request_id, "statement": statement, "bindings": bindings,
                      "requested": now(), "statement_handle": None, "status": "submitted"}
        handle, completed = None, False
        if self.observer:
            self.observer(provenance)
        try:
            async with asyncio.timeout(20):
                status, record = await self._request("POST", "/api/v2/statements", params={"requestId": request_id, "async": "true"},
                    body={"statement": statement, "timeout": 10, "warehouse": self.connection.warehouse,
                          "role": self.connection.role, "database": self.connection.database,
                          "schema": self.connection.schema_name, "bindings": bindings,
                          "parameters": {"MULTI_STATEMENT_COUNT": "1"}})
                handle = str(UUID(record["statementHandle"]))
                provenance["statement_handle"] = handle
                if self.observer:
                    self.observer(provenance)
                for _ in range(8):
                    if status == 200:
                        break
                    await asyncio.sleep(0.5)
                    status, record = await self._request("GET", f"/api/v2/statements/{handle}")
                    if str(UUID(record["statementHandle"])) != handle:
                        raise ValueError("Snowflake returned a different statement handle.")
                if status != 200:
                    raise ValueError("Snowflake read exceeded its bounded polling allowance.")
                metadata = record["resultSetMetaData"]
                rows = record["data"]
                row_type = metadata["rowType"]
                partitions = metadata.get("partitionInfo", [])
                if (type(metadata.get("numRows")) is not int or metadata["numRows"] > limit + 1
                        or not isinstance(rows, list) or len(rows) != metadata["numRows"]
                        or not isinstance(row_type, list) or not 1 <= len(row_type) <= 100
                        or len(partitions) > 1
                        or any(not isinstance(row, list) or len(row) != len(row_type) for row in rows)):
                    raise ValueError("Snowflake result is incomplete or exceeds its row/column bound.")
                columns = [column["name"] for column in row_type]
                if any(not isinstance(name, str) or len(name) > 128 for name in columns):
                    raise ValueError("Snowflake returned invalid column metadata.")
                # Credentials never become query evidence, even if a remote row echoes them.
                token = self.connection.token.get_secret_value()
                columns = [name.replace(token, "[redacted]") for name in columns]
                safe_rows = [[str(value).replace(token, "[redacted]") if value is not None else None for value in row] for row in rows[:limit]]
                completed = True
                provenance.update(status="completed", retrieved=now())
                return {"columns": columns, "rows": safe_rows, "truncated": len(rows) > limit,
                        "provenance": provenance, "untrusted_content": True}
        except asyncio.CancelledError:
            provenance["status"] = "cancelled"
            raise
        except Exception as exc:
            provenance["status"] = "failed"
            message = str(exc).replace(self.connection.token.get_secret_value(), "[redacted]")[:1000]
            raise SnowflakeError(message or "Snowflake read did not complete.", provenance) from None
        finally:
            if handle is not None and not completed:
                async def cancel():
                    try:
                        await self._request("POST", f"/api/v2/statements/{handle}/cancel")
                        provenance["cancellation"] = "requested"
                    except Exception:
                        provenance["cancellation"] = "unconfirmed; server query timeout remains ten seconds"
                await _shielded(cancel())
            if self.observer:
                self.observer(provenance)

    async def schema(self, corp_id: str, table: str):
        database, schema, name = self._table(corp_id, table)
        statement = (f"SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM {quoted(database)}.INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_CATALOG=? AND TABLE_SCHEMA=? AND TABLE_NAME=? ORDER BY ORDINAL_POSITION LIMIT 101")
        return await self._query(statement, {str(index): {"type": "TEXT", "value": value}
            for index, value in enumerate((database, schema, name), 1)}, limit=100)

    async def rows(self, corp_id: str, table: str, columns: list[str], *, limit: int = 20, filters: dict | None = None):
        parts = self._table(corp_id, table)
        if type(limit) is not int or not 1 <= limit <= 100 or not isinstance(columns, list) or not 1 <= len(columns) <= 20:
            raise ValueError("Read 1–100 rows and 1–20 explicit columns.")
        selection = ", ".join(quoted(column) for column in columns)
        predicates, bindings = [], {}
        filters = filters or {}
        if not isinstance(filters, dict) or len(filters) > 8:
            raise ValueError("At most eight bound equality filters are supported.")
        for column, value in filters.items():
            column = quoted(column)
            if value is None:
                predicates.append(column + " IS NULL")
                continue
            if type(value) is bool:
                kind, text = "BOOLEAN", str(value).lower()
            elif type(value) is int and abs(value) < 10**18:
                kind, text = "FIXED", str(value)
            elif type(value) is float and math.isfinite(value):
                kind, text = "REAL", str(value)
            elif isinstance(value, str) and len(value) <= 1000:
                kind, text = "TEXT", value
            else:
                raise ValueError("Filters accept bounded text, finite numbers, booleans, or null.")
            if self.connection.token.get_secret_value() in text:
                raise ValueError("A filter cannot contain connection credentials.")
            bindings[str(len(bindings) + 1)] = {"type": kind, "value": text}
            predicates.append(column + "=?")
        statement = f"SELECT {selection} FROM {'.'.join(quoted(part) for part in parts)}"
        if predicates:
            statement += " WHERE " + " AND ".join(predicates)
        statement += f" LIMIT {limit + 1}"
        return await self._query(statement, bindings, limit=limit)

    async def close(self):
        await self._client.aclose()


class SnowflakeService:
    def __init__(self, coding, *, connector_factory=SnowflakeConnector):
        self.coding, self.connector_factory = coding, connector_factory
        self._locks = {}
        self._admissions = {}

    def status(self, corp_id: str, project_id: str):
        project = self.coding.store.project(corp_id, project_id)
        connection = self.coding.settings.snowflake_connections.get(corp_id)
        return {"configured": bool(connection), "enabled": bool(connection and project.get("snowflake") == connection.digest()),
                "profile": connection.profile() if connection else None, "digest": connection.digest() if connection else None}

    def enable(self, corp_id: str, project_id: str, enabled: bool, digest: str | None):
        status = self.status(corp_id, project_id)
        if self.coding.store.project_has_pending(corp_id, project_id):
            raise CodingConflict("Finish or stop this project's pending tasks before changing Snowflake authority.")
        if enabled and (not status["configured"] or status["digest"] != digest):
            raise CodingConflict("Review the configured Snowflake account, role, warehouse and tables first.")
        project = self.coding.store.project(corp_id, project_id)
        project["snowflake"] = digest if enabled else None
        self.coding.store.save_project(corp_id, project)
        return self.status(corp_id, project_id)

    async def read(self, corp_id: str, project_id: str, operation: str, *, table: str, **arguments):
        if operation not in {"schema", "rows"}:
            raise ValueError("Unsupported Snowflake read operation.")
        if not self.status(corp_id, project_id)["enabled"]:
            raise CodingConflict("Explicitly enable the currently configured Snowflake read scope for this project first.")
        lock = self._locks.setdefault(corp_id, asyncio.Lock())
        if lock.locked():
            raise CodingConflict("A Snowflake read is already active for this corporation.")
        loop = asyncio.get_running_loop()
        admissions = self._admissions.setdefault(corp_id, deque())
        while admissions and admissions[0] < loop.time() - 60:
            admissions.popleft()
        if len(admissions) >= 20:
            raise CodingConflict("Snowflake read limit reached: at most twenty requests per minute.")
        admissions.append(loop.time())
        async with lock:
            connection = self.coding.settings.snowflake_connections[corp_id]
            connector = self.connector_factory(corp_id, connection,
                observer=lambda provenance: self.coding.store.record_connector_query(corp_id, project_id, provenance))
            try:
                return await getattr(connector, operation)(corp_id, table, **arguments)
            finally:
                await connector.close()
