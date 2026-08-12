"""Synchronous client for the stateless Advisor Match API."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import httpx


class APIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details


class AdvisorMatchAPIClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=120.0)

    def health(self) -> dict[str, Any]:
        return self._json("GET", "/health")

    def map_advisors(
        self, filename: str, content: bytes, content_type: str | None = None
    ) -> dict[str, Any]:
        return self._upload_json(
            "/advisor-match/mapping", filename, content, content_type
        )

    def match_advisors(
        self,
        filename: str,
        content: bytes,
        configuration: dict[str, Any],
        content_type: str | None = None,
    ) -> tuple[dict[str, Any], bytes]:
        response = self._upload(
            "/advisor-match/match",
            filename,
            content,
            content_type,
            configuration=configuration,
            timeout=900.0,
        )
        try:
            with ZipFile(BytesIO(response.content)) as bundle:
                if set(bundle.namelist()) != {"advisor_matches.xlsx", "result.json"}:
                    raise ValueError("unexpected bundle entries")
                result = json.loads(bundle.read("result.json"))
                workbook = bundle.read("advisor_matches.xlsx")
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise APIError("The match API returned an invalid result bundle.") from exc
        return result, workbook

    def map_profile(
        self, filename: str, content: bytes, content_type: str | None = None
    ) -> dict[str, Any]:
        return self._upload_json(
            "/advisor-profile/mapping", filename, content, content_type
        )

    def generate_profile(
        self,
        filename: str,
        content: bytes,
        configuration: dict[str, Any],
        content_type: str | None = None,
    ) -> dict[str, Any]:
        return self._upload_json(
            "/advisor-profile/generate",
            filename,
            content,
            content_type,
            configuration=configuration,
            timeout=900.0,
        )

    def _upload_json(
        self,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None,
        *,
        configuration: dict[str, Any] | None = None,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        return self._json_response(
            self._upload(
                path,
                filename,
                content,
                content_type,
                configuration=configuration,
                timeout=timeout,
            )
        )

    def _upload(
        self,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None,
        *,
        configuration: dict[str, Any] | None = None,
        timeout: float,
    ) -> httpx.Response:
        data = (
            {"configuration": json.dumps(configuration)}
            if configuration is not None
            else None
        )
        try:
            response = self._client.post(
                path,
                files={
                    "file": (
                        filename,
                        content,
                        content_type or "application/octet-stream",
                    )
                },
                data=data,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise APIError(f"Cannot reach the Advisor Match API: {exc}") from exc
        self._raise_for_error(response)
        return response

    def _json(self, method: str, path: str) -> dict[str, Any]:
        try:
            response = self._client.request(method, path)
        except httpx.HTTPError as exc:
            raise APIError(f"Cannot reach the Advisor Match API: {exc}") from exc
        self._raise_for_error(response)
        return self._json_response(response)

    def _json_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise APIError("The API returned invalid JSON.") from exc
        if not isinstance(value, dict):
            raise APIError("The API returned an unexpected JSON value.")
        return value

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if not response.is_error:
            return
        try:
            body = response.json().get("error") or {}
        except (ValueError, AttributeError):
            body = {}
        raise APIError(
            str(body.get("message") or response.reason_phrase),
            status_code=response.status_code,
            code=body.get("code"),
            details=body.get("details"),
        )
