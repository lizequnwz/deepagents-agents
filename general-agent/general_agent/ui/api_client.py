"""Synchronous HTTP client used only by the Streamlit frontend."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class APIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AgentAPIClient:
    def __init__(self, base_url: str, corp_id: str = "A123456") -> None:
        self.base_url = base_url.rstrip("/")
        self.corp_id = corp_id
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=30.0,
            trust_env=False,
            headers={"X-Corp-ID": corp_id},
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise APIError(f"Cannot reach the General Agent API: {exc}") from exc
        if response.is_error:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = response.text
            raise APIError(str(detail or response.reason_phrase), status_code=response.status_code)
        if response.status_code == 204:
            return None
        return response.json()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def coding_readiness(self) -> dict[str, Any]:
        return self._request("GET", "/coding/readiness")

    def projects(self) -> list[dict[str, Any]]:
        return self._request("GET", "/projects")

    def register_project(self, root: str, name: str, checks: dict[str, str],
                         documentation_domains: list[str] | None = None) -> dict[str, Any]:
        return self._request("POST", "/projects", json={"root": root, "name": name, "checks": checks,
                                                        "documentation_domains": documentation_domains or []})

    def coding_sessions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/sessions")

    def coding_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{quote(session_id, safe='')}")

    def create_coding_session(self, project_id: str) -> dict[str, Any]:
        return self._request("POST", f"/projects/{quote(project_id, safe='')}/sessions")

    def coding_setup(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{quote(session_id, safe='')}/setup")

    def prepare_coding_setup(self, session_id: str, kind: str, manifest_identity: str) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{quote(session_id, safe='')}/setup",
                             json={"kind": kind, "manifest_identity": manifest_identity})

    def coding_decision_status(self, decision_id: str) -> dict[str, Any]:
        return self._request("GET", f"/decisions/{quote(decision_id, safe='')}")

    def answer_coding_input(self, decision_id: str, message: str) -> dict[str, Any]:
        return self._request("POST", f"/decisions/{quote(decision_id, safe='')}/input", json={"message": message})

    def coding_task(self, session_id: str, message: str, mode: str, **links: Any) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{quote(session_id, safe='')}/tasks",
                             json={"message": message, "mode": mode, **links})

    def coding_run(self, run_id: str, after: int = 0) -> dict[str, Any]:
        return self._request("GET", f"/coding/runs/{quote(run_id, safe='')}", params={"after": after})

    def stop_coding_run(self, run_id: str) -> dict[str, Any]:
        return self._request("POST", f"/coding/runs/{quote(run_id, safe='')}/stop")

    def coding_processes(self, run_id: str):
        return self._request("GET", f"/coding/runs/{quote(run_id, safe='')}/processes")

    def coding_process_output(self, run_id: str, process_id: str, cursor: int = 0):
        return self._request("GET", f"/coding/runs/{quote(run_id, safe='')}/processes/{quote(process_id, safe='')}", params={"cursor": cursor})

    def stop_coding_process(self, run_id: str, process_id: str):
        return self._request("POST", f"/coding/runs/{quote(run_id, safe='')}/processes/{quote(process_id, safe='')}/stop")

    def coding_browser_image(self, run_id: str, check_id: str) -> bytes:
        response = self._client.get(f"/coding/runs/{quote(run_id, safe='')}/browser/{quote(check_id, safe='')}/image")
        if response.is_error:
            raise APIError("Screenshot is unavailable.", status_code=response.status_code)
        return response.content

    def steer_coding_run(self, run_id: str, message: str) -> dict[str, Any]:
        return self._request("POST", f"/coding/runs/{quote(run_id, safe='')}/steer", json={"message": message})

    def coding_diff(self, change_id: str) -> dict[str, Any]:
        return self._request("GET", f"/changes/{quote(change_id, safe='')}/diff")

    def coding_github_status(self, project_id: str):
        return self._request("GET", f"/projects/{quote(project_id, safe='')}/github")

    def coding_snowflake_status(self, project_id: str):
        return self._request("GET", f"/projects/{quote(project_id, safe='')}/snowflake")

    def enable_coding_snowflake(self, project_id: str, enabled: bool, digest: str | None):
        return self._request("POST", f"/projects/{quote(project_id, safe='')}/snowflake", json={"enabled": enabled, "expected_digest": digest})

    def connect_coding_github(self, project_id: str, owner: str, repository: str):
        return self._request("POST", f"/projects/{quote(project_id, safe='')}/github", json={"owner": owner, "repository": repository})

    def prepare_coding_delivery(self, change_id: str, title: str, body: str, base: str | None):
        return self._request("POST", f"/changes/{quote(change_id, safe='')}/deliveries", json={"title": title, "body": body, "base": base})

    def coding_deliveries(self, session_id: str):
        return self._request("GET", f"/sessions/{quote(session_id, safe='')}/deliveries")

    def publish_coding_delivery(self, delivery_id: str, digest: str):
        return self._request("POST", f"/deliveries/{quote(delivery_id, safe='')}/publish", json={"expected_digest": digest})

    def apply_coding_change(self, change_id: str, revision: str, paths: list[str]) -> dict[str, Any]:
        return self._request("POST", f"/changes/{quote(change_id, safe='')}/apply",
                             json={"expected_revision": revision, "paths": paths})

    def revert_coding_change(self, change_id: str, revision: str) -> dict[str, Any]:
        return self._request("POST", f"/changes/{quote(change_id, safe='')}/revert",
                             json={"expected_revision": revision})

    def reject_coding_change(self, change_id: str, revision: str) -> dict[str, Any]:
        return self._request("POST", f"/changes/{quote(change_id, safe='')}/reject",
                             json={"expected_revision": revision})

    def coding_decision(self, decision_id: str, response: str) -> dict[str, Any]:
        return self._request("POST", f"/decisions/{quote(decision_id, safe='')}/respond", json={"response": response})

    def create_conversation(self, title: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/conversations", json={"title": title})

    def conversations(self) -> list[dict[str, Any]]:
        return self._request("GET", "/conversations")

    def conversation(self, conversation_id: str) -> dict[str, Any]:
        return self._request("GET", f"/conversations/{conversation_id}")

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        self._request("PATCH", f"/conversations/{conversation_id}", json={"title": title})

    def delete_conversation(self, conversation_id: str) -> None:
        self._request("DELETE", f"/conversations/{conversation_id}")

    def send_message(
        self,
        conversation_id: str,
        text: str,
        uploads: list[Any],
    ) -> dict[str, Any]:
        files = [
            (
                "files",
                (upload.name, upload.getvalue(), getattr(upload, "type", None) or "application/octet-stream"),
            )
            for upload in uploads
        ]
        return self._request(
            "POST",
            f"/conversations/{conversation_id}/messages",
            data={"text": text},
            files=files,
            timeout=120.0,
        )

    def run(self, run_id: str, after_event_id: int = 0) -> dict[str, Any]:
        return self._request("GET", f"/runs/{run_id}", params={"after_event_id": after_event_id})

    def stop_run(self, run_id: str) -> dict[str, Any]:
        return self._request("POST", f"/runs/{run_id}/stop")

    def workspace(
        self,
        path: str = "",
        *,
        scope: str = "shared",
        conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/workspace",
            params={
                "path": path,
                "scope": scope,
                "conversation_id": conversation_id,
            },
        )

    def upload_workspace(
        self,
        uploads: list[Any],
        *,
        scope: str = "shared",
        conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        files = [
            (
                "files",
                (upload.name, upload.getvalue(), getattr(upload, "type", None) or "application/octet-stream"),
            )
            for upload in uploads
        ]
        return self._request(
            "POST",
            "/workspace/uploads",
            params={"scope": scope, "conversation_id": conversation_id},
            files=files,
            timeout=120.0,
        )

    def promote_workspace(self, path: str, conversation_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/workspace/promote",
            params={"path": path, "conversation_id": conversation_id},
        )

    def cleanup_chat_workspace(self, conversation_id: str) -> None:
        self._request("DELETE", f"/workspace/chats/{quote(conversation_id)}")

    def inspect_workspace(self, path: str) -> dict[str, Any]:
        return self._request("GET", "/workspace/inspect", params={"path": path})

    def rename_workspace(self, path: str, new_name: str) -> str:
        result = self._request("PATCH", "/workspace", params={"path": path}, json={"new_name": new_name})
        return result["path"]

    def delete_workspace(self, path: str) -> None:
        self._request("DELETE", "/workspace", params={"path": path})

    def download_workspace(self, path: str) -> bytes:
        return self._download("/workspace/download", params={"path": path})

    def download_attachment(self, attachment_id: str) -> bytes:
        return self._download(f"/attachments/{quote(attachment_id)}/download")

    def download_artifact(self, artifact_id: str) -> bytes:
        return self._download(f"/artifacts/{quote(artifact_id)}/download")

    def _download(self, path: str, **kwargs: Any) -> bytes:
        try:
            response = self._client.get(path, timeout=120.0, **kwargs)
        except httpx.HTTPError as exc:
            raise APIError(f"Download failed: {exc}") from exc
        if response.is_error:
            raise APIError(response.text or response.reason_phrase, status_code=response.status_code)
        return response.content
