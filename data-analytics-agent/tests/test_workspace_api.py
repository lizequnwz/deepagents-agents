"""The React client uses the existing scoped artifacts and a single API server."""

from dataclasses import replace

from fastapi.testclient import TestClient

from data_analytics_agent.api import Services, create_app
from data_analytics_agent.config import Settings
from data_analytics_agent.visualization.tools import create_chart_tool
from data_analytics_agent.visualization.schemas import ChartRequest


def test_chart_figures_preserve_values_and_reject_other_conversations(
    test_settings, workspace
):
    w = workspace
    result = w.results.save(
        columns=["region", "sales"],
        rows=[{"region": "East", "sales": 10}, {"region": "West", "sales": 25}],
        thread_id=w.thread,
        source_id="test",
    )
    payload = create_chart_tool(w.results, w.runs, source_id="test").func(
        spec=ChartRequest(
            result_id=result.result_id,
            chart_type="bar",
            title="Sales by region",
            x="region",
            y=["sales"],
        ),
        runtime=w.runtime("workspace-chart"),
    )
    services = Services(
        settings=replace(test_settings, enable_react_ui=False),
        storage=w.storage,
        results=w.results,
        runs=w.runs,
        conversations=w.conversations,
        analyses=w.analyses,
        reports=w.reports,
    )
    chart_id = payload["chart"]["chart_id"]
    other = services.conversations.create("test")
    with TestClient(create_app(services)) as client:
        response = client.get(f"/api/conversations/{w.thread}/charts/{chart_id}/figure")
        assert response.status_code == 200, response.text
        figure = response.json()
        assert figure["data"][0]["x"] == ["East", "West"]
        assert figure["layout"]["title"]["text"] == "Sales by region"
        assert (
            client.get(
                f"/api/conversations/{other}/charts/{chart_id}/figure"
            ).status_code
            == 404
        )


def test_workspace_serves_built_assets_only_when_enabled(test_settings, monkeypatch):
    root = test_settings.project_root
    dist = root / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>Analytics workspace</h1>")
    (dist / "assets" / "app-123.js").write_text("console.log('workspace')")
    (root / "private.txt").write_text("private")

    monkeypatch.delenv("ENABLE_REACT_UI", raising=False)
    disabled = replace(test_settings, enable_react_ui=Settings().enable_react_ui)
    with TestClient(create_app(Services(settings=disabled))) as client:
        assert client.get("/health").json()["react_ui_enabled"] is False
        for path in ("/", "/workspace", "/workspace/", "/workspace/assets/app-123.js"):
            assert client.get(path, follow_redirects=False).status_code == 404

    monkeypatch.setenv("ENABLE_REACT_UI", "true")
    enabled = replace(test_settings, enable_react_ui=Settings().enable_react_ui)
    with TestClient(create_app(Services(settings=enabled))) as client:
        assert client.get("/health").json()["react_ui_enabled"] is True
        assert (
            client.get("/", follow_redirects=False).headers["location"] == "/workspace/"
        )
        assert client.get("/workspace/").text == "<h1>Analytics workspace</h1>"
        assert client.get("/workspace/saved/dashboard").status_code == 200
        asset = client.get("/workspace/assets/app-123.js")
        assert "immutable" in asset.headers["cache-control"]
        assert client.get("/workspace/assets/missing.js").status_code == 404
        assert client.get("/workspace/%2e%2e/private.txt").status_code == 404
