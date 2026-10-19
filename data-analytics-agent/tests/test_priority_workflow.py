from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
import yaml
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.ui.api_client import AgentAPIClient, APIError
from tests.priority_support import SavedPopulationGraph


def setup(test_settings):
    services = Services(settings=test_settings)
    thread = services.conversations.create("test")
    base = services.results.save(
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
    services.agent = SavedPopulationGraph(services, base.result_id)
    return services, thread, base


def send(api, thread, **kwargs):
    response = api.post(
        f"/api/conversations/{thread}/messages",
        json={"message": "Count artists and compare names", **kwargs},
    )
    assert response.status_code == 202, response.text
    return api.get("/api/runs/" + response.json()["run_id"]).json()


def test_saved_evidence_supports_report_revisions_exports_and_reopened_history(
    test_settings,
):
    services, thread, base = setup(test_settings)
    with TestClient(create_app(services)) as api:
        first = send(api, thread)
        assert first["status"] == "completed", first.get("error")
        prior = first["answer"]["report"]["report_id"]
        revised = send(api, thread, previous_report_id=prior)
        assert revised["status"] == "completed", revised.get("error")
        answer = revised["answer"]
        assert "3 records" in answer["answer"]
        assert services.results.get_unscoped(
            answer["charts"][0]["source_result_id"]
        ).rows == [
            {"artist": "Alpha", "records": 2},
            {"artist": "Beta", "records": 1},
        ]
        report = api.get("/api/reports/" + answer["report"]["report_id"]).json()
        assert report["previous_report_id"] == prior
        downloaded = api.get(
            f"/api/runs/{revised['run_id']}/download",
            params={"report_id": answer["report"]["report_id"]},
        )
        assert downloaded.status_code == 200, downloaded.text
        with ZipFile(BytesIO(downloaded.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        assert base.result_id in manifest["lineage_result_ids"]
        assert manifest["report_id"] == answer["report"]["report_id"]
        stale = api.post(
            f"/api/conversations/{thread}/messages",
            json={"message": "Count", "previous_report_id": prior},
        )
        assert stale.status_code == 409
    reopened = Services(settings=test_settings).conversations.get(thread)
    assert len(reopened.turns) == 2
    assert reopened.turns[-1].answer.report.report_id == report["report_id"]


@pytest.mark.parametrize("damage", ["invalid_registry", "removed_source"])
def test_reopened_history_preserves_answer_when_source_configuration_fails(
    test_settings, monkeypatch, damage
):
    services, thread, _ = setup(test_settings)
    with TestClient(create_app(services)) as api:
        completed = send(api, thread)
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
        assert any("3 records" in item.value for item in app.markdown)
        assert not app.chat_input
        assert len(reopened.conversations.get(thread).turns) == 1
        report_id = completed["answer"]["report"]["report_id"]
        report = api.get(f"/api/reports/{report_id}")
        assert report.status_code == 200
        assert "Artist population" in report.json()["html"]
