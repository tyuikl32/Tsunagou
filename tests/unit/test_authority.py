from pathlib import Path

import pytest

from tsunagou.modules.authority import AuthorityService
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES


def complete_baseline() -> dict[str, object]:
    """Synthetic unit fixture, not live host evidence."""
    return {"baseline": {
        name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
        for name in BASELINE_CAPABILITIES
    }}


def enroll(service: AuthorityService, installation: str, conversation: str, ready: bool = True):
    ticket = service.issue_ticket(installation, conversation)
    return service.redeem_ticket(
        ticket, installation, conversation, baseline=complete_baseline() if ready else {}
    )


def test_ticket_is_single_use_and_baseline_controls_degraded_state(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    ticket = service.issue_ticket("install-a", "conversation-a")
    assert ticket not in (tmp_path / "identity.json").read_text(encoding="utf-8")
    receipt = service.redeem_ticket(ticket, "install-a", "conversation-a", baseline={"baseline_ok": False})
    assert receipt.baseline_status == "degraded"
    assert service.agents[receipt.agent_id].status == "provisioning"
    assert not service.grants
    with pytest.raises(ValueError, match="consumed"):
        service.redeem_ticket(ticket, "install-a", "conversation-a")
    persisted = (tmp_path / "identity.json").read_text(encoding="utf-8")
    assert ticket not in persisted
    assert receipt.secret_token not in persisted
    assert receipt.reconnect_nonce not in persisted


def test_malformed_baseline_does_not_consume_ticket_or_rotate_session(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    ticket = service.issue_ticket("install", "conversation")
    with pytest.raises((TypeError, ValueError)):
        service.redeem_ticket(ticket, "install", "conversation", baseline={"invalid": object()})
    receipt = service.redeem_ticket(ticket, "install", "conversation", baseline=complete_baseline())
    with pytest.raises((TypeError, ValueError)):
        service.rebind(
            receipt.session_id, expected_nonce=receipt.reconnect_nonce,
            baseline={"invalid": object()},
        )
    assert service.verify_token(receipt.session_id, receipt.secret_token)
    assert service.sessions[receipt.session_id].connection_epoch == receipt.connection_epoch


def test_boolean_or_incomplete_baseline_cannot_grant_ready_or_main(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    ticket = service.issue_ticket("install-a", "conversation-a")
    receipt = service.redeem_ticket(ticket, "install-a", "conversation-a", baseline={"baseline_ok": True})
    assert receipt.baseline_status == "degraded"
    with pytest.raises(PermissionError, match="ready_session_required"):
        service.appoint_main(actor_kind="user_control", agent_id=receipt.agent_id)
    assert not service.grants
    upgraded = service.rebind(receipt.session_id, expected_nonce=receipt.reconnect_nonce, baseline=complete_baseline())
    assert upgraded.baseline_status == "ready"
    assert service.agents[receipt.agent_id].status == "active"
    assert len(service.grants) == 1


def test_baseline_downgrade_freezes_existing_grants(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    main = enroll(service, "install-main", "conversation-main")
    worker = enroll(service, "install-worker", "conversation-worker")
    service.appoint_main(actor_kind="user_control", agent_id=main.agent_id)
    service.appoint_main(actor_kind="user_control", agent_id=worker.agent_id)
    assert service.agents[main.agent_id].role == "worker"
    service.appoint_main(actor_kind="user_control", agent_id=main.agent_id)
    grant = service.issue_grant(
        issuer_agent_id=main.agent_id, kind="task_attempt", principal_id=worker.agent_id,
        session_id=worker.session_id, capabilities={"execution.write"},
    )
    service.rebind(worker.session_id, expected_nonce=worker.reconnect_nonce, baseline={"baseline_ok": True})
    assert service.sessions[worker.session_id].status == "degraded"
    assert service.grants[grant.grant_id].status == "revoked"
    with pytest.raises(PermissionError):
        service.authorize(
            agent_id=worker.agent_id, session_id=worker.session_id, grant_id=grant.grant_id,
            capability="execution.write",
        )


def test_user_only_main_and_exact_attempt_grant(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    main = enroll(service, "install-main", "conversation-main")
    worker = enroll(service, "install-worker", "conversation-worker")
    with pytest.raises(PermissionError, match="user_only"):
        service.appoint_main(actor_kind="agent", agent_id=main.agent_id)
    service.appoint_main(actor_kind="user_control", agent_id=main.agent_id)
    with pytest.raises(PermissionError, match="main_authority"):
        service.issue_grant(
            issuer_agent_id=worker.agent_id, kind="task_attempt", principal_id=worker.agent_id,
            attempt_id="attempt-1", capabilities={"execution.write"},
        )
    grant = service.issue_grant(
        issuer_agent_id=main.agent_id, kind="task_attempt", principal_id=worker.agent_id,
        session_id=worker.session_id, task_id="task-1", attempt_id="attempt-1",
        execution_epoch=2, capabilities={"execution.write"},
    )
    assert service.authorize(
        agent_id=worker.agent_id, session_id=worker.session_id, grant_id=grant.grant_id,
        capability="execution.write", task_id="task-1", attempt_id="attempt-1",
    ) == grant
    with pytest.raises(PermissionError, match="attempt_scope"):
        service.authorize(
            agent_id=worker.agent_id, session_id=worker.session_id, grant_id=grant.grant_id,
            capability="execution.write", task_id="task-1", attempt_id="other",
        )


def test_rebind_rotates_connection_epoch_without_exposing_token_in_snapshot(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    receipt = enroll(service, "install", "conversation")
    with pytest.raises(PermissionError, match="nonce"):
        service.rebind(receipt.session_id, expected_nonce="stale")
    rebound = service.rebind(
        receipt.session_id, expected_nonce=receipt.reconnect_nonce,
        baseline=complete_baseline(),
    )
    assert rebound.connection_epoch == receipt.connection_epoch + 1
    assert service.verify_token(receipt.session_id, rebound.secret_token)
    assert receipt.secret_token not in str(service.public_snapshot())


def test_each_conversation_is_a_distinct_worker_even_with_same_installation() -> None:
    service = AuthorityService(None)
    first = enroll(service, "same-ide", "conversation-a")
    second = enroll(service, "same-ide", "conversation-b")

    assert first.agent_id != second.agent_id
    assert first.session_id != second.session_id
    assert service.agents[first.agent_id].conversation_digest != service.agents[second.agent_id].conversation_digest


def test_rebind_cannot_retarget_another_conversation_agent() -> None:
    service = AuthorityService(None)
    first = enroll(service, "same-ide", "conversation-a")
    ticket = service.issue_ticket("same-ide", "conversation-b")

    with pytest.raises(ValueError, match="session_not_rebindable"):
        service.redeem_rebind_ticket(
            ticket, "same-ide", "conversation-b", target_agent_id=first.agent_id,
        )
