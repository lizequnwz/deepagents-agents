"""Small typed-by-convention HTTP client for the Streamlit application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from data_analytics_agent.schemas import API_CONTRACT_VERSION


def api_contract_error(health: dict[str, Any]) -> str | None:
    """Explain when Streamlit and FastAPI were loaded from different code."""

    actual = health.get("api_contract_version")
    if actual == API_CONTRACT_VERSION:
        return None
    displayed = "missing" if actual is None else repr(actual)
    return (
        "The API process is running an incompatible code version "
        f"(contract {displayed}; this UI expects "
        f"{API_CONTRACT_VERSION}). Stop the current services and restart "
        "`./scripts/start.sh` before submitting another request."
    )


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

    def get_data_sources(self) -> dict[str, Any]:
        return self.request("GET", "/api/data-sources", timeout=5)

    def create_conversation(self, source_id: str) -> str:
        response = self.request(
            "POST",
            "/api/conversations",
            json={"source_id": source_id},
        )
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

    def get_result(
        self,
        result_id: str,
        *,
        page_size: int = 1_000,
    ) -> dict[str, Any]:
        """Fetch every stored result page up to the backend retrieval cap."""

        bounded_page_size = min(max(page_size, 1), 10_000)
        offset = 0
        combined: dict[str, Any] | None = None
        rows: list[dict[str, Any]] = []
        while True:
            page = self.request(
                "GET",
                f"/api/results/{result_id}?offset={offset}"
                f"&limit={bounded_page_size}",
            )
            if combined is None:
                combined = dict(page)
            page_rows = list(page.get("rows") or [])
            rows.extend(page_rows)
            offset += len(page_rows)
            if not page_rows or offset >= int(page["row_count"]):
                break
        assert combined is not None
        combined["rows"] = rows
        combined["offset"] = 0
        combined["limit"] = len(rows)
        return combined

    def get_report(self, report_id: str) -> dict[str, Any]:
        """Fetch the exact stored HTML and immutable report metadata."""

        return self.request("GET", f"/api/reports/{report_id}", timeout=30)

    def report_view_url(self, report_id: str) -> str:
        """Return the browser-facing full-page report URL."""

        return f"{self.base_url.rstrip('/')}/api/reports/{report_id}/view"
