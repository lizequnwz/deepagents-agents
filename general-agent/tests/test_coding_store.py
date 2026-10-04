"""Scoped persistence, queue ownership and interrupted-attempt recovery."""

import pytest

from general_agent.coding.store import CodingConflict, CodingStore


def populate(store, corp, root, project, session):
    store.register_project(corp, {"id": project, "root": str(root)})
    store.add_session(corp, {"id": session, "project_id": project})


def test_registry_scope_and_physical_overlap(tmp_path):
    store = CodingStore(tmp_path / "coding.db")
    populate(store, "A123456", tmp_path / "one", "p1", "s1")
    populate(store, "B123456", tmp_path / "two", "p2", "s2")
    with pytest.raises(KeyError):
        store.session("B123456", "s1")
    with pytest.raises(CodingConflict):
        store.register_project("B123456", {"id": "p3", "root": str(tmp_path / "one" / "nested")})
    with pytest.raises(CodingConflict):
        store.register_project("B123456", {"id": "p4", "root": str(tmp_path)})
    assert len(store.projects("A123456")) == 1
    store.close()


def test_queue_writers_events_and_restart(tmp_path):
    path = tmp_path / "coding.db"
    store = CodingStore(path)
    populate(store, "A123456", tmp_path / "one", "p1", "s1")
    populate(store, "B123456", tmp_path / "two", "p2", "s2")
    for index, (corp, session) in enumerate([
        ("A123456", "s1"), ("A123456", "s1"), ("B123456", "s2")
    ]):
        store.enqueue(corp, {"id": f"a{index}", "session_id": session,
                             "status": "queued", "created": str(index)})
    assert store.claim(2)["id"] == "a0"
    assert store.claim(2)["id"] == "a2"
    assert store.claim(2) is None
    for index in range(5):
        store.event("A123456", "a0", {"kind": "progress", "index": index})
    page = store.events("A123456", "a0", limit=2)
    next_page = store.events("A123456", "a0", after=page["next_cursor"], limit=2)
    assert [item["index"] for item in page["events"] + next_page["events"]] == [0, 1, 2, 3]
    assert page["has_more"]
    with pytest.raises(KeyError):
        store.events("B123456", "a0")
    store.close()
    recovered = CodingStore(path)
    assert recovered.attempt("A123456", "a0")["status"] == "failed"
    assert recovered.attempt("A123456", "a1")["status"] == "queued"
    assert recovered.claim(1)["id"] == "a1"
    recovered.close()


def test_decisions_are_scoped_and_single_use(tmp_path):
    store = CodingStore(tmp_path / "coding.db")
    populate(store, "A123456", tmp_path / "one", "p1", "s1")
    store.add_decision("A123456", {"id": "d1", "session_id": "s1", "status": "pending"})
    with pytest.raises(KeyError):
        store.respond("B123456", "d1", "approve")
    assert store.respond("A123456", "d1", "approve")["status"] == "approve"
    with pytest.raises(CodingConflict):
        store.respond("A123456", "d1", "reject")
    store.close()


def test_scheduler_exclusive_ownership_and_corporation_admission(tmp_path):
    path = tmp_path / "coding.db"
    store = CodingStore(path)
    with pytest.raises(CodingConflict, match="owns the coding scheduler"):
        CodingStore(path)
    original = store.scheduler_health()
    store.heartbeat()
    assert store.scheduler_health()["owner_id"] == original["owner_id"]
    assert store.scheduler_health()["heartbeat"] >= original["heartbeat"]
    populate(store, "A123456", tmp_path / "one", "p1", "s1")
    store.add_session("A123456", {"id": "s2", "project_id": "p1"})
    populate(store, "B123456", tmp_path / "two", "p2", "s3")
    for index, (corp, sid) in enumerate([("A123456", "s1"), ("A123456", "s2"), ("B123456", "s3")]):
        store.enqueue(corp, {"id": str(index), "session_id": sid, "status": "queued", "created": str(index)})
    assert store.claim(3, 1)["id"] == "0"
    assert store.claim(3, 1)["id"] == "2"
    assert store.claim(3, 1) is None
    store.close()
    replacement = CodingStore(path)
    assert replacement.scheduler_health()["owner_id"] != original["owner_id"]
    assert replacement.claim(1)["id"] == "1"
    replacement.close()


def test_history_is_bounded_scoped_and_approval_queue_is_atomic(tmp_path):
    store = CodingStore(tmp_path / "coding.db")
    populate(store, "A123456", tmp_path / "one", "p1", "s1")
    store.add_session("A123456", {"id": "s2", "project_id": "p1"})
    for index in range(5):
        store.enqueue("A123456", {"id": str(index), "session_id": "s1", "status": "queued", "created": str(index)})
    page = store.attempts("A123456", "s1", limit=2)
    assert [a["id"] for a in page] == ["3", "4"]
    assert [a["id"] for a in store.attempts("A123456", "s1", limit=2, before="3")] == ["1", "2"]
    with pytest.raises(CodingConflict):
        store.attempts("A123456", "s2", before="3")
    store.add_decision("A123456", {"id": "d1", "session_id": "s1", "status": "pending"})
    duplicate = {"id": "0", "session_id": "s1", "status": "queued", "created": "5"}
    with pytest.raises(Exception):
        store.approve_and_enqueue("A123456", "d1", duplicate)
    assert store.decision("A123456", "d1")["status"] == "pending"
    queued = {**duplicate, "id": "new"}
    store.approve_and_enqueue("A123456", "d1", queued)
    assert store.decision("A123456", "d1")["implementation_id"] == "new"
    with pytest.raises(CodingConflict):
        store.approve_and_enqueue("A123456", "d1", queued)
    assert store.has_pending("A123456", "s1")
    store.close()
