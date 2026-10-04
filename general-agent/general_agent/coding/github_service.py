"""User-approved GitHub connection and immutable delivery orchestration."""

import asyncio
import contextlib

from general_agent.coding.github import GitHubConnector, GitHubDelivery
from general_agent.coding.store import CodingConflict


class GitHubService:
    def __init__(self, coding, *, connector_factory=GitHubConnector):
        self.coding = coding
        self.store = coding.store
        self.connector_factory = connector_factory

    def connector(self, corp_id: str, project: dict):
        connection = project.get("github")
        token = self.coding.settings.github_tokens.get(corp_id)
        if not connection or not token:
            raise CodingConflict("Configure this corporation's GitHub token and explicitly connect a repository first.")
        return self.connector_factory(corp_id, token.get_secret_value(), connection["owner"], connection["repository"])

    async def status(self, corp_id: str, project_id: str):
        project = self.store.project(corp_id, project_id)
        return {"configured": corp_id in self.coding.settings.github_tokens, "connection": project.get("github")}

    async def read(self, corp_id: str, project_id: str, operation: str, **arguments):
        if operation not in {"repository", "issues", "issue", "pulls", "pull"}:
            raise ValueError("Unsupported GitHub read operation.")
        project = self.store.project(corp_id, project_id)
        connector = self.connector(corp_id, project)
        try:
            identity = await connector.repository(corp_id)
            if identity["id"] != project["github"]["identity"]["id"]:
                raise CodingConflict("The connected GitHub repository identity changed; review its connection again.")
            return identity if operation == "repository" else await getattr(connector, operation)(corp_id, **arguments)
        finally:
            await connector.close()

    async def connect(self, corp_id: str, project_id: str, owner: str, repository: str):
        project = self.store.project(corp_id, project_id)
        token = self.coding.settings.github_tokens.get(corp_id)
        if token is None:
            raise CodingConflict("Configure GITHUB_TOKENS_JSON for this corporation on the application server.")
        if self.store.project_has_pending(corp_id, project_id):
            raise CodingConflict("Finish or stop this project's pending tasks before changing its connection.")
        connector = self.connector_factory(corp_id, token.get_secret_value(), owner, repository)
        try:
            identity = await connector.repository(corp_id)
            if self.store.project_has_pending(corp_id, project_id):
                raise CodingConflict("A task started while validating the connection; try again after it finishes.")
            project["github"] = {"owner": owner, "repository": repository, "identity": identity}
            self.store.save_project(corp_id, project)
            return project["github"]
        finally:
            await connector.close()

    @contextlib.asynccontextmanager
    async def _delivery(self, corp_id: str, session_id: str):
        async with self.coding._lock(session_id):
            session = self.store.session(corp_id, session_id)
            if self.store.has_pending(corp_id, session_id):
                raise CodingConflict("Finish or stop pending tasks before reviewing or publishing delivery.")
            await self.coding._recover_session(corp_id, session)
            connector = self.connector(corp_id, self.store.project(corp_id, session["project_id"]))
            try:
                identity = await connector.repository(corp_id)
                project = self.store.project(corp_id, session["project_id"])
                if identity["id"] != project["github"]["identity"]["id"]:
                    raise CodingConflict("The connected GitHub repository identity changed.")
                current = await asyncio.to_thread(self.coding.changes.capture, corp_id, session_id,
                    self.coding.projects.repository(corp_id, session_id), tracked_paths=tuple(session["tracked_paths"]))
                yield GitHubDelivery(connector, self.store.record_delivery, self.coding.changes.blob), current
            finally:
                await connector.close()

    async def prepare(self, corp_id: str, change_id: str, title: str, body: str = "", base: str | None = None):
        change = self.store.change(corp_id, change_id)
        if change.get("review_status") == "rejected":
            raise CodingConflict("A rejected proposal cannot be delivered.")
        async with self._delivery(corp_id, change["session_id"]) as (delivery, current):
            if current["revision"] != change["after_revision"]:
                raise CodingConflict("The source changed after this proposal; review the latest change first.")
            attempt = self.coding._evaluate_attempt(corp_id, self.store.attempt(corp_id, change["attempt_id"]), current)
            return await delivery.prepare(corp_id, change["session_id"], change, attempt, title, body, base=base)

    async def publish(self, corp_id: str, delivery_id: str, expected_digest: str):
        record = self.store.delivery(corp_id, delivery_id)
        async with self._delivery(corp_id, record["session_id"]) as (delivery, current):
            change = self.store.change(corp_id, record["proposal"]["change_id"])
            if change.get("review_status") == "rejected":
                raise CodingConflict("The reviewed change was rejected.")
            attempt = self.coding._evaluate_attempt(corp_id, self.store.attempt(corp_id, change["attempt_id"]), current)
            evidence = delivery._verification(attempt, current["revision"])
            if evidence != record["proposal"]["verification"]:
                raise CodingConflict("Verification changed after delivery review; prepare a new proposal.")
            return await delivery.publish(corp_id, record, expected_digest=expected_digest,
                                          current_source_revision=current["revision"])
