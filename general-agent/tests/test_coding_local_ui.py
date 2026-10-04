"""Local workbench readiness and dependency status without running services."""

from tests.test_coding_ui import WorkbenchClient, button, page


class LocalWorkbenchClient(WorkbenchClient):
    def __init__(self, *, runtime_id="local:toolchain", prepared_runtime=None):
        super().__init__()
        self.runtime_id = runtime_id
        self.prepared_runtime = prepared_runtime

    def coding_readiness(self):
        return {"ready": True, "errors": [], "runtime": "local",
                "runtime_id": self.runtime_id, "browser": False,
                "typescript_version": None}

    def coding_setup(self, sid):
        if self.prepared_runtime is None:
            return super().coding_setup(sid)
        return {"python": {"ready": True, "files": ["requirements.txt"],
                "manifest_identity": "f" * 64,
                "prepared": {"status": "ready", "manifest_identity": "f" * 64,
                             "runtime_id": self.prepared_runtime}}}


def captions(app):
    return "\n".join(element.value for element in app.caption)


def test_local_implementation_does_not_require_optional_tools(monkeypatch):
    client = LocalWorkbenchClient()
    app = page(monkeypatch, client)
    assert not app.exception
    app.segmented_control[0].set_value("implement").run()
    assert not app.exception
    assert not button(app, "Start task").disabled
    next(widget for widget in app.text_area if widget.label == "Task").set_value("Fix the bug")
    button(app, "Start task").click().run()
    assert not app.exception
    assert client.submitted == ("s1", "Fix the bug", "implement")
    copy = captions(app)
    assert "host permissions" in copy and "not a sandbox" in copy
    assert "JavaScript/TypeScript navigation · not configured" in copy
    assert "Browser checks · not configured" in copy
    assert not app.warning


def test_prepared_dependencies_use_current_runtime_identity(monkeypatch):
    app = page(monkeypatch, LocalWorkbenchClient(prepared_runtime="local:toolchain"))
    assert not app.exception
    assert "Python · prepared" in captions(app)


def test_toolchain_change_marks_prepared_dependencies_unavailable(monkeypatch):
    client = LocalWorkbenchClient(runtime_id="local:changed", prepared_runtime="local:toolchain")
    app = page(monkeypatch, client)
    assert not app.exception
    assert "Python · not prepared" in captions(app)
    button(app, "Prepare python dependencies").click().run()
    assert not app.exception
    assert client.prepared == ("s1", "python", "f" * 64)


def test_explicit_docker_runtime_has_its_own_trust_copy(monkeypatch):
    class DockerWorkbenchClient(LocalWorkbenchClient):
        def coding_readiness(self):
            return {"ready": True, "errors": [], "runtime": "docker",
                    "runtime_id": "sha256:" + "a" * 64, "browser": True,
                    "typescript_version": "5.9.3"}

    app = page(monkeypatch, DockerWorkbenchClient())
    assert not app.exception
    copy = captions(app)
    assert "Docker execution" in copy
    assert "Project commands run offline in the coding container" in copy
    assert "Local execution" not in copy
