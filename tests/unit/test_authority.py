from pathlib import Path

import pytest

from tsunagou.modules.authority import AuthorityService


def enroll(service: AuthorityService, installation: str, conversation: str, ready: bool = True):
    ticket = service.issue_ticket(installation, conversation)
    return service.redeem_ticket(
        ticket, installation, conversation, baseline={"baseline_ok": ready}
    )


def test_ticket_is_single_use_and_baseline_controls_degraded_state(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    ticket = service.issue_ticket("install-a", "conversation-a")
    receipt = service.redeem_ticket(ticket, "install-a", "conversation-a", baseline={"baseline_ok": False})
    assert receipt.baseline_status == "degraded"
    with pytest.raises(ValueError, match="consumed"):
        service.redeem_ticket(ticket, "install-a", "conversation-a")


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
        baseline={"baseline_ok": True},
    )
    assert rebound.connection_epoch == receipt.connection_epoch + 1
    assert service.verify_token(receipt.session_id, rebound.secret_token)
    assert receipt.secret_token not in str(service.public_snapshot())
