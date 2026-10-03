from pathlib import Path

import pytest

from tsunagou.modules.authority import MAX_EVIDENCE_REF_LENGTH, MAX_EVIDENCE_REFS, AuthorityService
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


def test_requested_main_role_is_applied_by_daemon_after_ticket_redeem(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    ticket = service.issue_ticket("install-main", "conversation-main", requested_role="main")
    receipt = service.redeem_ticket(
        ticket, "install-main", "conversation-main", baseline=complete_baseline(),
    )
    assert service.main_agent_id == receipt.agent_id
    assert service.agents[receipt.agent_id].role == "main"
    assert service.agents[receipt.agent_id].requested_role == "worker"


def test_requested_main_role_waits_until_session_is_ready(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    ticket = service.issue_ticket("install-main", "conversation-main", requested_role="main")
    receipt = service.redeem_ticket(ticket, "install-main", "conversation-main", baseline={})
    assert service.main_agent_id is None
    service.rebind(receipt.session_id, expected_nonce=receipt.reconnect_nonce, baseline=complete_baseline())
    assert service.main_agent_id == receipt.agent_id


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


def test_retiring_an_agent_takes_away_everything_that_lets_it_act(tmp_path: Path) -> None:
    """退役 = 他从此不能再动：会话结束、凭据作废、授权收回、代次递增；记录留着。"""

    service = AuthorityService(tmp_path / "identity.json")
    main = enroll(service, "install-main", "conversation-main")
    worker = enroll(service, "install-worker", "conversation-worker")
    service.appoint_main(actor_kind="user_control", agent_id=main.agent_id)
    epoch = service.authority_epoch

    summary = service.retire_agent(actor_kind="user_control", agent_id=worker.agent_id)

    assert summary["agent_id"] == worker.agent_id and summary["status"] == "retired"
    assert summary["stopped_sessions"] == 1 and summary["revoked_grants"] >= 1
    assert service.agents[worker.agent_id].status == "retired"
    assert not service.verify_token(worker.session_id, worker.secret_token), "凭据立即失效"
    assert service.sessions[worker.session_id].status == "ended"
    assert not [g for g in service.grants.values()
                if g.principal_id == worker.agent_id and g.status == "active"], "授权全部收回"
    assert service.authority_epoch == epoch + 1, "权威变了，这件事对所有人可见"
    assert service.main_agent_id == main.agent_id, "主 Agent 不受影响"
    assert service.retire_agent(actor_kind="user_control", agent_id=worker.agent_id)["status"] == "retired"


def test_a_retired_agent_is_told_it_was_retired(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    main = enroll(service, "install-main", "conversation-main")
    worker = enroll(service, "install-worker", "conversation-worker")
    service.appoint_main(actor_kind="user_control", agent_id=main.agent_id)
    grant = service.find_grant(agent_id=worker.agent_id, capability="coordination.read", session_id=worker.session_id)
    assert grant is not None
    service.retire_agent(actor_kind="user_control", agent_id=worker.agent_id)

    with pytest.raises(PermissionError, match="agent_retired"):
        service.authorize(
            agent_id=worker.agent_id, session_id=worker.session_id, grant_id=grant.grant_id,
            capability="coordination.read",
        )


def test_the_current_main_agent_cannot_be_retired(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    main = enroll(service, "install-main", "conversation-main")
    service.appoint_main(actor_kind="user_control", agent_id=main.agent_id)

    with pytest.raises(PermissionError, match="main_agent_cannot_retire"):
        service.retire_agent(actor_kind="user_control", agent_id=main.agent_id)

    assert service.agents[main.agent_id].status == "active", "拒绝就是什么都没发生"
    assert service.main_agent_id == main.agent_id


def test_only_the_user_can_retire(tmp_path: Path) -> None:
    service = AuthorityService(tmp_path / "identity.json")
    main = enroll(service, "install-main", "conversation-main")
    worker = enroll(service, "install-worker", "conversation-worker")
    service.appoint_main(actor_kind="user_control", agent_id=main.agent_id)
    with pytest.raises(PermissionError, match="user_only"):
        service.retire_agent(actor_kind="agent", agent_id=worker.agent_id)
    assert service.agents[worker.agent_id].status == "active"


def test_a_remote_agent_cannot_be_appointed_main(tmp_path: Path) -> None:
    """主 Agent 得和协调中心同一台机器：远端入席时自报了机器名，只能当子 Agent。"""

    service = AuthorityService(tmp_path / "identity.json")
    local = enroll(service, "install-local", "conversation-local")
    remote = enroll(service, "install-remote", "conversation-remote")
    service.agents[remote.agent_id].machine = "工位-九"

    service.appoint_main(actor_kind="user_control", agent_id=local.agent_id)
    with pytest.raises(PermissionError, match="main_agent_must_be_local"):
        service.appoint_main(actor_kind="user_control", agent_id=remote.agent_id)

    assert service.main_agent_id == local.agent_id, "拒绝之后原来的主 Agent 不许动"
    assert service.agents[local.agent_id].role == "main"
    assert service.agents[remote.agent_id].role == "worker"


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


def test_a_session_keeps_which_capabilities_it_proved(tmp_path: Path) -> None:
    """准入时的那份自报留在会话里，页面才算得出"缺哪几项"。

    留的是**行**（状态 + 引用），而且有上限：引用最多 8 条、每条截到 200 字符，空引用丢掉，
    11 项以外的名字一个不收。会话文件不是宿主回执的回收站，也不能长到没人敢读。
    """
    service = AuthorityService(tmp_path / "identity.json")
    baseline = complete_baseline()
    baseline["baseline"]["identity.session_isolation"] = {
        "status": "supported",
        "evidence_refs": ["x" * (MAX_EVIDENCE_REF_LENGTH + 50)]
        + [f"ref:{index}" for index in range(10)],
    }
    # 一份"写了 status 但引用是空白"的行：准入规则不认它（所以它缺），
    # 会话留的那份行照样只收有效引用 —— 留下的是"能拿出来看的证据"。
    baseline["baseline"]["delivery.deduplicate"] = {
        "status": "supported", "evidence_refs": ["", "   "],
    }
    baseline["baseline"]["made.up"] = {"status": "supported", "evidence_refs": ["nope"]}

    receipt = service.redeem_ticket(
        service.issue_ticket("install-a", "conversation-a"), "install-a", "conversation-a",
        baseline=baseline,
    )

    stored = service.sessions[receipt.session_id].baseline
    assert stored["status"] == "ready"
    assert isinstance(stored["digest"], str) and stored["digest"]
    rows = stored["capabilities"]
    assert set(rows) == set(BASELINE_CAPABILITIES)
    assert rows["identity.session_isolation"]["status"] == "supported"
    refs = rows["identity.session_isolation"]["evidence_refs"]
    assert len(refs) == MAX_EVIDENCE_REFS
    assert refs[0] == "x" * MAX_EVIDENCE_REF_LENGTH
    assert all(ref.strip() for ref in refs)
    assert rows["delivery.deduplicate"]["evidence_refs"] == []


def test_rebinding_replaces_the_stored_rows_instead_of_adding_to_them(tmp_path: Path) -> None:
    """换一份自报就是换一份事实：升级要如实记，降级也要如实记。"""
    service = AuthorityService(tmp_path / "identity.json")
    ticket = service.issue_ticket("install-a", "conversation-a")
    receipt = service.redeem_ticket(ticket, "install-a", "conversation-a", baseline={})
    assert service.sessions[receipt.session_id].baseline["capabilities"] == {}

    upgraded = service.rebind(
        receipt.session_id, expected_nonce=receipt.reconnect_nonce, baseline=complete_baseline(),
    )
    assert set(service.sessions[receipt.session_id].baseline["capabilities"]) == set(BASELINE_CAPABILITIES)

    one_row = {"baseline": {
        "identity.session_isolation": {"status": "supported", "evidence_refs": ["fixture:only"]},
    }}
    service.rebind(receipt.session_id, expected_nonce=upgraded.reconnect_nonce, baseline=one_row)
    stored = service.sessions[receipt.session_id].baseline
    assert set(stored["capabilities"]) == {"identity.session_isolation"}
    assert stored["status"] == "degraded"
