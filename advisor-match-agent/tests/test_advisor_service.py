from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from general_agent.advisor_matching.schemas import (
    CrdInputMapping,
    InputMapping,
    MatchRunResult,
)
from general_agent.advisor_matching.source import SyntheticAdvisorReferenceSource
from general_agent.advisor_repository import AdvisorRepository
from general_agent.advisor_service import AdvisorService, ServiceContext
from general_agent.runtime_store import RuntimeStore
from general_agent.workspace import Workspace


def test_service_validates_matches_and_publishes_workbook(settings) -> None:
    corp_id = "A123456"
    runtime = RuntimeStore()
    repository = AdvisorRepository(settings.advisor_repository_db)
    workspace = Workspace(settings.data_root)
    conversation = runtime.create_conversation(corp_id=corp_id)
    run_id, _ = runtime.create_run(conversation.conversation_id, "match", corp_id=corp_id)
    attachment, protected = workspace.upload(
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
        original_name="advisors.csv",
        content_type="text/csv",
        source=BytesIO(
            b"CRD_NUMBER,FIRST_NAME,LAST_NAME,EMAIL\n"
            b"99000001,Avery,Stone,avery.stone@example.com\n"
            b",Mystery,Person,mystery.person@example.com\n"
        ),
        max_bytes=1024 * 1024,
    )
    repository.add_attachment(
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
        run_id=run_id,
        attachment=attachment,
        protected_path=protected,
    )
    runtime.add_attachment(run_id, attachment, corp_id=corp_id)
    service = AdvisorService(
        settings,
        workspace,
        repository,
        runtime,
        SyntheticAdvisorReferenceSource(
            Path(__file__).parents[1]
            / "general_agent/advisor_matching/data/master_advisors.csv"
        ),
    )
    context = ServiceContext(corp_id, conversation.conversation_id, run_id, "match")
    mapping = InputMapping.model_validate(
        {
            "crd_number": {"columns": [{"index": 0, "header": "CRD_NUMBER"}]},
            "first_name": {"columns": [{"index": 1, "header": "FIRST_NAME"}]},
            "last_name": {"columns": [{"index": 2, "header": "LAST_NAME"}]},
            "email": {"columns": [{"index": 3, "header": "EMAIL"}]},
        }
    )
    validation = service.validate(context, attachment.attachment_id, mapping)
    result = service.create_match(context, validation)
    assert isinstance(result, MatchRunResult)
    assert result.counts.matched == 1
    assert result.counts.no_match == 1
    path, name = repository.artifact_path(result.output_artifact_id, corp_id=corp_id)
    assert path.is_file()
    assert name == "advisor_matches.xlsx"
    session = repository.get_advisor_match_session(
        result.match_session_id,
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
    )
    assert session["status"] == "Matching Complete"
    assert session["revision"] == 1
    profile = service.create_profile_report_from_match(
        context, result.match_session_id
    )
    assert profile.source_kind == "match_session"
    assert profile.unique_crd_count == 1
    report = repository.get_profile_report(
        profile.profile_report_id,
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
    )
    assert report["crd_numbers"] == ["99000001"]
    report_path, report_name = repository.artifact_path(
        profile.output_artifact_id, corp_id=corp_id
    )
    assert report_name == "advisor_profile_report.html"
    assert report_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    with pytest.raises(ValueError, match="current chat"):
        service.create_profile_report_from_match(
            ServiceContext("B654321", conversation.conversation_id, run_id, "profile"),
            result.match_session_id,
        )
    with pytest.raises(ValueError, match="current chat"):
        service.create_profile_report_from_match(
            ServiceContext(corp_id, "another-conversation", run_id, "profile"),
            result.match_session_id,
        )
    repository.close()


def test_service_generates_profile_report_directly_from_crd_upload(
    settings, monkeypatch
) -> None:
    corp_id = "A123456"
    runtime = RuntimeStore()
    repository = AdvisorRepository(settings.advisor_repository_db)
    workspace = Workspace(settings.data_root)
    conversation = runtime.create_conversation(corp_id=corp_id)
    run_id, _ = runtime.create_run(
        conversation.conversation_id, "profile", corp_id=corp_id
    )
    attachment, protected = workspace.upload(
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
        original_name="profile-crds.csv",
        content_type="text/csv",
        source=BytesIO(
            b"CRD,NOTE\n"
            b" 00123 ,first\n"
            b"FSA_ID:111,second\n"
            b"00123,duplicate\n"
            b",missing\n"
        ),
        max_bytes=1024 * 1024,
    )
    repository.add_attachment(
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
        run_id=run_id,
        attachment=attachment,
        protected_path=protected,
    )
    runtime.add_attachment(run_id, attachment, corp_id=corp_id)
    service = AdvisorService(
        settings,
        workspace,
        repository,
        runtime,
        SyntheticAdvisorReferenceSource(
            Path(__file__).parents[1]
            / "general_agent/advisor_matching/data/master_advisors.csv"
        ),
    )
    context = ServiceContext(
        corp_id, conversation.conversation_id, run_id, "profile"
    )
    mapping = CrdInputMapping.model_validate(
        {"crd_number": {"columns": [{"index": 0, "header": "CRD"}]}}
    )

    validation = service.validate_profile_input(
        context, attachment.attachment_id, mapping
    )
    assert validation.unique_crd_count == 2
    assert validation.blank_crd_count == 1
    assert validation.duplicate_crd_count == 1

    result = service.create_profile_report_from_upload(context, validation)
    report = repository.get_profile_report(
        result.profile_report_id,
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
    )
    assert report["source_kind"] == "attachment"
    assert report["crd_numbers"] == ["00123", "FSA_ID:111"]
    assert report["blank_crd_count"] == 1
    assert report["duplicate_crd_count"] == 1
    assert runtime.get_conversation(
        conversation.conversation_id, corp_id=corp_id
    ).turns[0].artifacts[0].artifact_kind == "advisor_profile_report"

    published = set(settings.data_root.rglob("advisor_profile_report.html"))

    def fail_report_insert(**_kwargs) -> None:
        raise RuntimeError("simulated report persistence failure")

    monkeypatch.setattr(repository, "add_profile_report", fail_report_insert)
    with pytest.raises(RuntimeError, match="simulated report persistence failure"):
        service.create_profile_report_from_upload(context, validation)
    assert set(settings.data_root.rglob("advisor_profile_report.html")) == published
    assert not list(settings.data_root.rglob("*.building.html"))
    repository.close()


def test_profile_report_rejects_attachment_changed_after_validation(settings) -> None:
    corp_id = "A123456"
    runtime = RuntimeStore()
    repository = AdvisorRepository(settings.advisor_repository_db)
    workspace = Workspace(settings.data_root)
    conversation = runtime.create_conversation(corp_id=corp_id)
    run_id, _ = runtime.create_run(
        conversation.conversation_id, "profile", corp_id=corp_id
    )
    attachment, protected = workspace.upload(
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
        original_name="profile-crds.csv",
        content_type="text/csv",
        source=BytesIO(b"CRD\n00123\n"),
        max_bytes=1024 * 1024,
    )
    repository.add_attachment(
        corp_id=corp_id,
        conversation_id=conversation.conversation_id,
        run_id=run_id,
        attachment=attachment,
        protected_path=protected,
    )
    runtime.add_attachment(run_id, attachment, corp_id=corp_id)
    service = AdvisorService(
        settings,
        workspace,
        repository,
        runtime,
        SyntheticAdvisorReferenceSource(
            Path(__file__).parents[1]
            / "general_agent/advisor_matching/data/master_advisors.csv"
        ),
    )
    context = ServiceContext(
        corp_id, conversation.conversation_id, run_id, "profile"
    )
    mapping = CrdInputMapping.model_validate(
        {"crd_number": {"columns": [{"index": 0, "header": "CRD"}]}}
    )
    validation = service.validate_profile_input(
        context, attachment.attachment_id, mapping
    )
    protected.write_bytes(b"CRD\nCHANGED\n")

    with pytest.raises(ValueError, match="integrity validation"):
        service.create_profile_report_from_upload(context, validation)
    assert not list(settings.data_root.rglob("advisor_profile_report.html"))
    repository.close()
