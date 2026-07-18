"""Small typed-by-convention HTTP client for the Streamlit application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class APIError(RuntimeError):
    """A user-presentable API failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AgentAPIClient:
    base_url: str

    def request(
        self,
        method: str,
        path: str,
        *,
        timeout: float = 20.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                timeout=timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                body = exc.response.json()
                detail = body.get("detail", exc.response.text)
            except ValueError:
                detail = exc.response.text
            raise APIError(
                str(detail), status_code=exc.response.status_code
            ) from exc
        except httpx.HTTPError as exc:
            raise APIError(
                f"Cannot reach the API at {self.base_url}. "
                "Start the local services and try again."
            ) from exc

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/health", timeout=5)

    def create_conversation(self) -> str:
        response = self.request("POST", "/api/conversations")
        return str(response["thread_id"])

    def get_conversation(self, thread_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/conversations/{thread_id}")

    def send_message(self, thread_id: str, message: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/api/conversations/{thread_id}/messages",
            json={"message": message},
        )

    def get_run(
        self, run_id: str, *, after_event_id: int = 0
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/api/runs/{run_id}?after_event_id={after_event_id}",
            timeout=10,
        )

    def submit_decision(
        self, run_id: str, decision: dict[str, Any]
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/api/runs/{run_id}/decisions",
            json={"decisions": [decision]},
        )

    def get_result(self, result_id: str) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/api/results/{result_id}?offset=0&limit=500",
        )
