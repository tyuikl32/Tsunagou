import pytest

from tsunagou.modules.resources import ResourceKey, ResourceRequest, ResourceService
from tsunagou.shared_kernel.errors import ResourceConflict


def reserve(service, requests, attempt="a1", **kwargs):
    return service.reserve_set(
        task_id="t-" + attempt,
        attempt_id=attempt,
        owner_agent_id="w-" + attempt,
        execution_epoch=1,
        scope_digest="scope",
        requests=requests,
        **kwargs,
    )


def test_prefix_conflict_matrix_and_all_or_none():
    service = ResourceService()
    read = ResourceRequest(ResourceKey.path("root", "src"), "read")
    stable = ResourceRequest(ResourceKey.path("root", "src", "pkg"), "consistent_read")
    write = ResourceRequest(ResourceKey.path("root", "src"), "exclusive_write")
    held = reserve(service, [stable])
    assert not service.check_conflicts([read])
    assert not service.check_conflicts([stable])
    assert service.check_conflicts([write]) == [stable.key.canonical]
    with pytest.raises(ResourceConflict) as exc:
        reserve(service, [write, ResourceRequest(ResourceKey.named("db", "migration"), "exclusive_use")], "a2")
    assert exc.value.blockers[0]["owner_agent_id"] == "w-a1"
    assert list(service.reservations) == [held.reservation_id]


def test_elapsed_time_does_not_release_and_explicit_release_is_idempotent(monkeypatch):
    service = ResourceService()
    request = ResourceRequest(ResourceKey.named("service", "deploy"), "exclusive_use")
    held = reserve(service, [request])
    monkeypatch.setattr("tsunagou.modules.resources.now_ms", lambda: held.created_at + 10**12)
    with pytest.raises(ResourceConflict):
        reserve(service, [request], "later")
    assert held.status == "active"
    assert service.release_for_attempt("a1", reason="owner_blocked") == 1
    assert held.release_reason == "owner_blocked" and held.released_at > held.created_at
    released_at = held.released_at
    assert service.release_for_attempt("a1", reason="duplicate") == 0
    assert held.released_at == released_at and held.release_reason == "owner_blocked"
    assert reserve(service, [request], "later").status == "active"


def test_repeated_reservation_requires_identical_owner_epoch_and_scope():
    service = ResourceService()
    request = ResourceRequest(ResourceKey.named("db", "migration"), "exclusive_use")
    held = reserve(service, [request])
    assert reserve(service, [request]) is held
    for change in ({"execution_epoch": 2}, {"owner_agent_id": "other"}, {"scope_digest": "other"}):
        values = dict(task_id="t-a1", attempt_id="a1", owner_agent_id="w-a1", execution_epoch=1, scope_digest="scope", requests=[request])
        with pytest.raises(PermissionError, match="reservation_context_mismatch"):
            service.reserve_set(**{**values, **change})
    assert reserve(service, []) is None


def test_root_aliases_conflict_and_distinct_named_resources_do_not():
    service = ResourceService()
    service.set_root_aliases({"root-a": "inode:1:42", "root-b": "inode:1:42"})
    reserve(service, [ResourceRequest(ResourceKey.path("root-a", "src"), "exclusive_write")])
    with pytest.raises(ResourceConflict):
        reserve(service, [ResourceRequest(ResourceKey.path("root-b", "src"), "exclusive_write")], "a2")
    reserve(service, [ResourceRequest(ResourceKey.named("db", "first"), "exclusive_use")], "a3")
    assert reserve(service, [ResourceRequest(ResourceKey.named("db", "second"), "exclusive_use")], "a4")


def test_external_observation_does_not_invent_an_owner():
    service = ResourceService()
    key = ResourceKey.path("root", "file.py")
    observed = service.observe_external(key, source="watcher", evidence={"digest": "new"}, kind="file_changed")
    assert observed.resource_key == key.canonical and not service.reservations
