import io

import pytest
from PIL import Image

from general_agent.coding.evidence import EvidenceStore
from general_agent.coding.store import CodingConflict


CORP = "A123456"
SESSION = "a" * 32


def test_check_manifests_and_logs_are_immutable_and_scoped(settings):
    store = EvidenceStore(settings)
    snapshot = {"revision": "rev", "files": {"a.py": {"sha256": "hash", "mode": 0o644, "size": 3}}}
    check = {"name": "tests", "output": "observed log", "exit_code": 0}
    ref = store.check(CORP, SESSION, check, snapshot, snapshot)
    record = store.get(CORP, SESSION, ref["evidence_id"], ref["evidence_sha256"])
    assert record["check"] == check
    assert record["before"] == snapshot
    with pytest.raises(FileNotFoundError):
        store.get("OTHER_CORP", SESSION, ref["evidence_id"], ref["evidence_sha256"])
    path = store._directory(CORP, SESSION) / (ref["evidence_id"] + ".json")
    assert path.stat().st_mode & 0o777 == 0o400
    path.chmod(0o600)
    path.write_text("{}")
    with pytest.raises(CodingConflict, match="integrity"):
        store.get(CORP, SESSION, ref["evidence_id"], ref["evidence_sha256"])


def test_screenshot_validation_hashes_and_quota(settings):
    store = EvidenceStore(settings)
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), "blue").save(buffer, format="PNG")
    data = buffer.getvalue()
    record = store.image(CORP, SESSION, data, label="Preview", revision="revision", runtime_identity="image")
    assert (record["width"], record["height"]) == (16, 12)
    assert store.image_bytes(CORP, SESSION, record) == data
    store.max_bytes = 1
    with pytest.raises(ValueError, match="storage limit"):
        store.check(CORP, SESSION, {"output": "another"}, {}, {})
    with pytest.raises((ValueError, OSError)):
        store.image(CORP, SESSION, b"not an image", label="Invalid", revision="rev", runtime_identity="image")


def test_evidence_rejects_symlinks_and_oversized_images(settings, tmp_path):
    store = EvidenceStore(settings)
    path = store._directory(CORP, SESSION)
    (path / "bad.json").symlink_to(tmp_path / "foreign")
    with pytest.raises(CodingConflict, match="invalid file"):
        store.check(CORP, SESSION, {}, {}, {})
    with pytest.raises(ValueError, match="five MiB"):
        store.image(CORP, SESSION, b"x" * (5 * 1024 * 1024 + 1), label="Big", revision="rev", runtime_identity="image")
