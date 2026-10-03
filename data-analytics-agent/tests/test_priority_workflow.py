from io import BytesIO
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile

import pytest
import yaml
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.ui.api_client import AgentAPIClient, APIError
from tests.priority_support import FreshPopulationGraph, SavedPopulationGraph


def setup(test_settings):
    s = Services(settings=test_settings)
    thread = s.conversations.create("test")
    base = s.results.save(
        columns=["ArtistId", "Name"],
        rows=[
            {"ArtistId": 1, "Name": "Alpha"},
            {"ArtistId": 2, "Name": "Beta"},
            {"ArtistId": 3, "Name": "Alpha"},
        ],
        thread_id=thread,
        source_id="test",
        purpose="Complete artist snapshot",
        originating_question="Count artists",
        executed_sql="SELECT ArtistId, Name FROM Artist",
    )
    s.agent = SavedPopulationGraph(s, base.result_id)
    return s, thread, base


def send(api, thread, base, **kwargs):
    response = api.post(
        f"/api/conversations/{thread}/messages",
        json={
            "message": "Count artists and compare names",
            "selected_result_id": base.result_id,
            **kwargs,
        },
    )
    assert response.status_code == 202, response.text
    return api.get("/api/runs/" + response.json()["run_id"]).json()


def test_shared_scope_agrees_in_answer_chart_report_and_bundle(test_settings):
    s, thread, base = setup(test_settings)
    with TestClient(create_app(s)) as api:
        first = send(api, thread, base)
        assert first["status"] == "completed", first.get("error")
        prior = first["answer"]["report"]["report_id"]
        scoped = send(
            api,
            thread,
            base,
            scope={"base_result_id": base.result_id, "categories": {"Name": ["Alpha"]}},
            previous_report_id=prior,
        )
        assert scoped["status"] == "completed", scoped.get("error")
        answer = scoped["answer"]
        assert answer["analytical_input"]["row_count"] == 2
        assert "2 records" in answer["answer"]
        assert s.results.get_unscoped(answer["charts"][0]["source_result_id"]).rows == [
            {"artist": "Alpha", "records": 2}
        ]
        report = api.get("/api/reports/" + answer["report"]["report_id"]).json()
        assert "Name: Alpha" in report["html"]
        assert report["previous_report_id"] == prior
        downloaded = api.get(
            f"/api/runs/{scoped['run_id']}/download",
            params={"report_id": answer["report"]["report_id"]},
        )
        assert downloaded.status_code == 200, (
            downloaded.text if downloaded.status_code != 200 else ""
        )
        with ZipFile(BytesIO(downloaded.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        assert manifest["analytical_input"] == answer["analytical_input"]
        stale = api.post(
            f"/api/conversations/{thread}/messages",
            json={
                "message": "Count",
                "selected_result_id": base.result_id,
                "previous_report_id": prior,
            },
        )
        assert stale.status_code == 409
    reopened = Services(settings=test_settings).conversations.get(thread)
    assert reopened.analytical_input.scope.categories == {"Name": ["Alpha"]}


def test_failed_refresh_keeps_last_successful_answer(test_settings):
    s, thread, base = setup(test_settings)
    with TestClient(create_app(s)) as api:
        first = send(api, thread, base)
        report_id = first["answer"]["report"]["report_id"]
        response = api.post(
            f"/api/runs/{first['run_id']}/refresh", json={"report_id": report_id}
        )
        assert response.status_code == 202
        refreshed = api.get("/api/runs/" + response.json()["run_id"]).json()
        assert refreshed["status"] == "failed"
        assert "Synthetic warehouse" in refreshed["error"]
        current = api.get(f"/api/conversations/{thread}").json()
        assert len(current["turns"]) == 1
        assert current["turns"][0]["answer"]["report"]["report_id"] == report_id
        assert api.get("/api/reports/" + report_id).status_code == 200
        stale = api.post(
            f"/api/runs/{first['run_id']}/refresh", json={"report_id": "stale"}
        )
        assert stale.status_code == 409


def test_successful_refresh_uses_changed_source_and_preserves_old_evidence(
    test_settings,
):
    s, thread, base = setup(test_settings)
    s.agent = FreshPopulationGraph(s, base.result_id)
    with TestClient(create_app(s)) as api:
        first = send(
            api,
            thread,
            base,
            scope={"base_result_id": base.result_id, "categories": {"Name": ["Alpha"]}},
        )
        assert first["status"] == "completed", first.get("error")
        old_report = first["answer"]["report"]["report_id"]
        old_input = first["answer"]["analytical_input"]["input_result_id"]
        with sqlite3.connect(test_settings.project_root / "db/test.sqlite") as db:
            db.executemany(
                "INSERT INTO Artist VALUES (?, ?)",
                [(1, "Alpha"), (2, "Gamma"), (3, "Alpha"), (4, "Alpha")],
            )
        response = api.post(
            f"/api/runs/{first['run_id']}/refresh", json={"report_id": old_report}
        )
        assert response.status_code == 202, response.text
        fresh = api.get("/api/runs/" + response.json()["run_id"]).json()
        assert fresh["status"] == "completed", fresh.get("error")
        assert fresh["answer"]["analytical_input"]["row_count"] == 3
        assert "3 records" in fresh["answer"]["answer"]
        assert fresh["answer"]["refreshed_from_report_id"] == old_report
        new_report = api.get(
            "/api/reports/" + fresh["answer"]["report"]["report_id"]
        ).json()
        assert new_report["previous_report_id"] == old_report
        assert new_report["report_id"] != old_report
        assert s.results.get_unscoped(old_input).row_count == 2
        assert s.results.get_unscoped(base.result_id).row_count == 3
        new_base = s.results.get_unscoped(
            fresh["answer"]["analytical_input"]["selected_result_id"]
        )
        assert (
            new_base.kind == "source_sql"
            and new_base.executed_sql == "SELECT ArtistId, Name FROM Artist"
        )
        assert new_base.row_count == 4 and new_base.result_id != base.result_id
        assert new_base.created_at > base.created_at


def test_file_refresh_requires_new_upload_and_conversation(test_settings):
    from tests.test_uploads import reviewed

    s = Services(settings=test_settings)
    upload = reviewed(s)
    run = s.runs.create(upload.thread_id, upload.source_id, "Analyze this file")
    with TestClient(create_app(s)) as api:
        response = api.post(
            f"/api/runs/{run}/refresh", json={"report_id": "file-report"}
        )
        assert response.status_code == 422
        assert "new upload" in response.json()["detail"]


def test_native_dataset_selection_scope_and_refresh_failure(test_settings, monkeypatch):
    s, thread, base = setup(test_settings)
    with TestClient(create_app(s)) as api:
        send(api, thread, base)

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise APIError(
                    str(response.json().get("detail")), status_code=response.status_code
                )
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        app.query_params["thread_id"] = thread
        app.run(timeout=15)
        assert not app.exception
        assert (
            next(v for v in app.selectbox if v.label == "Analyze").value
            == base.result_id
        )
        next(t for t in app.toggle if t.label == "Refine saved population").set_value(
            True
        ).run(timeout=15)
        next(m for m in app.multiselect if m.label == "Category columns").set_value(
            ["Name"]
        ).run(timeout=15)
        next(m for m in app.multiselect if m.label == "Name").set_value(["Alpha"])
        next(b for b in app.button if b.label == "Apply population").click().run(
            timeout=15
        )
        assert not app.exception
        app.run(timeout=15)
        assert any("2 records" in m.value for m in app.markdown)
        next(b for b in app.button if b.label == "Refresh from warehouse").click().run(
            timeout=15
        )
        app.run(timeout=15)
        assert not app.exception
        assert any("2 records" in m.value for m in app.markdown)
        assert any("Synthetic warehouse" in e.value for e in app.error)


@pytest.mark.parametrize("category_count", [1, 101])
def test_vanished_category_refresh_keeps_empty_scope_and_exact_followup_input(
    test_settings, monkeypatch, category_count
):
    s, thread, base = setup(test_settings)
    s.agent = FreshPopulationGraph(s, base.result_id)
    with sqlite3.connect(test_settings.project_root / "db/test.sqlite") as db:
        db.executemany(
            "INSERT INTO Artist VALUES (?, ?)",
            [(i + 1, f"Beta {i}") for i in range(category_count)],
        )
    with TestClient(create_app(s)) as api:
        first = send(
            api,
            thread,
            base,
            scope={"base_result_id": base.result_id, "categories": {"Name": ["Alpha"]}},
        )
        response = api.post(
            f"/api/runs/{first['run_id']}/refresh",
            json={"report_id": first["answer"]["report"]["report_id"]},
        )
        fresh = api.get("/api/runs/" + response.json()["run_id"]).json()
        assert fresh["status"] == "completed", fresh.get("error")
        current = fresh["answer"]["analytical_input"]
        assert current["row_count"] == 0
        assert current["scope"]["categories"] == {"Name": ["Alpha"]}
        followup = api.post(
            f"/api/conversations/{thread}/messages",
            json={
                "message": "Count the same selected population again",
                "selected_result_id": current["selected_result_id"],
                "scope": current["scope"],
            },
        )
        assert followup.status_code == 202, followup.text
        completed = api.get("/api/runs/" + followup.json()["run_id"]).json()
        assert completed["status"] == "completed", completed.get("error")
        assert (
            completed["analytical_input"]["input_result_id"]
            == current["input_result_id"]
        )
        assert "0 records" in completed["answer"]["answer"]

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise APIError(
                    str(response.json().get("detail")), status_code=response.status_code
                )
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        app.query_params["thread_id"] = thread
        app.run(timeout=15)
        next(t for t in app.toggle if t.label == "Refine saved population").set_value(
            True
        ).run(timeout=15)
        assert not app.exception
        if category_count == 1:
            assert next(m for m in app.multiselect if m.label == "Name").value == []
            assert any("absent" in warning.value for warning in app.warning)
        else:
            assert (
                next(m for m in app.multiselect if m.label == "Category columns").value
                == []
            )
            assert any("no longer supports" in warning.value for warning in app.warning)
            assert next(
                button for button in app.button if button.label == "Apply population"
            ).disabled


@pytest.mark.parametrize("damage", ["invalid_registry", "removed_source"])
def test_reopened_history_preserves_answer_when_source_configuration_fails(
    test_settings, monkeypatch, damage
):
    services, thread, base = setup(test_settings)
    with TestClient(create_app(services)) as api:
        completed = send(
            api,
            thread,
            base,
            scope={"base_result_id": base.result_id, "categories": {"Name": ["Alpha"]}},
        )
        assert completed["status"] == "completed"
    registry = yaml.safe_load(test_settings.data_sources_config_path.read_text())
    if damage == "invalid_registry":
        registry["sources"]["test"]["semantic_model"] = "outside.osi.yaml"
        expected_status = 503
    else:
        del registry["sources"]["test"]
        registry["default_source"] = "test_alt"
        expected_status = 404
    test_settings.data_sources_config_path.write_text(yaml.safe_dump(registry))
    reopened = Services(settings=test_settings)
    with TestClient(create_app(reopened), raise_server_exceptions=False) as api:
        response = api.get(f"/api/conversations/{thread}/source")
        assert response.status_code == expected_status, response.text

        def request(self, method, path, **kwargs):
            kwargs.pop("timeout", None)
            response = api.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise APIError(
                    str(response.json().get("detail")), status_code=response.status_code
                )
            return response.json()

        monkeypatch.setattr(AgentAPIClient, "request", request)
        app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py"))
        app.query_params["thread_id"] = thread
        app.run(timeout=15)
        assert not app.exception
        assert any("source is unavailable" in error.value for error in app.error)
        assert any("2 records" in item.value for item in app.markdown)
        assert not app.chat_input
        assert len(reopened.conversations.get(thread).turns) == 1
        report_id = completed["answer"]["report"]["report_id"]
        assert "Name: Alpha" in api.get(f"/api/reports/{report_id}").json()["html"]
