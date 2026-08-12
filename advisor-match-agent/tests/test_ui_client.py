from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from advisor_match.ui.api_client import APIError, AdvisorMatchAPIClient


def test_ui_client_extracts_match_summary_and_workbook(monkeypatch) -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("advisor_matches.xlsx", b"workbook")
        bundle.writestr("result.json", json.dumps({"counts": {"matched": 1}}))
    response = httpx.Response(200, content=output.getvalue())
    client = AdvisorMatchAPIClient("http://example.test")
    monkeypatch.setattr(client, "_upload", lambda *_args, **_kwargs: response)

    result, workbook = client.match_advisors(
        "input.csv", b"content", {"mapping": {}}
    )

    assert result["counts"]["matched"] == 1
    assert workbook == b"workbook"


def test_ui_client_exposes_structured_correction_details() -> None:
    response = httpx.Response(
        422,
        json={
            "error": {
                "code": "FIRM_RESOLUTION_REQUIRED",
                "message": "Firm resolution is required.",
                "details": {"reason": "missing_firm"},
            }
        },
    )

    with pytest.raises(APIError) as raised:
        AdvisorMatchAPIClient._raise_for_error(response)

    assert raised.value.code == "FIRM_RESOLUTION_REQUIRED"
    assert raised.value.details == {"reason": "missing_firm"}
