"""Scoped GitHub reads and single-use, journaled remote draft delivery.

No local Git subprocess, credential environment, or mutable source reads are
used. The application supplies frozen change records and immutable blob bytes.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import re
import time
from copy import deepcopy
from typing import Any, Callable
from urllib.parse import quote

import httpx

from general_agent.coding.http import tls_context
from general_agent.coding.source import source_revision, validate_source_path
from general_agent.coding.store import CodingConflict, identifier, now
from general_agent.workspace import validate_corp_id

_SHA = re.compile(r"[a-f0-9]{40}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_ID = re.compile(r"[a-f0-9]{32}\Z")
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_BRANCH = re.compile(r"codex/coding-[a-f0-9]{32}\Z")
_MAX_RESPONSE = 2 * 1024 * 1024
_MAX_FILES = 100
_MAX_BYTES = 5 * 1024 * 1024
_MAX_DIFF = 200_000


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha(value: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise GitHubError("GitHub returned an invalid Git object identifier.")
    return value


def _branch(value: str) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 200 or value == "@"
            or any(ord(char) < 33 or ord(char) == 127 or char in "~^:?*[\\" for char in value)
            or any(part.startswith(".") or part.endswith(".lock") or not part for part in value.split("/"))
            or ".." in value or "@{" in value or value.endswith(".")):
        raise ValueError("A valid, bounded Git branch name is required.")
    return value


def _git_mode(mode: int) -> str:
    return "100755" if mode & 0o111 else "100644"


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class GitHubError(ValueError):
    """Sanitized operation failure; uncertainty must never trigger a retry."""

    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


class GitHubConnector:
    """One corporation and one explicitly approved github.com repository."""

    def __init__(self, corp_id: str, token: str, owner: str, repo: str, *, transport=None):
        self.corp_id = validate_corp_id(corp_id)
        if not _OWNER.fullmatch(owner) or not _REPO.fullmatch(repo) or repo in {".", ".."}:
            raise ValueError("An explicit GitHub owner and repository name are required.")
        if not isinstance(token, str) or not token or len(token) > 1024 or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise ValueError("A bounded GitHub token without whitespace is required.")
        self.owner, self.repo = owner, repo
        self._token = token
        self._prefix = f"/repos/{owner}/{repo}"
        self._lock = asyncio.Lock()
        self._last_mutation = 0.0
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com", timeout=15, trust_env=False, verify=tls_context(),
            follow_redirects=False, transport=transport,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "general-agent-coding"},
        )

    def _scope(self, corp_id: str):
        if validate_corp_id(corp_id) != self.corp_id:
            raise KeyError("GitHub connection not found.")

    def _text(self, value, limit: int = 20_000) -> str:
        return str(value or "").replace(self._token, "[redacted]")[:limit]

    def _reject_secret(self, value):
        if self._token in _canonical(value).decode():
            raise ValueError("Delivery metadata cannot contain connection credentials.")

    async def _request(self, method: str, suffix: str = "", *, params=None, json_body=None,
                       missing: bool = False):
        # Callers construct suffixes from checked numbers, branches, and SHAs.
        # Neither remote links nor model URLs are followed.
        async with self._lock, asyncio.timeout(15):
            try:
                if method == "POST":
                    await asyncio.sleep(max(0, 1 - (time.monotonic() - self._last_mutation)))
                    self._last_mutation = time.monotonic()
                async with self._client.stream(method, self._prefix + suffix,
                                                params=params, json=json_body) as response:
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > _MAX_RESPONSE:
                            raise GitHubError("GitHub response exceeds the transfer limit.", uncertain=method == "POST")
                    if response.status_code == 404 and missing:
                        return None
                    expected = 201 if method == "POST" else 200
                    if response.status_code != expected:
                        raise GitHubError(f"GitHub request failed (HTTP {response.status_code}); no automatic retry.",
                                          uncertain=method == "POST" and (response.is_redirect or response.status_code >= 500 or response.is_success))
                    try:
                        return json.loads(data)
                    except (UnicodeDecodeError, ValueError):
                        raise GitHubError("GitHub returned an invalid JSON receipt.", uncertain=method == "POST") from None
            except (httpx.HTTPError, TimeoutError):
                raise GitHubError("GitHub request did not complete; inspect its journal before any new action.",
                                  uncertain=method == "POST") from None

    async def repository(self, corp_id: str) -> dict:
        self._scope(corp_id)
        record = await self._request("GET")
        if (not isinstance(record, dict) or type(record.get("id")) is not int
                or str(record.get("full_name", "")).casefold() != f"{self.owner}/{self.repo}".casefold()):
            raise GitHubError("The approved GitHub repository identity no longer matches.")
        return {"id": record["id"], "full_name": f"{self.owner}/{self.repo}",
                "url": f"https://github.com/{self.owner}/{self.repo}",
                "default_branch": _branch(record["default_branch"]),
                "private": bool(record.get("private")), "archived": bool(record.get("archived")),
                "description": self._text(record.get("description"), 2000)}

    @staticmethod
    def _number(number: int) -> int:
        if type(number) is not int or not 1 <= number <= 1_000_000_000:
            raise ValueError("A positive, bounded GitHub issue or pull request number is required.")
        return number

    def _item(self, record: dict, *, pull: bool = False, body_limit: int = 20_000) -> dict:
        if not isinstance(record, dict) or "number" not in record:
            raise GitHubError("GitHub returned an invalid issue or pull request.")
        number = self._number(record["number"])
        body = self._text(record.get("body"), body_limit)
        result = {"number": number, "title": self._text(record.get("title"), 300),
                  "body": body, "body_truncated": len(str(record.get("body") or "")) > body_limit,
                  "state": self._text(record.get("state"), 20),
                  "url": f"https://github.com/{self.owner}/{self.repo}/{'pull' if pull or 'pull_request' in record else 'issues'}/{number}",
                  "is_pull_request": pull or "pull_request" in record}
        if pull:
            result.update(draft=bool(record.get("draft")),
                          head=self._text(record.get("head", {}).get("ref"), 200),
                          base=self._text(record.get("base", {}).get("ref"), 200))
        return result

    async def _page(self, corp_id: str, suffix: str, *, page: int, state: str, pull: bool):
        self._scope(corp_id)
        if type(page) is not int or not 1 <= page <= 3 or state not in {"open", "closed", "all"}:
            raise ValueError("Read one bounded page (1–3) of open, closed, or all records.")
        records = await self._request("GET", suffix, params={"page": page, "per_page": 50, "state": state})
        if not isinstance(records, list) or len(records) > 50:
            raise GitHubError("GitHub returned an invalid page.")
        return {"items": [self._item(item, pull=pull, body_limit=1000) for item in records],
                "page": page, "next_page": page + 1 if len(records) == 50 and page < 3 else None,
                "truncated": len(records) == 50 and page == 3}

    async def issues(self, corp_id: str, *, page: int = 1, state: str = "open"):
        return await self._page(corp_id, "/issues", page=page, state=state, pull=False)

    async def pulls(self, corp_id: str, *, page: int = 1, state: str = "open"):
        return await self._page(corp_id, "/pulls", page=page, state=state, pull=True)

    async def issue(self, corp_id: str, number: int):
        self._scope(corp_id)
        return self._item(await self._request("GET", f"/issues/{self._number(number)}"))

    async def pull(self, corp_id: str, number: int):
        self._scope(corp_id)
        return self._item(await self._request("GET", f"/pulls/{self._number(number)}"), pull=True)

    async def _ref(self, branch: str, *, missing: bool = False):
        value = await self._request("GET", "/git/ref/heads/" + quote(_branch(branch), safe=""), missing=missing)
        if value is None:
            return None
        if value.get("ref") != f"refs/heads/{branch}" or value.get("object", {}).get("type") != "commit":
            raise GitHubError("GitHub returned a different branch reference.")
        return _sha(value["object"]["sha"])

    async def close(self):
        await self._client.aclose()


class GitHubDelivery:
    """Concrete review before any mutation; durable claim before publication.

    record_callback(corp_id, record, event) is synchronous and must durably save
    prepared/progress records. For claim it must atomically enforce the stored
    prepared digest and transition prepared→publishing exactly once. A callback
    failure prevents the next network mutation. The API layer supplies only its
    stored canonical proposal and claims under the session writer lock.
    """

    def __init__(self, connector: GitHubConnector, record_callback: Callable,
                 blob_loader: Callable[[str, str, str], bytes]):
        self.connector, self.record_callback, self.blob_loader = connector, record_callback, blob_loader

    def _save(self, corp_id: str, record: dict, event: str):
        self.record_callback(corp_id, deepcopy(record), event)

    @staticmethod
    def _snapshot(snapshot: dict):
        files = snapshot["files"]
        if not isinstance(files, dict) or len(files) > 5000 or source_revision(files) != snapshot["revision"]:
            raise CodingConflict("Frozen source manifest integrity check failed.")
        for path, entry in files.items():
            if validate_source_path(path).as_posix() != path or len(path) > 1024:
                raise ValueError("A canonical approved source path is required for delivery.")
            if (not _DIGEST.fullmatch(entry["sha256"]) or type(entry["size"]) is not int
                    or not 0 <= entry["size"] <= _MAX_BYTES or type(entry["mode"]) is not int
                    or not 0 <= entry["mode"] <= 0o777):
                raise ValueError("Frozen source metadata is invalid.")

    def _change(self, change: dict):
        before, after = change["before"], change["after"]
        self._snapshot(before)
        self._snapshot(after)
        if (hashlib.sha256(_canonical({"before": before, "after": after})).hexdigest() != change["revision"]
                or change["before_revision"] != before["revision"] or change["after_revision"] != after["revision"]):
            raise CodingConflict("Frozen change integrity check failed.")
        files = [{"path": path, "kind": "created" if path not in before["files"] else
                  "deleted" if path not in after["files"] else "modified",
                  "before": before["files"].get(path), "after": after["files"].get(path)}
                 for path in sorted(before["files"].keys() | after["files"].keys())
                 if before["files"].get(path) != after["files"].get(path)]
        if files != change["files"]:
            raise CodingConflict("Frozen change files do not match its source manifests.")
        if not files or len(files) > _MAX_FILES:
            raise ValueError("Delivery requires 1–100 changed source files.")
        paths = {item["path"] for item in files}
        if any("/".join(path.split("/")[:index]) in paths for path in paths for index in range(1, len(path.split("/")))):
            raise ValueError("File/directory replacements need separate review and cannot be delivered together.")
        return files

    def _bytes(self, corp_id: str, session_id: str, metadata: dict | None) -> bytes:
        if metadata is None:
            return b""
        data = self.blob_loader(corp_id, session_id, metadata["sha256"])
        if (not isinstance(data, bytes) or len(data) != metadata["size"]
                or hashlib.sha256(data).hexdigest() != metadata["sha256"]):
            raise CodingConflict("An immutable delivery source version failed its integrity check.")
        if self.connector._token.encode() in data:
            raise ValueError("Source delivery cannot contain connection credentials.")
        return data

    def _versions(self, corp_id: str, session_id: str, files: list[dict]):
        versions, total, diff = {}, 0, []
        for item in files:
            old = self._bytes(corp_id, session_id, item["before"])
            new = self._bytes(corp_id, session_id, item["after"])
            total += len(old) + len(new)
            if total > _MAX_BYTES:
                raise ValueError("Delivery source versions exceed the 5 MiB review limit.")
            try:
                old_text, new_text = old.decode("utf-8"), new.decode("utf-8")
                if b"\0" in old or b"\0" in new:
                    raise UnicodeError
            except UnicodeError:
                raise ValueError("Binary changes require a separate delivery workflow; this review supports UTF-8 source.") from None
            if (item["before"] and item["after"] and old == new
                    and _git_mode(item["before"]["mode"]) == _git_mode(item["after"]["mode"])):
                raise ValueError("Git cannot represent this permission-only source change.")
            text = "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                           for line in difflib.unified_diff(old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                                fromfile=f"a/{item['path']}" if item["before"] else "/dev/null",
                                tofile=f"b/{item['path']}" if item["after"] else "/dev/null"))
            old_mode = _git_mode(item["before"]["mode"]) if item["before"] else None
            new_mode = _git_mode(item["after"]["mode"]) if item["after"] else None
            if old_mode != new_mode:
                text = f"Git mode {old_mode or 'absent'} → {new_mode or 'absent'}: {item['path']}\n" + text
            diff.append(text)
            versions[item["path"]] = {"old": old, "new": new, "text": new_text,
                                      "old_git_sha": _git_blob(old) if item["before"] else None,
                                      "new_git_sha": _git_blob(new) if item["after"] else None,
                                      "old_mode": old_mode, "new_mode": new_mode}
        result = "".join(diff)
        if len(result) > _MAX_DIFF:
            raise ValueError("The complete delivery diff exceeds the 200,000 character review limit.")
        return versions, result

    async def _preimages(self, base_tree: str, files: list[dict], versions: dict):
        trees = {}

        async def tree(sha):
            if sha not in trees:
                record = await self.connector._request("GET", f"/git/trees/{_sha(sha)}")
                entries = record.get("tree", [])
                if record.get("truncated") or record.get("sha") != sha or len(entries) > 10_000:
                    raise GitHubError("Remote directory inventory is incomplete or exceeds its limit.")
                names = [entry["path"] for entry in entries]
                if len(names) != len(set(names)) or any("/" in name or name in {".", ".."} for name in names):
                    raise GitHubError("GitHub returned an invalid directory tree.")
                trees[sha] = {entry["path"]: entry for entry in entries}
            return trees[sha]

        for item in files:
            parts, sha, remote = item["path"].split("/"), base_tree, None
            for index, part in enumerate(parts):
                remote = (await tree(sha)).get(part)
                if remote is None or index == len(parts) - 1:
                    break
                if remote.get("type") != "tree" or remote.get("mode") != "040000":
                    raise CodingConflict("A remote source ancestor is a file, link, or submodule.")
                sha = _sha(remote["sha"])
            if item["before"] is None:
                if remote is not None:
                    raise CodingConflict("A newly created source path already exists on the remote base.")
            elif (remote is None or remote.get("type") != "blob"
                    or remote.get("mode") != versions[item["path"]]["old_mode"]
                    or remote.get("sha") != versions[item["path"]]["old_git_sha"]):
                raise CodingConflict("A touched remote file differs from the accepted source baseline.")

    def _verification(self, verification: dict, revision: str):
        outcome = verification.get("outcome", "not_verified")
        if outcome not in {"verified", "not_verified", "checks_failed", "blocked"}:
            raise ValueError("An authoritative verification outcome is required.")
        records = verification.get("checks", [])
        if not isinstance(records, list) or len(records) > 100:
            raise ValueError("Check evidence exceeds the delivery review limit.")
        checks = [{key: check.get(key) for key in ("id", "name", "command", "phase", "status", "exit_code", "revision", "runtime_identity", "reason", "evidence_id", "evidence_sha256")}
                  for check in records]
        runtime = verification.get("runtime_identity")
        latest = {check["name"]: check for check in checks if check["phase"] != "baseline"}
        if outcome == "verified" and (not latest or not runtime or any(
            check["status"] != "passed" or check["exit_code"] != 0 or check["revision"] != revision
            or check["runtime_identity"] != runtime for check in latest.values()
        )):
            raise CodingConflict("Verified delivery requires current source and runtime check evidence.")
        browser = [{key: check.get(key) for key in ("id", "status", "target", "source_revision", "main_runtime_identity", "reason", "evidence_id", "evidence_sha256")}
                   for check in verification.get("browser_checks", [])]
        result = {"outcome": outcome, "runtime_identity": runtime, "checks": checks, "browser_checks": browser}
        if len(_canonical(result)) > 100_000:
            raise ValueError("Check evidence exceeds the delivery review limit.")
        self.connector._reject_secret(result)
        return result

    async def prepare(self, corp_id: str, session_id: str, change: dict, verification: dict,
                      title: str, body: str = "", *, base: str | None = None) -> dict:
        self.connector._scope(corp_id)
        if not _ID.fullmatch(session_id) or not _ID.fullmatch(change["id"]):
            raise ValueError("An existing coding session and immutable change are required.")
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or "\n" in title or "\r" in title:
            raise ValueError("A concrete pull request title within 200 characters is required.")
        if not isinstance(body, str) or len(body) > 10_000:
            raise ValueError("Pull request text exceeds the review limit.")
        self.connector._reject_secret({"title": title, "body": body})
        change = deepcopy(change)
        files = self._change(change)
        versions, diff = self._versions(corp_id, session_id, files)
        evidence = self._verification(verification, change["after_revision"])
        async with asyncio.timeout(30):
            repository = await self.connector.repository(corp_id)
            if repository["archived"]:
                raise CodingConflict("An archived repository cannot receive delivery.")
            base = _branch(base or repository["default_branch"])
            base_sha = await self.connector._ref(base)
            commit = await self.connector._request("GET", f"/git/commits/{base_sha}")
            if commit.get("sha") != base_sha:
                raise GitHubError("GitHub returned a different base commit.")
            base_tree = _sha(commit["tree"]["sha"])
            await self._preimages(base_tree, files, versions)
        delivery_id = identifier()
        branch = f"codex/coding-{delivery_id}"
        check_lines = "\n".join(f"- {entry['name']}: {entry['status']}" for entry in evidence["checks"])
        pr_body = (body.strip() + "\n\n" if body.strip() else "") + (
            f"Source revision: `{change['after_revision']}`\n"
            f"Immutable change: `{change['revision']}`\n"
            f"Session verification: **{evidence['outcome']}**. GitHub CI is separate.\n"
            + (check_lines + "\n" if check_lines else "No approved check evidence was recorded.\n")
            + f"\nDelivery: `{delivery_id}`\n")
        proposal = {"repository": repository["full_name"], "repository_id": repository["id"],
                    "base_branch": base, "base_commit": base_sha, "base_tree": base_tree,
                    "branch": branch, "change_id": change["id"], "change_revision": change["revision"],
                    "source_revision": change["after_revision"], "baseline_revision": change["before_revision"],
                    "change": change, "files": [{**item, "git_before": versions[item['path']]["old_git_sha"],
                        "git_after": versions[item['path']]["new_git_sha"], "git_mode": versions[item['path']]["new_mode"]} for item in files],
                    "diff": diff, "verification": evidence, "title": title.strip(), "body": pr_body,
                    "actions": ["Create remote Git tree and commit from this base.",
                                "Create this new codex branch; leave existing branches unchanged.",
                                "Open a draft pull request; repository workflows may run."]}
        self.connector._reject_secret(proposal)
        record = {"id": delivery_id, "session_id": session_id, "corp_id": corp_id,
                  "status": "prepared", "created": now(), "proposal": proposal,
                  "digest": hashlib.sha256(_canonical(proposal)).hexdigest(), "journal": []}
        self._save(corp_id, record, "prepared")
        return record

    async def _stable(self, corp_id: str, proposal: dict):
        repository = await self.connector.repository(corp_id)
        if repository["id"] != proposal["repository_id"] or repository["archived"]:
            raise CodingConflict("The approved remote repository identity or write availability changed.")
        if proposal["branch"] == repository["default_branch"]:
            raise CodingConflict("Delivery cannot write the default branch.")
        if await self.connector._ref(proposal["base_branch"]) != proposal["base_commit"]:
            raise CodingConflict("The remote base advanced; prepare and review a new delivery.")

    async def _mutation(self, corp_id: str, record: dict, action: str, suffix: str, payload: dict, receipt: Callable):
        entry = {"action": action, "state": "sending", "started": now(),
                 "request_digest": hashlib.sha256(_canonical(payload)).hexdigest()}
        record["journal"].append(entry)
        self._save(corp_id, record, "progress")
        try:
            value = await self.connector._request("POST", suffix, json_body=payload)
            try:
                result = receipt(value)
            except (ValueError, KeyError, TypeError, AttributeError):
                raise GitHubError("GitHub returned an unexpected publication receipt; inspect the journal.", uncertain=True) from None
        except GitHubError as exc:
            entry.update(state="uncertain" if exc.uncertain else "failed", ended=now())
            raise
        entry.update(state="succeeded", ended=now(), receipt=result)
        self._save(corp_id, record, "progress")
        return result

    async def publish(self, corp_id: str, record: dict, *, expected_digest: str,
                      current_source_revision: str) -> dict:
        self.connector._scope(corp_id)
        record = deepcopy(record)
        proposal = record["proposal"]
        if (record["corp_id"] != corp_id or not _ID.fullmatch(record["id"])
                or not _BRANCH.fullmatch(proposal["branch"]) or proposal["branch"] != f"codex/coding-{record['id']}"
                or proposal["repository"].casefold() != f"{self.connector.owner}/{self.connector.repo}".casefold()
                or record["status"] != "prepared" or record.get("journal")):
            raise CodingConflict("This delivery is not an unused, scoped application proposal.")
        digest = hashlib.sha256(_canonical(proposal)).hexdigest()
        if digest != record["digest"] or digest != expected_digest:
            raise CodingConflict("The reviewed delivery digest no longer matches.")
        if current_source_revision != proposal["source_revision"]:
            raise CodingConflict("Session source changed after delivery review.")
        files = self._change(proposal["change"])
        versions, diff = self._versions(corp_id, record["session_id"], files)
        if diff != proposal["diff"] or proposal["source_revision"] != proposal["change"]["after_revision"]:
            raise CodingConflict("Delivery review differs from its immutable source versions.")
        self.connector._reject_secret(proposal)
        record.update(status="publishing", claimed=now())
        self._save(corp_id, record, "claim")
        try:
            async with asyncio.timeout(90):
                await self._stable(corp_id, proposal)
                if await self.connector._ref(proposal["branch"], missing=True) is not None:
                    raise CodingConflict("The proposed branch already exists; prepare a new delivery.")
                await self._preimages(proposal["base_tree"], files, versions)
                tree_entries = [{"path": item["path"], "type": "blob",
                                 "mode": versions[item["path"]]["new_mode"] or versions[item["path"]]["old_mode"],
                                 **({"content": versions[item["path"]]["text"]} if item["after"] else {"sha": None})}
                                for item in files]
                tree = await self._mutation(corp_id, record, "create_tree", "/git/trees",
                    {"base_tree": proposal["base_tree"], "tree": tree_entries}, lambda value: {"sha": _sha(value["sha"])})

                def commit_receipt(value):
                    if value["tree"]["sha"] != tree["sha"] or [entry["sha"] for entry in value["parents"]] != [proposal["base_commit"]]:
                        raise ValueError("Commit ancestry differs.")
                    return {"sha": _sha(value["sha"])}

                commit = await self._mutation(corp_id, record, "create_commit", "/git/commits",
                    {"message": proposal["title"], "tree": tree["sha"], "parents": [proposal["base_commit"]]}, commit_receipt)
                await self._stable(corp_id, proposal)

                def ref_receipt(value):
                    if value["ref"] != f"refs/heads/{proposal['branch']}" or value["object"]["sha"] != commit["sha"] or value["object"]["type"] != "commit":
                        raise ValueError("Created branch differs.")
                    return {"branch": proposal["branch"], "sha": commit["sha"]}

                await self._mutation(corp_id, record, "create_branch", "/git/refs",
                    {"ref": f"refs/heads/{proposal['branch']}", "sha": commit["sha"]}, ref_receipt)
                await self._stable(corp_id, proposal)

                def pull_receipt(value):
                    number = self.connector._number(value["number"])
                    if (value["draft"] is not True or value["head"]["ref"] != proposal["branch"]
                            or value["head"]["sha"] != commit["sha"] or value["base"]["ref"] != proposal["base_branch"]
                            or value["base"]["sha"] != proposal["base_commit"]
                            or value["head"]["repo"]["id"] != proposal["repository_id"]
                            or value["base"]["repo"]["id"] != proposal["repository_id"]):
                        raise ValueError("Created draft scope differs.")
                    return {"number": number, "url": f"https://github.com/{self.connector.owner}/{self.connector.repo}/pull/{number}", "draft": True}

                pull = await self._mutation(corp_id, record, "create_draft_pull_request", "/pulls",
                    {"title": proposal["title"], "body": proposal["body"], "head": proposal["branch"],
                     "base": proposal["base_branch"], "draft": True, "maintainer_can_modify": False}, pull_receipt)
                record.update(status="published", ended=now(), remote={**pull, "branch": proposal["branch"], "commit": commit["sha"]})
                try:
                    await self._stable(corp_id, proposal)
                except (CodingConflict, GitHubError):
                    record.update(status="needs_review", error="Publication completed, but its remote base could not be revalidated.")
                self._save(corp_id, record, "progress")
                return record
        except BaseException as exc:
            uncertain = (isinstance(exc, GitHubError) and exc.uncertain
                         or bool(record["journal"] and record["journal"][-1]["state"] in {"sending", "uncertain"}))
            record.update(status="uncertain" if uncertain else "failed", ended=now(),
                          error="Delivery stopped. Inspect recorded remote receipts before preparing any new action.")
            self._save(corp_id, record, "progress")
            raise
