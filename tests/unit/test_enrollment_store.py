"""The local handoff keeps selection stable across retries, races and restarts."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from tsunagou.platform.enrollment_store import EnrollmentStore


def _new(store: EnrollmentStore, tmp_path: Path, *, role: str = "main") -> dict[str, Any]:
    return store.create(project_id="project-a", project_root=tmp_path / "project", role=role, nickname="熊猫")


def test_selection_is_persistent_and_independent_of_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    directory = tmp_path / "private"
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(directory))
    record = _new(EnrollmentStore(), tmp_path)
    monkeypatch.chdir(tmp_path)
    assert EnrollmentStore().current() == record
    assert record["requested_role"] == "main"
    assert Path(record["receipt_file"]).is_absolute()
    assert record["project_root"] == str((tmp_path / "project").resolve())


def test_only_one_active_slot_can_be_created(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    record = _new(store, tmp_path)
    with pytest.raises(RuntimeError, match="^enrollment_already_pending$"):
        _new(store, tmp_path, role="worker")
    assert store.current() == record
    store.cancel(record["enrollment_id"])
    second = _new(store, tmp_path, role="worker")
    assert second["requested_role"] == "worker"
    assert store.get(record["enrollment_id"])["status"] == "cancelled"


def test_pending_expires_but_claimed_never_transfers(tmp_path: Path) -> None:
    now = [100.0]
    store = EnrollmentStore(tmp_path / "store", clock=lambda: now[0])
    expired = _new(store, tmp_path)
    now[0] += 901
    with pytest.raises(RuntimeError, match="^enrollment_not_pending$"):
        store.current()
    assert store.get(expired["enrollment_id"])["status"] == "expired"
    with pytest.raises(RuntimeError, match="^enrollment_expired$"):
        store.claim(expired["enrollment_id"], "a", expected_revision=1)
    active = _new(store, tmp_path)
    claimed = store.claim(active["enrollment_id"], "a", expected_revision=1)
    now[0] += 90000
    assert store.current("a") == claimed
    with pytest.raises(RuntimeError, match="^enrollment_claimed_by_another_chat$"):
        store.claim(active["enrollment_id"], "b", expected_revision=claimed["revision"])


def test_concurrent_claims_have_exactly_one_owner(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    record = _new(store, tmp_path)

    def claim(thread: str) -> str:
        try:
            return str(EnrollmentStore(store.directory).claim(record["enrollment_id"], thread, expected_revision=1)["thread_id"])
        except RuntimeError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["thread-a", "thread-b"]))
    assert results.count("enrollment_claimed_by_another_chat") == 1
    assert store.get(record["enrollment_id"])["thread_id"] in {"thread-a", "thread-b"}


def test_same_owner_retries_preserve_identity_and_cannot_steal_next_slot(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    record = _new(store, tmp_path)
    claimed = store.claim(record["enrollment_id"], "a", expected_revision=1)
    assert store.claim(record["enrollment_id"], "a", expected_revision=1) == claimed
    store.fail(record["enrollment_id"], "a", "host_not_ready:private detail")
    assert store.current("a")["error"] == "host_not_ready"
    store.claim(record["enrollment_id"], "a", expected_revision=1)
    store.mark_enrolled(record["enrollment_id"], "a", agent_id="agent-a")
    arrived = store.mark_arrived(record["enrollment_id"])
    next_record = _new(store, tmp_path, role="worker")
    assert store.current("a") == arrived
    assert store.current("b") == next_record
    assert store.get(record["enrollment_id"])["agent_id"] == "agent-a"
    with pytest.raises(RuntimeError, match="^enrollment_agent_mismatch$"):
        store.mark_enrolled(record["enrollment_id"], "a", agent_id="agent-b")


def test_revision_and_cancel_fence_claim_side_effects(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    record = _new(store, tmp_path)
    with pytest.raises(RuntimeError, match="^enrollment_revision_conflict$"):
        store.claim(record["enrollment_id"], "a", expected_revision=0)
    assert store.get(record["enrollment_id"])["status"] == "pending"
    store.cancel(record["enrollment_id"])
    with pytest.raises(RuntimeError, match="^enrollment_cancelled$"):
        store.claim(record["enrollment_id"], "a", expected_revision=1)


def test_claimed_cannot_be_cancelled_or_completed_without_enrollment(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    record = _new(store, tmp_path)
    store.claim(record["enrollment_id"], "a", expected_revision=1)
    with pytest.raises(RuntimeError, match="^enrollment_already_claimed$"):
        store.cancel(record["enrollment_id"])
    with pytest.raises(RuntimeError, match="^enrollment_not_enrolled$"):
        store.mark_arrived(record["enrollment_id"])
    with pytest.raises(RuntimeError, match="^enrollment_claimed_by_another_chat$"):
        store.mark_enrolled(record["enrollment_id"], "b", agent_id="agent-b")


def test_corrupt_store_fails_closed(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    _new(store, tmp_path)
    store.path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="^enrollment_store_invalid$"):
        store.current()
    assert json.loads(store.path.read_text(encoding="utf-8")) == {}


def test_forget_keeps_history_but_revokes_unfinished_handoff(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    record = _new(store, tmp_path)
    store.claim(record["enrollment_id"], "a", expected_revision=1)
    assert store.forget_project("another") == []
    assert store.forget_project("project-a") == [record["enrollment_id"]]
    assert store.get(record["enrollment_id"])["status"] == "forgotten"
    with pytest.raises(RuntimeError, match="^enrollment_forgotten$"):
        store.mark_enrolled(record["enrollment_id"], "a", agent_id="agent-a")
    assert _new(store, tmp_path)["enrollment_id"] != record["enrollment_id"]


def test_same_selection_reprepare_is_idempotent_even_after_claim(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    assert store.active() is None
    record = _new(store, tmp_path)
    assert store.active() == record
    assert _new(store, tmp_path) == record
    claimed = store.claim(record["enrollment_id"], "a", expected_revision=1)
    reused = store.create(project_id="project-a", project_root=tmp_path / "project", role="main", nickname="other")
    assert reused == claimed and reused["nickname"] == "熊猫"
    assert store.active() == claimed


def test_reprepare_conflicts_if_project_root_or_role_changed(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    record = _new(store, tmp_path)
    for project_id, root, role in [
        ("other", tmp_path / "project", "main"),
        ("project-a", tmp_path / "other", "main"),
        ("project-a", tmp_path / "project", "worker"),
    ]:
        with pytest.raises(RuntimeError, match="^enrollment_already_pending$"):
            store.create(project_id=project_id, project_root=root, role=role)
    assert store.active() == record


def test_late_failure_preserves_enrolled_and_arrived(tmp_path: Path) -> None:
    store = EnrollmentStore(tmp_path / "store")
    record = _new(store, tmp_path)
    store.claim(record["enrollment_id"], "a", expected_revision=1)
    enrolled = store.mark_enrolled(record["enrollment_id"], "a", agent_id="agent-a")
    assert store.fail(record["enrollment_id"], "a", "host_timeout") == enrolled
    arrived = store.mark_arrived(record["enrollment_id"])
    assert store.fail(record["enrollment_id"], "a", "host_timeout") == arrived
    assert store.active() is None


def test_the_slot_is_not_codex_only_and_is_read_per_adapter(tmp_path: Path) -> None:
    """宿主自己接入那条路也要记下"接哪个项目"，但只有它自己的聊天读得到这条。"""

    store = EnrollmentStore(tmp_path / "store")
    record = store.create(
        project_id="project-a", project_root=tmp_path / "project", role="main", adapter="deepseek",
    )
    assert record["adapter"] == "deepseek"
    assert store.active_for("deepseek") == record
    assert store.active_for("codex") is None
    assert store.active_for("") is None
    with pytest.raises(RuntimeError, match="^enrollment_selection_invalid$"):
        store.create(project_id="project-a", project_root=tmp_path / "project", role="main", adapter="Deep Seek")


def test_a_watched_arrival_closes_the_slot_but_a_bound_record_belongs_to_its_chat(tmp_path: Path) -> None:
    """控制台看着名单确认到达 = Codex 的 mark_arrived；有主的记录不许别人替它收尾。"""

    store = EnrollmentStore(tmp_path / "store")
    watched = store.create(
        project_id="project-a", project_root=tmp_path / "project", role="worker", adapter="opencode",
    )
    arrived = store.observe_arrival(watched["enrollment_id"], agent_id="agent-a")
    assert arrived["status"] == "arrived" and arrived["agent_id"] == "agent-a"
    assert store.active() is None, "下一个人得接得上"

    bound = _new(store, tmp_path)
    store.claim(bound["enrollment_id"], "chat-a", expected_revision=1)
    with pytest.raises(RuntimeError, match="^enrollment_claimed_by_another_chat$"):
        store.observe_arrival(bound["enrollment_id"], agent_id="agent-b")
    assert store.active() == store.get(bound["enrollment_id"])
