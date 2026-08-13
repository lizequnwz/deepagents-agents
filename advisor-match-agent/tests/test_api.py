from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from advisor_match.advisor_matching.schemas import (
    AdvisorRecord,
    ColumnRef,
    CrdInputMapping,
    InputMapping,
)
from advisor_match.api import create_app
from advisor_match.mapping import (
    CrdMappingDecision,
    MappingDecision,
    MappingModelError,
)


class FakeMapper:
    async def propose_match(self, _profile):
        return MappingDecision(
            mapping=InputMapping(
                crd_number=ColumnRef(index=0, header="CRD"),
                full_name=ColumnRef(index=1, header="Name"),
                email=ColumnRef(index=2, header="Email"),
            )
        )

    async def propose_crd(self, profile):
        for sheet in profile["sheets"]:
            for candidate in sheet["header_candidates"]:
                for column in candidate["columns"]:
                    if column["header"] == "Advisor CRD":
                        return CrdMappingDecision(
                            mapping=CrdInputMapping(
                                sheet_name=sheet["name"],
                                header_row=candidate["row_number"],
                                crd_number=ColumnRef(
                                    index=column["index"],
                                    header=column["header"],
                                ),
                            )
                        )
        return CrdMappingDecision(missing_crd_column=True)


class FakeSource:
    source_kind = "snowflake"
    schema_version = "test"
    query_id = "query-1"

    def iter_records(self):
        yield AdvisorRecord(
            crd_number="1001",
            first_name="Avery",
            last_name="Stone",
            firm_name="Northstar Wealth",
            email="avery@example.com",
            city="Boston",
            state="MA",
        )


def _client(settings) -> TestClient:
    return TestClient(
        create_app(
            settings=settings,
            mapping_service=FakeMapper(),
            reference_source_factory=FakeSource,
        )
    )


def _map_match(client: TestClient, content: bytes) -> dict:
    response = client.post(
        "/advisor-match/mapping",
        files={"file": ("advisors.csv", content, "text/csv")},
    )
    assert response.status_code == 200
    return response.json()


def test_stateless_match_endpoints_return_exact_result_bundle(settings) -> None:
    client = _client(settings)
    content = b"CRD,Name,Email\n1001,Avery Stone,avery@example.com\n"
    analysis = _map_match(client, content)
    configuration = {
        "analyzed_source_sha256": analysis["source"]["sha256"],
        "mapping": analysis["decision"]["mapping"],
        "firm_resolution": "auto",
    }

    response = client.post(
        "/advisor-match/match",
        files={"file": ("advisors.csv", content, "text/csv")},
        data={"configuration": json.dumps(configuration)},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as bundle:
        assert set(bundle.namelist()) == {"advisor_matches.xlsx", "result.json"}
        assert bundle.read("advisor_matches.xlsx").startswith(b"PK")
        result = json.loads(bundle.read("result.json"))
    assert result["counts"] == {
        "matched": 1,
        "ambiguous_match": 0,
        "no_match": 0,
    }
    assert result["reference"]["query_id"] == "query-1"
    assert set(result) == {
        "source_sha256",
        "mapping",
        "mapping_fingerprint",
        "input_summary",
        "counts",
        "firm_resolution",
        "all_rows_firm",
        "firm_override_rows",
        "reference",
        "warnings",
        "policy_version",
        "generated_at",
    }


def test_match_rejects_file_different_from_analyzed_source(settings) -> None:
    client = _client(settings)
    content = b"CRD,Name,Email\n1001,Avery Stone,avery@example.com\n"
    analysis = _map_match(client, content)
    response = client.post(
        "/advisor-match/match",
        files={"file": ("advisors.csv", content + b"1002,Other,other@example.com\n")},
        data={
            "configuration": json.dumps(
                {
                    "analyzed_source_sha256": analysis["source"]["sha256"],
                    "mapping": analysis["decision"]["mapping"],
                }
            )
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SOURCE_CHANGED"


def test_match_returns_structured_firm_resolution_error(settings) -> None:
    client = _client(settings)
    content = b"CRD,Name,Email\n,Avery Stone,\n"
    analysis = _map_match(client, content)
    response = client.post(
        "/advisor-match/match",
        files={"file": ("advisors.csv", content)},
        data={
            "configuration": json.dumps(
                {
                    "analyzed_source_sha256": analysis["source"]["sha256"],
                    "mapping": analysis["decision"]["mapping"],
                }
            )
        },
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "FIRM_RESOLUTION_REQUIRED"
    assert body["details"]["reason"] == "missing_firm"


def test_profile_endpoints_are_file_driven_and_return_json_html(settings) -> None:
    client = _client(settings)
    content = b"Advisor CRD\n00123\n00123\nABC\n"
    mapping = client.post(
        "/advisor-profile/mapping",
        files={"file": ("crds.csv", content, "text/csv")},
    )
    assert mapping.status_code == 200
    analysis = mapping.json()

    generated = client.post(
        "/advisor-profile/generate",
        files={"file": ("crds.csv", content, "text/csv")},
        data={
            "configuration": json.dumps(
                {
                    "analyzed_source_sha256": analysis["source"]["sha256"],
                    "mapping": analysis["decision"]["mapping"],
                }
            )
        },
    )

    assert generated.status_code == 200
    result = generated.json()
    assert result["unique_crd_count"] == 2
    assert result["duplicate_crd_count"] == 1
    assert result["filename"] == "advisor_profile_report.html"
    assert result["html"].startswith("<!doctype html>")


def test_requests_can_move_between_fresh_app_instances(settings) -> None:
    expanded = settings.__class__(
        project_root=settings.project_root,
        model_name=settings.model_name,
        max_inspect_sheets=10,
        max_inspect_rows=10,
        max_inspect_columns=30,
    )
    first = _client(expanded)
    second = _client(expanded)
    third = _client(expanded)
    fourth = _client(expanded)
    content = b"CRD,Name,Email\n1001,Avery Stone,avery@example.com\n"
    analysis = _map_match(first, content)

    response = second.post(
        "/advisor-match/match",
        files={"file": ("advisors.csv", content)},
        data={
            "configuration": json.dumps(
                {
                    "analyzed_source_sha256": analysis["source"]["sha256"],
                    "mapping": analysis["decision"]["mapping"],
                }
            )
        },
    )

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as bundle:
        workbook = bundle.read("advisor_matches.xlsx")

    profile_mapping = third.post(
        "/advisor-profile/mapping",
        files={"file": ("advisor_matches.xlsx", workbook)},
    )
    assert profile_mapping.status_code == 200
    profile_analysis = profile_mapping.json()
    assert profile_analysis["decision"]["mapping"]["sheet_name"] == "Matched"

    generated = fourth.post(
        "/advisor-profile/generate",
        files={"file": ("advisor_matches.xlsx", workbook)},
        data={
            "configuration": json.dumps(
                {
                    "analyzed_source_sha256": profile_analysis["source"]["sha256"],
                    "mapping": profile_analysis["decision"]["mapping"],
                }
            )
        },
    )
    assert generated.status_code == 200
    assert generated.json()["unique_crd_count"] == 1


def test_successful_requests_create_no_runtime_storage(settings, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = _client(settings)
    content = b"CRD,Name,Email\n1001,Avery Stone,avery@example.com\n"
    analysis = _map_match(client, content)

    response = client.post(
        "/advisor-match/match",
        files={"file": ("advisors.csv", content)},
        data={
            "configuration": json.dumps(
                {
                    "analyzed_source_sha256": analysis["source"]["sha256"],
                    "mapping": analysis["decision"]["mapping"],
                }
            )
        },
    )

    assert response.status_code == 200
    assert not (tmp_path / ".data").exists()
    assert not (tmp_path / "workspace").exists()
    assert not list(tmp_path.glob("*.sqlite*"))


def test_health_is_minimal_and_has_no_state_claims(settings) -> None:
    body = _client(settings).get("/health").json()
    assert body == {"status": "ok", "service": "advisor-match", "version": "1.0.0"}


def test_openapi_documents_real_multipart_and_response_contracts(settings) -> None:
    schema = _client(settings).get("/openapi.json").json()
    paths = schema["paths"]

    def multipart_schema(path: str) -> dict:
        body = paths[path]["post"]["requestBody"]
        reference = body["content"]["multipart/form-data"]["schema"]["$ref"]
        assert body["required"] is True
        return schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]

    for path in ("/advisor-match/mapping", "/advisor-profile/mapping"):
        multipart = multipart_schema(path)
        assert multipart["required"] == ["file"]
        assert multipart["properties"]["file"]["contentMediaType"] == (
            "application/octet-stream"
        )

    for path in ("/advisor-match/match", "/advisor-profile/generate"):
        multipart = multipart_schema(path)
        assert multipart["required"] == ["file", "configuration"]
        assert multipart["properties"]["configuration"]["type"] == "string"
        assert multipart["properties"]["configuration"]["maxLength"] == 64 * 1024

    match_success = paths["/advisor-match/match"]["post"]["responses"]["200"]
    assert set(match_success["content"]) == {"application/zip"}
    assert match_success["content"]["application/zip"]["schema"] == {
        "type": "string",
        "format": "binary",
    }
    profile_success = paths["/advisor-profile/generate"]["post"]["responses"][
        "200"
    ]
    assert profile_success["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProfileGenerationResult"
    }
    mapping_profile = schema["components"]["schemas"]["MatchMappingResponse"][
        "properties"
    ]["profile"]
    assert mapping_profile == {"$ref": "#/components/schemas/UploadProfile"}


def test_native_fastapi_file_upload_is_accepted(settings) -> None:
    response = _client(settings).post(
        "/advisor-match/mapping",
        files={
            "file": (
                "advisors.csv",
                b"CRD,Name,Email\n1001,Avery Stone,avery@example.com\n",
            )
        },
    )

    assert response.status_code == 200


def test_native_fastapi_form_requires_configuration(settings) -> None:
    response = _client(settings).post(
        "/advisor-match/match",
        files={"file": ("advisors.csv", b"CRD\n1001\n", "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_upload_limit_is_enforced_when_reading_native_upload(settings) -> None:
    limited = settings.__class__(
        project_root=settings.project_root,
        model_name=settings.model_name,
        max_upload_mb=1,
    )

    response = _client(limited).post(
        "/advisor-match/mapping",
        files={"file": ("advisors.csv", b"x" * (1024 * 1024 + 1))},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


@pytest.mark.parametrize(
    ("filename", "content", "expected_status"),
    [
        ("advisors.txt", b"CRD\n1001\n", 415),
        ("advisors.xlsx", b"not-an-xlsx", 400),
    ],
)
def test_mapping_rejects_unsupported_or_corrupt_uploads(
    settings, filename, content, expected_status
) -> None:
    response = _client(settings).post(
        "/advisor-match/mapping",
        files={"file": (filename, content)},
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] in {
        "INVALID_UPLOAD",
        "UNSUPPORTED_UPLOAD_TYPE",
    }


def test_mapping_rejects_non_multipart_requests_as_invalid_contract(settings) -> None:
    response = _client(settings).post(
        "/advisor-match/mapping",
        content=b"CRD\n1001\n",
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_match_reports_reference_provider_unavailability_as_503(settings) -> None:
    def unavailable():
        raise RuntimeError("warehouse offline")

    client = TestClient(
        create_app(
            settings=settings,
            mapping_service=FakeMapper(),
            reference_source_factory=unavailable,
        )
    )
    content = b"CRD,Name,Email\n1001,Avery Stone,avery@example.com\n"
    analysis = _map_match(client, content)

    response = client.post(
        "/advisor-match/match",
        files={"file": ("advisors.csv", content)},
        data={
            "configuration": json.dumps(
                {
                    "analyzed_source_sha256": analysis["source"]["sha256"],
                    "mapping": analysis["decision"]["mapping"],
                }
            )
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REFERENCE_SOURCE_INVALID"


def test_mapping_model_failure_is_a_502(settings) -> None:
    class FailedMapper(FakeMapper):
        async def propose_match(self, _profile):
            raise MappingModelError("three structured attempts failed")

    client = TestClient(
        create_app(
            settings=settings,
            mapping_service=FailedMapper(),
            reference_source_factory=FakeSource,
        )
    )

    response = client.post(
        "/advisor-match/mapping",
        files={"file": ("advisors.csv", b"CRD\n1001\n")},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MAPPING_MODEL_FAILED"
