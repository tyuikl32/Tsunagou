from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest, create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import build_handlers
from tsunagou.bootstrap.container import build_application
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.shared_kernel.baseline import (
    ADMISSION_CAPABILITIES,
    BASELINE_CAPABILITIES,
    missing_baseline_capabilities,
)
from tsunagou.shared_kernel.errors import CommandRefused

ROOT = Path(__file__).parents[2]


def complete_baseline() -> dict[str, Any]:
    return {"baseline": {name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]} for name in BASELINE_CAPABILITIES}}


def _endpoint(app: Any) -> Any:
    return next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")


def _request(payload: dict[str, Any]) -> CommandRequest:
    return CommandRequest(command_id="c", protocol_version="1", schema_bundle_digest="sha256:x", payload=payload)


def _app(tmp_path: Path, *, control_token: str | None = None) -> tuple[Any, AuthorityService]:
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    authority = AuthorityService(tmp_path / "identity.json")
    for kind, handler in build_handlers(authority=authority).items():
        dispatcher.register(kind, handler)
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator(authority=authority, control_token=control_token))
    return app, authority


def _enroll_payload() -> dict[str, Any]:
    return {
        "installation_id": "install-a",
        "conversation_evidence": {"conversation_id": "conversation-a"},
        "probe_payload": complete_baseline(),
    }


def test_enroll_t_principal_reaches_redeem_ticket(tmp_path: Path) -> None:
    app, authority = _app(tmp_path)
    ticket = authority.issue_ticket("install-a", "conversation-a")
    result = _endpoint(app)("agent.enroll", _request(_enroll_payload()), Response(), f"Bearer {ticket}", None, None)
    body = result["result"]
    assert body["baseline_status"] == "ready"
    assert body["agent_id"] in authority.agents
    assert authority.verify_token(body["session_id"], body["secret_token"])


def test_enroll_ticket_is_single_use_and_mismatch_fails_closed(tmp_path: Path) -> None:
    app, authority = _app(tmp_path)
    ticket = authority.issue_ticket("install-a", "conversation-a")
    endpoint = _endpoint(app)
    endpoint("agent.enroll", _request(_enroll_payload()), Response(), f"Bearer {ticket}", None, None)
    with pytest.raises(HTTPException) as exc:
        endpoint("agent.enroll", _request(_enroll_payload()), Response(), f"Bearer {ticket}", None, None)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "invalid_or_consumed_enrollment_ticket"


def test_enroll_requires_authority_and_conversation_identity(tmp_path: Path) -> None:
    # A T bearer without a configured authority must fail closed, not resolve an identity.
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator())
    with pytest.raises(HTTPException) as exc:
        _endpoint(app)("agent.enroll", _request(_enroll_payload()), Response(), "Bearer whatever", None, None)
    assert exc.value.status_code == 401


def test_issue_user_ticket_returns_redeemable_secret(tmp_path: Path) -> None:
    app, authority = _app(tmp_path, control_token="ctl")
    result = _endpoint(app)(
        "agent.ticket.create.user",
        _request({"kind": "worker", "installation_id": "install-a", "conversation_evidence": {"conversation_id": "conversation-a"}}),
        Response(),
        "Bearer ctl",
        None,
        None,
    )
    secret = result["result"]["secret"]
    assert secret
    receipt = authority.redeem_ticket(secret, "install-a", "conversation-a", baseline=complete_baseline())
    assert receipt.baseline_status == "ready"


def test_issue_user_ticket_can_request_main_without_agent_id(tmp_path: Path) -> None:
    app, authority = _app(tmp_path, control_token="ctl")
    result = _endpoint(app)(
        "agent.ticket.create.user",
        _request(
            {
                "kind": "worker",
                "role": "main",
                "installation_id": "install-main",
                "conversation_evidence": {"conversation_id": "conversation-main"},
            }
        ),
        Response(),
        "Bearer ctl",
        None,
        None,
    )
    secret = result["result"]["secret"]
    receipt = authority.redeem_ticket(
        secret,
        "install-main",
        "conversation-main",
        baseline=complete_baseline(),
    )
    assert result["result"]["requested_role"] == "main"
    assert authority.main_agent_id == receipt.agent_id


def test_appoint_requires_ready_session(tmp_path: Path) -> None:
    app, authority = _app(tmp_path, control_token="ctl")
    endpoint = _endpoint(app)
    degraded = authority.redeem_ticket(authority.issue_ticket("install-a", "conversation-a"), "install-a", "conversation-a", baseline={})
    with pytest.raises(HTTPException) as exc:
        endpoint("authority.appoint", _request({"agent_id": degraded.agent_id}), Response(), "Bearer ctl", None, None)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ready_session_required"

    ready = authority.redeem_ticket(
        authority.issue_ticket("install-b", "conversation-b"), "install-b", "conversation-b", baseline=complete_baseline()
    )
    result = endpoint("authority.appoint", _request({"agent_id": ready.agent_id}), Response(), "Bearer ctl", None, None)
    assert result["result"]["main_agent_id"] == ready.agent_id
    assert authority.main_agent_id == ready.agent_id


def test_appoint_refuses_a_remote_agent(tmp_path: Path) -> None:
    """跨机器入席的人自报了机器名 → 不能当主 Agent（主 Agent 必须和协调中心同机）。"""

    app, authority = _app(tmp_path, control_token="ctl")
    endpoint = _endpoint(app)
    local = authority.redeem_ticket(
        authority.issue_ticket("install-local", "conversation-local"),
        "install-local", "conversation-local", baseline=complete_baseline(),
    )
    remote = authority.redeem_ticket(
        authority.issue_ticket("install-remote", "conversation-remote"),
        "install-remote", "conversation-remote", baseline=complete_baseline(),
    )
    authority.agents[remote.agent_id].machine = "工位-九"

    endpoint("authority.appoint", _request({"agent_id": local.agent_id}), Response(), "Bearer ctl", None, None)
    with pytest.raises(HTTPException) as exc:
        endpoint("authority.appoint", _request({"agent_id": remote.agent_id}), Response(), "Bearer ctl", None, None)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "main_agent_must_be_local"
    assert authority.main_agent_id == local.agent_id, "拒绝之后原来的主 Agent 不许动"


def test_retire_takes_the_agent_out_of_service_and_refuses_the_main(tmp_path: Path) -> None:
    """退役走用户命令：普通成员能退，当前主 Agent 被拒（项目永远得有一个主 Agent）。"""

    app, authority = _app(tmp_path, control_token="ctl")
    endpoint = _endpoint(app)
    main = authority.redeem_ticket(
        authority.issue_ticket("install-main", "conversation-main"),
        "install-main", "conversation-main", baseline=complete_baseline(),
    )
    worker = authority.redeem_ticket(
        authority.issue_ticket("install-worker", "conversation-worker"),
        "install-worker", "conversation-worker", baseline=complete_baseline(),
    )
    endpoint("authority.appoint", _request({"agent_id": main.agent_id}), Response(), "Bearer ctl", None, None)

    result = endpoint(
        "agent.retire.user", _request({"agent_id": worker.agent_id, "reason": "test"}),
        Response(), "Bearer ctl", None, None,
    )
    assert result["result"]["status"] == "retired"
    assert authority.agents[worker.agent_id].status == "retired"
    assert not authority.verify_token(worker.session_id, worker.secret_token)

    with pytest.raises(HTTPException) as exc:
        endpoint(
            "agent.retire.user", _request({"agent_id": main.agent_id}),
            Response(), "Bearer ctl", None, None,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "main_agent_cannot_retire"
    assert authority.main_agent_id == main.agent_id


def test_a_refusal_carries_the_facts_the_page_has_to_show(tmp_path: Path) -> None:
    """拒绝时把事实一起给出去（"他手上还有这些任务"）：页面照着列，不用自己编话。"""

    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    authority = AuthorityService(tmp_path / "identity.json")
    for kind, handler in build_handlers(authority=authority).items():
        dispatcher.register(kind, handler)

    def refuse(_payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        raise CommandRefused("agent_has_open_work", {"tasks": [{"task_id": "t-1", "title": "改登录"}]})

    dispatcher.register("agent.retire.user", refuse)
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator(authority=authority, control_token="ctl"))
    endpoint = _endpoint(app)

    with pytest.raises(HTTPException) as exc:
        endpoint("agent.retire.user", _request({"agent_id": "a-1"}), Response(), "Bearer ctl", None, None)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "agent_has_open_work"
    assert exc.value.detail["tasks"] == [{"task_id": "t-1", "title": "改登录"}]


def test_build_application_full_enrollment_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "ctl")
    endpoint = _endpoint(build_application())
    issued = endpoint(
        "agent.ticket.create.user",
        _request({"kind": "worker", "installation_id": "install-a", "conversation_evidence": {"conversation_id": "conversation-a"}}),
        Response(),
        "Bearer ctl",
        None,
        None,
    )
    secret = issued["result"]["secret"]
    enrolled = endpoint(
        "agent.enroll",
        _request(_enroll_payload()),
        Response(),
        f"Bearer {secret}",
        None,
        None,
    )
    assert enrolled["result"]["baseline_status"] == "ready"


def test_build_application_fails_closed_without_control_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("TSUNAGOU_CONTROL_TOKEN", raising=False)
    endpoint = _endpoint(build_application())
    with pytest.raises(HTTPException) as exc:
        endpoint(
            "agent.ticket.create.user",
            _request({"kind": "worker", "installation_id": "i", "conversation_evidence": {"conversation_id": "c"}}),
            Response(),
            "Bearer whatever",
            None,
            None,
        )
    assert exc.value.status_code == 401


def _admission_baseline() -> dict[str, Any]:
    return {"baseline": {name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]} for name in ADMISSION_CAPABILITIES}}


def test_admission_only_baseline_grants_ready_and_b_auth(tmp_path: Path) -> None:
    # Direction 4: the 4 pre-enrollment rows are enough to become ready and to
    # authenticate a B session, breaking the degraded->ready deadlock.
    _app_result, authority = _app(tmp_path)
    ticket = authority.issue_ticket("install-a", "conversation-a")
    receipt = authority.redeem_ticket(ticket, "install-a", "conversation-a", baseline=_admission_baseline())
    assert receipt.baseline_status == "ready"
    principal = LocalCommandAuthenticator(authority=authority).authenticate(
        "B",
        f"Bearer {receipt.secret_token}",
        session_id=receipt.session_id,
        connection_epoch=receipt.connection_epoch,
    )
    assert principal.principal_id == receipt.agent_id


def test_full_baseline_still_required_by_release_gate(tmp_path: Path) -> None:
    # The release gate keeps requiring all 11 rows; an admission-only baseline is
    # ready for a session but still misses the 7 operational rows for release.
    missing = missing_baseline_capabilities(_admission_baseline())
    assert set(missing) == set(name for name in BASELINE_CAPABILITIES if name not in ADMISSION_CAPABILITIES)
    assert len(missing) == len(BASELINE_CAPABILITIES) - len(ADMISSION_CAPABILITIES)


def test_review_changes_requested_closes_execution_lease_and_grant() -> None:
    """A rejected result cannot keep using the previous execution credential."""
    from tsunagou.application.handlers import build_handlers
    from tsunagou.modules.resources import ResourceKey, ResourceRequest, ResourceService
    from tsunagou.modules.tasks import TaskService

    authority = AuthorityService(None)
    main = authority.redeem_ticket(
        authority.issue_ticket("review-main", "review-main-conversation"),
        "review-main",
        "review-main-conversation",
        baseline=complete_baseline(),
    )
    worker = authority.redeem_ticket(
        authority.issue_ticket("review-worker", "review-worker-conversation"),
        "review-worker",
        "review-worker-conversation",
        baseline=complete_baseline(),
    )
    authority.appoint_main(actor_kind="user_control", agent_id=main.agent_id)
    tasks = TaskService()
    resources = ResourceService()
    task = tasks.create_task("review", "return changes")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    attempt = tasks.claim(task.task_id, worker.agent_id)
    preflight = tasks.preflight(task.task_id, worker.agent_id, attempt_id=attempt.attempt_id)
    tasks.start(task.task_id, worker.agent_id, preflight_id=preflight.preflight_id, require_preflight=True)
    grant = authority.issue_execution_grant(
        agent_id=worker.agent_id,
        session_id=worker.session_id,
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
    )
    reservation = resources.reserve_set(
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        owner_agent_id=worker.agent_id,
        execution_epoch=attempt.execution_epoch,
        scope_digest="review-scope",
        requests=[ResourceRequest(ResourceKey.path("root", "file.py"), "exclusive_write")],
    )
    result = tasks.submit(task.task_id, worker.agent_id, {"summary": "needs changes"})
    authority.issue_grant(
        issuer_agent_id=main.agent_id,
        kind="task_review",
        principal_id=main.agent_id,
        session_id=main.session_id,
        task_id=task.task_id,
        capabilities={"task.review"},
    )

    handlers = build_handlers(authority=authority, tasks=tasks, resources=resources)
    reviewed = handlers["task.review.request_changes"](
        {"task_id": task.task_id, "result_id": result.result_id, "result_digest": result.digest},
        {"kind": "M", "principal_id": main.agent_id, "session_id": main.session_id, "command_id": "review"},
    )

    assert reviewed["status"] == "changes_requested"
    assert tasks.tasks[task.task_id].current_attempt_id is None
    assert tasks.attempts[attempt.attempt_id].status == "orphaned"
    assert resources.reservations[reservation.reservation_id].status == "released"
    assert authority.grants[grant.grant_id].status == "revoked"


def test_task_resource_requests_come_from_main_scope():
    from tsunagou.application.workflows.execution_commands import ExecutionCommands
    from tsunagou.modules.tasks import Task

    task = Task(
        "task",
        "scoped",
        "write",
        execution_scope={
            "resources": [
                {"kind": "path", "root_id": "root", "segments": ["src"], "mode": "exclusive_write"},
            ]
        },
    )
    requests = ExecutionCommands.requests(task)
    assert len(requests) == 1 and requests[0].key.segments == ("src",)
    task.execution_scope["resources"][0]["segments"] = ["..", "outside"]
    with pytest.raises(ValueError, match="invalid_path_resource"):
        ExecutionCommands.requests(task)
