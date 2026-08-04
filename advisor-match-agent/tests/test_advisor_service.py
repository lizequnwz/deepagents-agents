from __future__ import annotations

from io import BytesIO
from pathlib import Path

from general_agent.advisor_matching.schemas import InputMapping, MatchRunResult
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

    page = service.list_results(
        context, result.match_session_id, status="no_match", limit=10
    )
    proposal = service.propose_crd(
        context,
        result.match_session_id,
        page["items"][0]["review_item_id"],
        "99000001",
    )
    service.cancel_proposal(
        context, proposal["proposal_id"], result.match_session_id
    )
    stored = repository.get_advisor_override_proposal(
        proposal["proposal_id"], corp_id=corp_id
    )
    assert stored["status"] == "Cancelled"
    repository.close()
