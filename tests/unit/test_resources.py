import pytest

from tsunagou.modules.resources import ResourceKey, ResourceRequest, ResourceService


def test_prefix_conflict_matrix_and_all_or_none() -> None:
    service = ResourceService()
    read = ResourceRequest(ResourceKey.path("root", "src"), "read")
    stable = ResourceRequest(ResourceKey.path("root", "src", "pkg"), "consistent_read")
    write = ResourceRequest(ResourceKey.path("root", "src"), "exclusive_write")
    first = service.declare_intent(
        task_id="t1", attempt_id="a1", owner_agent_id="w1", scope_digest="s",
        resources=[stable], reason="read snapshot",
    )
    lease = service.reserve_set(first.intent_id, execution_epoch=1)
    assert service.check_conflicts([read]) == []
    assert service.check_conflicts([write]) == [stable.key.canonical]
    with pytest.raises(RuntimeError):
        second = service.declare_intent(
            task_id="t2", attempt_id="a2", owner_agent_id="w2", scope_digest="s",
            resources=[write, ResourceRequest(ResourceKey.named("db", "migration"), "exclusive_use")], reason="write",
        )
        service.reserve_set(second.intent_id, execution_epoch=1)
    assert lease.status == "active"


def test_renew_requires_execution_epoch_and_expiry_keeps_external_risk(tmp_path) -> None:
    del tmp_path
    service = ResourceService(ttl_seconds=120)
    key = ResourceKey.named("service", "deploy")
    intent = service.declare_intent(
        task_id="t", attempt_id="a", owner_agent_id="w", scope_digest="scope",
        resources=[ResourceRequest(key, "exclusive_use")], reason="use",
    )
    lease = service.reserve_set(intent.intent_id, execution_epoch=3, now=100)
    with pytest.raises(PermissionError):
        service.renew(lease.lease_set_id, attempt_id="a", execution_epoch=4, scope_digest="scope", now=110)
    service.renew(lease.lease_set_id, attempt_id="a", execution_epoch=3, scope_digest="scope", now=110)
    assert service.expire_due(now=231) == [lease.lease_set_id]
    observation = service.observe_external(key, source="watcher", evidence={"owner": "unknown"}, kind="unexpected_owner")
    assert observation.kind == "unexpected_owner"


def test_blocked_attempt_has_no_lease() -> None:
    service = ResourceService()
    intent = service.declare_intent(
        task_id="t", attempt_id="a", owner_agent_id="w", scope_digest="s",
        resources=[ResourceRequest(ResourceKey.path("r", "x"), "exclusive_write")], reason="x",
    )
    with pytest.raises(ValueError, match="blocked"):
        service.reserve_set(intent.intent_id, execution_epoch=1, attempt_status="blocked")


def test_waiting_selection_ages_without_auto_start() -> None:
    service = ResourceService()
    holder = service.declare_intent(
        task_id="h", attempt_id="h", owner_agent_id="h", scope_digest="s",
        resources=[ResourceRequest(ResourceKey.named("db", "migration"), "exclusive_use")], reason="hold",
    )
    service.reserve_set(holder.intent_id, execution_epoch=1, now=0)
    waiter = service.declare_intent(
        task_id="w", attempt_id="w", owner_agent_id="w", scope_digest="s",
        resources=[ResourceRequest(ResourceKey.named("db", "migration"), "exclusive_use")], reason="wait",
    )
    with pytest.raises(RuntimeError):
        service.reserve_set(waiter.intent_id, execution_epoch=1, now=1)
    assert service.next_waiting(now=301).intent_id == waiter.intent_id
    assert all(lease.status == "active" for lease in service.lease_sets.values())


def test_physical_root_aliases_conflict_even_with_distinct_root_ids() -> None:
    service = ResourceService()
    service.set_root_aliases({"root-a": "inode:1:42", "root-b": "inode:1:42"})
    first = service.declare_intent(
        task_id="t1", attempt_id="a1", owner_agent_id="w1", scope_digest="s",
        resources=[ResourceRequest(ResourceKey.path("root-a", "src"), "exclusive_write")], reason="first",
    )
    service.reserve_set(first.intent_id, execution_epoch=1)
    second = service.declare_intent(
        task_id="t2", attempt_id="a2", owner_agent_id="w2", scope_digest="s",
        resources=[ResourceRequest(ResourceKey.path("root-b", "src"), "exclusive_write")], reason="alias",
    )
    with pytest.raises(RuntimeError, match="resource_conflict"):
        service.reserve_set(second.intent_id, execution_epoch=1)
