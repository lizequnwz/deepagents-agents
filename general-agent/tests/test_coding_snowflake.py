"""Scoped, finite Snowflake reads against the documented SQL API contract."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from general_agent.api import create_app
from general_agent.coding.snowflake import SnowflakeConnection, SnowflakeConnector, SnowflakeError
from tests.fakes import FakeGraph
from tests.test_budgets import ScriptedModel
from tests.test_coding_api import FixtureRuntime, fixture_project, open_session, tool_call, wait_for_attempt

CORP = "A123456"
TOKEN = "snowflake-fixture-secret"
HANDLE = "536fad38-b564-4dc5-9892-a4543504df6c"


def profile(**overrides):
    return SnowflakeConnection.model_validate({"account": "org-account", "token": TOKEN,
        "role": "READ_ROLE", "warehouse": "SMALL_WH", "database": "DB", "schema": "PUBLIC",
        "tables": ["DB.PUBLIC.T"], **overrides})


class Remote:
    def __init__(self):
        self.requests = []
        self.async_mode = False
        self.forever = False
        self.bad_partition = False
        self.received = asyncio.Event()

    def __call__(self, request):
        assert request.url.host == "org-account.snowflakecomputing.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.headers["X-Snowflake-Authorization-Token-Type"] == "OAUTH"
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"statementHandle": HANDLE, "code": "0"})
        if request.method == "POST":
            assert body["timeout"] == 10 and body["warehouse"] == "SMALL_WH" and body["role"] == "READ_ROLE"
            assert body["database"] == "DB" and body["schema"] == "PUBLIC"
            assert body["parameters"]["MULTI_STATEMENT_COUNT"] == "1"
            assert body["statement"].startswith("SELECT ")
            self.received.set()
            if self.async_mode:
                return httpx.Response(202, json={"statementHandle": HANDLE, "statementStatusUrl": "https://bad.example/never-follow"})
        if self.forever:
            return httpx.Response(202, json={"statementHandle": HANDLE})
        return httpx.Response(200, json={"statementHandle": HANDLE,
            "resultSetMetaData": {"numRows": 2, "rowType": [{"name": "C", "type": "text"}],
                                 "partitionInfo": [{}, {}] if self.bad_partition else [{}]},
            "data": [["value"], [TOKEN]]})


async def test_bounded_rows_compiled_identifiers_bound_values_and_provenance():
    remote = Remote()
    connector = SnowflakeConnector(CORP, profile(), transport=httpx.MockTransport(remote))
    try:
        result = await connector.rows(CORP, "DB.PUBLIC.T", ["C"], limit=1, filters={"C": "x'; DROP TABLE T;--"})
        body = remote.requests[0][2]
        assert body["statement"] == 'SELECT "C" FROM "DB"."PUBLIC"."T" WHERE "C"=? LIMIT 2'
        assert body["bindings"] == {"1": {"type": "TEXT", "value": "x'; DROP TABLE T;--"}}
        assert result["rows"] == [["value"]] and result["truncated"]
        assert result["provenance"]["statement_handle"] == HANDLE
        assert result["provenance"]["role"] == "READ_ROLE"
        assert TOKEN not in json.dumps(result)
        second = await connector.rows(CORP, "DB.PUBLIC.T", ["C"], limit=2)
        assert second["rows"][1][0] == "[redacted]"
        assert TOKEN not in json.dumps(profile().profile())
    finally:
        await connector.close()


@pytest.mark.parametrize("arguments", [
    {"table": "DB.PUBLIC.OTHER", "columns": ["C"]},
    {"table": "DB.PUBLIC.T", "columns": ["C; DROP TABLE T"]},
    {"table": "DB.PUBLIC.T", "columns": ["external_function()"]},
    {"table": "DB.PUBLIC.T", "columns": ["*"]},
    {"table": "DB.PUBLIC.T", "columns": ["C"], "limit": True},
    {"table": "DB.PUBLIC.T", "columns": ["C"], "limit": 101},
    {"table": "DB.PUBLIC.T", "columns": ["C"], "filters": {"C": float("nan")}},
    {"table": "DB.PUBLIC.T", "columns": ["C"], "filters": {"C": TOKEN}},
])
async def test_invalid_authority_or_expression_never_sends_request(arguments):
    remote = Remote()
    connector = SnowflakeConnector(CORP, profile(), transport=httpx.MockTransport(remote))
    try:
        with pytest.raises(ValueError):
            await connector.rows(CORP, **arguments)
        with pytest.raises(KeyError):
            await connector.rows("OTHER_CORP", "DB.PUBLIC.T", ["C"])
        assert not remote.requests
    finally:
        await connector.close()


async def test_async_polling_uses_owned_handle_and_incomplete_results_cancel():
    remote = Remote()
    remote.async_mode = True
    connector = SnowflakeConnector(CORP, profile(), transport=httpx.MockTransport(remote))
    try:
        result = await connector.rows(CORP, "DB.PUBLIC.T", ["C"], limit=2)
        assert result["provenance"]["status"] == "completed"
        assert remote.requests[1][:2] == ("GET", f"/api/v2/statements/{HANDLE}")
        remote.bad_partition = True
        with pytest.raises(SnowflakeError) as failure:
            await connector.rows(CORP, "DB.PUBLIC.T", ["C"], limit=2)
        assert failure.value.provenance["cancellation"] == "requested"
        assert remote.requests[-1][:2] == ("POST", f"/api/v2/statements/{HANDLE}/cancel")
    finally:
        await connector.close()


async def test_cancellation_closes_remote_read_without_resubmission():
    remote = Remote()
    remote.async_mode = remote.forever = True
    observed = []
    connector = SnowflakeConnector(CORP, profile(), transport=httpx.MockTransport(remote), observer=lambda record: observed.append(dict(record)))
    try:
        task = asyncio.create_task(connector.rows(CORP, "DB.PUBLIC.T", ["C"]))
        await remote.received.wait()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert remote.requests[-1][1].endswith("/cancel")
        assert observed[-1]["status"] == "cancelled"
        assert observed[-1]["cancellation"] == "requested"
        assert len([request for request in remote.requests if request[1] == "/api/v2/statements"]) == 1
    finally:
        await connector.close()


@pytest.mark.parametrize("overrides", [{"account": "evil.example"}, {"role": "R; DROP TABLE T"}, {"tables": ["T"]}, {"token_type": "PASSWORD"}])
def test_profiles_reject_arbitrary_hosts_roles_and_sql(overrides):
    with pytest.raises(ValueError):
        profile(**overrides)


def test_project_opt_in_agent_tools_and_durable_scoped_receipts(settings):
    settings = replace(settings, snowflake_connections={CORP: profile()})
    root = fixture_project(settings)
    remote = Remote()
    model = ScriptedModel(responses=[tool_call("snowflake_rows", {"table": "DB.PUBLIC.T", "columns": ["C"]}, "read"), AIMessage(content="Inspected")])
    options = dict(settings=settings, graph_override=FakeGraph(), coding_model=model, coding_runtime_factory=FixtureRuntime)
    with TestClient(create_app(**options)) as client:
        coding = client.app.state.coding
        coding.snowflake.connector_factory = lambda corp, connection, **kwargs: SnowflakeConnector(corp, connection, transport=httpx.MockTransport(remote), **kwargs)
        session = open_session(client, root)
        endpoint = f"/projects/{session['project_id']}/snowflake"
        assert client.post(endpoint + "/rows", json={"table": "DB.PUBLIC.T", "columns": ["C"]}).status_code == 409
        status = client.get(endpoint).json()
        assert client.post(endpoint, json={"enabled": True, "expected_digest": "0" * 64}).status_code == 409
        assert client.post(endpoint, json={"enabled": True, "expected_digest": status["digest"]}).status_code == 200
        task = client.post(f"/sessions/{session['id']}/tasks", json={"message": "Inspect Snowflake", "mode": "plan"}).json()
        completed = wait_for_attempt(client, task["id"])
        assert completed["status"] == "completed", completed
        assert completed["snowflake_reads"][0]["provenance"]["statement_handle"] == HANDLE
        receipts = client.get(endpoint + "/reads").json()
        assert len(receipts) == 1 and receipts[0]["status"] == "completed"
        assert TOKEN not in json.dumps(receipts)
        assert client.get(endpoint + "/reads", headers={"X-Corp-ID": "OTHER_CORP"}).status_code == 404
    with TestClient(create_app(**options)) as client:
        assert client.get(endpoint + "/reads").json()[0]["statement_handle"] == HANDLE
