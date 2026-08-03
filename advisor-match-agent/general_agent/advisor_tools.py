"""Thin LangChain tool facade for the advisor-match workflow."""

from __future__ import annotations

from langchain_core.tools import BaseTool

from general_agent.advisor_backend import AdvisorWorkspaceBackend
from general_agent.advisor_matching.source import AdvisorReferenceSource
from general_agent.advisor_workflow import AdvisorWorkflow
from general_agent.config import Settings
from general_agent.store import Store
from general_agent.workspace import Workspace


def build_advisor_tools(
    *,
    settings: Settings,
    workspace: Workspace,
    backend: AdvisorWorkspaceBackend,
    store: Store,
    advisor_source: AdvisorReferenceSource,
) -> list[BaseTool]:
    """Bind the workflow service to the narrow model-facing tool surface."""

    return AdvisorWorkflow(
        settings=settings,
        workspace=workspace,
        backend=backend,
        store=store,
        advisor_source=advisor_source,
    ).tools()
