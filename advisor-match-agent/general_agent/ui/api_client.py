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
            headers={"X-Corp-ID": corp_id},
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise APIError(f"Cannot reach the Advisor Match Agent API: {exc}") from exc
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
        *,
        requested_workflow: str | None = None,
        source_match_session_id: str | None = None,
    ) -> dict[str, Any]:
        files = [
            (
                "files",
                (upload.name, upload.getvalue(), getattr(upload, "type", None) or "application/octet-stream"),
            )
            for upload in uploads
        ]
        data = {"text": text}
        if requested_workflow is not None:
            data["requested_workflow"] = requested_workflow
        if source_match_session_id is not None:
            data["source_match_session_id"] = source_match_session_id
        return self._request(
            "POST",
            f"/conversations/{conversation_id}/messages",
            data=data,
            files=files,
            timeout=120.0,
        )

    def run(self, run_id: str, after_event_id: int = 0) -> dict[str, Any]:
        return self._request("GET", f"/runs/{run_id}", params={"after_event_id": after_event_id})

    def stop_run(self, run_id: str) -> dict[str, Any]:
        return self._request("POST", f"/runs/{run_id}/stop")

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
