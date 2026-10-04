"""Bounded immutable check and browser evidence, outside editable source."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import threading
from pathlib import Path

from PIL import Image

from general_agent.coding.store import CodingConflict, identifier, now
from general_agent.config import Settings
from general_agent.workspace import corp_storage_key, workspace_directory, workspace_file


class EvidenceStore:
    def __init__(self, settings: Settings):
        self.root = settings.coding_root
        self.max_bytes = min(50, settings.coding_storage_mb) * 1024 * 1024
        self._lock = threading.RLock()
        with workspace_directory(settings.project_root, self.root, create=True):
            pass

    def _directory(self, corp_id: str, session_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("Invalid evidence session ID.")
        directory = self.root / corp_storage_key(corp_id) / session_id / "evidence"
        with workspace_directory(self.root, directory, create=True):
            pass
        return directory

    def _read(self, directory: Path, name: str, *, limit: int) -> bytes:
        with workspace_file(self.root, directory / name, os.O_RDONLY) as descriptor:
            info = os.fstat(descriptor)
            if info.st_nlink != 1 or info.st_size > limit:
                raise CodingConflict("Evidence is invalid or exceeds its transfer limit.")
            with os.fdopen(os.dup(descriptor), "rb") as reader:
                content = reader.read(limit + 1)
        if len(content) > limit:
            raise CodingConflict("Evidence exceeds its transfer limit.")
        return content

    def _freeze(self, directory: Path, name: str, content: bytes) -> None:
        with self._lock, workspace_directory(self.root, directory) as parent:
            entries = os.listdir(parent)
            if len(entries) >= 5000:
                raise ValueError("Session evidence count limit reached; history is retained.")
            total = 0
            for entry in entries:
                info = os.stat(entry, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise CodingConflict("Evidence storage contains an invalid file.")
                total += info.st_size
            if name in entries:
                if self._read(directory, name, limit=self.max_bytes) != content:
                    raise CodingConflict("Immutable evidence was changed.")
                return
            if total + len(content) > self.max_bytes:
                raise ValueError("Session evidence storage limit reached; history is retained.")
            with workspace_file(self.root, directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL) as descriptor:
                with os.fdopen(os.dup(descriptor), "wb") as writer:
                    writer.write(content)
                    writer.flush()
                os.fchmod(descriptor, 0o400)
                os.fsync(descriptor)
            os.fsync(parent)

    def _record(self, corp_id: str, session_id: str, record: dict) -> dict:
        directory = self._directory(corp_id, session_id)
        content = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        if len(content) > 4 * 1024 * 1024:
            raise ValueError("Evidence manifest exceeds its limit.")
        self._freeze(directory, record["id"] + ".json", content)
        return {"evidence_id": record["id"], "evidence_sha256": hashlib.sha256(content).hexdigest()}

    def check(self, corp_id: str, session_id: str, check: dict, before: dict, after: dict) -> dict:
        return self._record(corp_id, session_id, {"id": identifier(), "kind": "check", "created": now(),
                                                 "check": check, "before": before, "after": after})

    def documentation(self, corp_id: str, session_id: str, source: dict) -> dict:
        return self._record(corp_id, session_id, {"id": identifier(), "kind": "documentation",
                                                 "created": now(), "source": source})

    def browser(self, corp_id: str, session_id: str, check: dict) -> dict:
        return self._record(corp_id, session_id, {"id": identifier(), "kind": "browser",
                                                 "created": now(), "check": check})

    def connector(self, corp_id: str, session_id: str, result: dict) -> dict:
        return self._record(corp_id, session_id, {"id": identifier(), "kind": "connector",
                                                 "created": now(), "result": result})

    def image(self, corp_id: str, session_id: str, data: bytes, *, label: str,
              revision: str, runtime_identity: str) -> dict:
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("Screenshot exceeds five MiB.")
        with Image.open(io.BytesIO(data)) as picture:
            width, height = picture.size
            if picture.format != "PNG" or width <= 0 or height <= 0 or width * height > 5_000_000:
                raise ValueError("Screenshot must be a bounded PNG image.")
            picture.verify()
        sha256 = hashlib.sha256(data).hexdigest()
        self._freeze(self._directory(corp_id, session_id), sha256 + ".png", data)
        record = {"id": identifier(), "kind": "image", "created": now(), "label": label[:200],
                  "revision": revision, "runtime_identity": runtime_identity,
                  "sha256": sha256, "size": len(data), "width": width, "height": height}
        return {**record, **self._record(corp_id, session_id, record)}

    def get(self, corp_id: str, session_id: str, evidence_id: str, sha256: str) -> dict:
        if not re.fullmatch(r"[a-f0-9]{32}", evidence_id) or not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("Invalid evidence identity.")
        content = self._read(self._directory(corp_id, session_id), evidence_id + ".json", limit=4 * 1024 * 1024)
        if hashlib.sha256(content).hexdigest() != sha256:
            raise CodingConflict("Evidence integrity check failed.")
        record = json.loads(content)
        if record["id"] != evidence_id:
            raise CodingConflict("Evidence identity check failed.")
        return record

    def image_bytes(self, corp_id: str, session_id: str, record: dict) -> bytes:
        if record["kind"] != "image" or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"]):
            raise ValueError("Invalid screenshot identity.")
        data = self._read(self._directory(corp_id, session_id), record["sha256"] + ".png", limit=5 * 1024 * 1024)
        if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise CodingConflict("Screenshot integrity check failed.")
        return data
