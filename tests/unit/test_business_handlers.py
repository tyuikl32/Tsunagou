from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Response
from jsonschema import Draft202012Validator

from tsunagou.api.app import CommandRequest, create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import build_handlers
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.tasks import TaskService
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES

ROOT = Path(__file__).parents[2]


def _admission_baseline() -> dict[str, Any]:
    return {"baseline": {
        name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
        for name in ADMISSION_CAPABILITIES
    }}


def _request(payload: dict[str, Any], *, command_id: str = "c") -> CommandRequest:
    return CommandRequest(command_id=command_id, protocol_version="1", schema_bundle_digest="sha256:x", payload=payload)


def _harness(
    tmp_path: Path,
    *,
    project_id: str | None = None,
) -> tuple[Any, AuthorityService, TaskService, CognitionService, MessageStore, Any]:
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    authority = AuthorityService(tmp_path / "identity.json")
    tasks = TaskService()
    cognition = CognitionService()
    messages = MessageStore()
    preparers = {}
    for kind, handler in build_handlers(
        authority=authority, tasks=tasks, cognition=cognition, messages=messages,
        project_id=project_id, preparers=preparers,
    ).items():
        dispatcher.register(kind, handler)
    for kind, prepare in preparers.items():
        dispatcher.register_preparer(kind, prepare)
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator(authority=authority))
    endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", "") == "/api/v1/commands/{command_kind}"
    )
    return app, authority, tasks, cognition, messages, endpoint


def _enroll_ready(authority: AuthorityService, *, installation: str, conversation: str) -> Any:
    ticket = authority.issue_ticket(installation, conversation)
    return authority.redeem_ticket(ticket, installation, conversation, baseline=_admission_baseline())


def _call(
    endpoint: Any, kind: str, payload: dict[str, Any], receipt: Any, *, command_id: str = "c"
) -> dict[str, Any]:
    return endpoint(
        kind, _request(payload, command_id=command_id), Response(),
        f"Bearer {receipt.secret_token}", receipt.session_id, receipt.connection_epoch,
    )["result"]


def _open_task(tasks: TaskService, title: str = "t") -> str:
    task = tasks.create_task(title, "objective")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    return task.task_id


def test_task_lifecycle_begin_progress_submit(tmp_path: Path) -> None:
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)
    started = _call(endpoint, "task.begin", {"task_id": task_id, "expected_task_revision": tasks.tasks[task_id].revision}, receipt)
    assert started["status"] == "running"
    attempt_id = started["attempt_id"]
    progressed = _call(endpoint, "task.progress", {
        "task_id": task_id, "attempt_id": attempt_id, "summary": "halfway", "evidence_refs": [],
    }, receipt)
    assert progressed["progress_id"] in tasks.progress_records
    submitted = _call(endpoint, "task.submit", {"task_id": task_id, "attempt_id": attempt_id, "summary": "done"}, receipt)
    assert submitted["result_id"] and tasks.tasks[task_id].status == "submitted"


def test_task_begin_rejects_stale_revision(tmp_path: Path) -> None:
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)
    with pytest.raises(HTTPException) as exc:
        _call(endpoint, "task.begin", {"task_id": task_id, "expected_task_revision": 0}, receipt)
    assert exc.value.status_code == 409
    assert tasks.tasks[task_id].status == "open" and not tasks.attempts


def test_task_submit_fails_closed_without_execution_grant(tmp_path: Path) -> None:
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)
    attempt = tasks.claim(task_id, receipt.agent_id)
    tasks.start(task_id, receipt.agent_id)
    with pytest.raises(HTTPException) as exc:
        _call(endpoint, "task.submit", {"task_id": task_id, "attempt_id": attempt.attempt_id, "summary": "done"}, receipt)
    assert exc.value.status_code == 403 and exc.value.detail["code"] == "capability_denied"


def test_cognition_report_roundtrip(tmp_path: Path) -> None:
    _, authority, _, cognition, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    report = _call(endpoint, "cognition.report", {
        "task_id": "t1", "attempt_id": "a1",
        "claims": [{"subject_key": "s", "claim_type": "literal", "equality_key": "s", "value": "v", "evidence_refs": ["e"]}],
        "uncertainties": [], "assumptions": [],
    }, receipt)
    assert report["report_id"] in cognition.reports


def test_cognition_report_rejects_string_claims(tmp_path: Path) -> None:
    # The bridge schema now declares claims as objects; the backend must still
    # reject a string element outright (this is the invalid_claim the real Codex
    # run hit before the schema fix).
    _, authority, _, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    with pytest.raises(HTTPException) as exc:
        _call(endpoint, "cognition.report", {
            "task_id": "t1", "attempt_id": "a1", "claims": ["not-an-object"],
        }, receipt)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "invalid_claim"


def test_a_report_keeps_the_contract_version_it_was_written_under(tmp_path: Path) -> None:
    """A report's declared premises used to be dropped by the handler, so "these two
    reports were written under different agreements" could not be answered at all.

    The declaration is kept, and one that no longer matches what is in force becomes a
    hard disagreement instead of a silent assumption.
    """
    _, authority, tasks, cognition, _, endpoint = _harness(tmp_path)
    agent = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)

    def propose(payload: dict[str, Any], supersedes_id: str = "") -> dict[str, Any]:
        return _call(endpoint, "contract.propose", {
            "contract_id": "api", "contract_kind": "interface", "payload": payload,
            "participants_required": [{"slot": "self", "agent_id": agent.agent_id}],
            "participants_optional": [], "subject_ref": task_id, "input_refs": [],
            "supersedes_id": supersedes_id,
        }, agent)

    def accept(proposal: dict[str, Any]) -> None:
        _call(endpoint, "contract.accept", {
            "proposal_id": proposal["proposal_id"], "participant_slot": "self",
            "proposal_digest": proposal["digest"], "evidence_refs": [],
        }, agent)

    def report(revisions: Any = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"task_id": task_id, "attempt_id": "a1", "claims": []}
        if revisions is not None:
            payload["input_revisions"] = revisions
        return _call(endpoint, "cognition.report", payload, agent)

    agreed = propose({"task_id": task_id, "label": "接口契约 v1"})
    accept(agreed)
    in_force = [f"{agreed['proposal_id']}:{agreed['digest']}"]

    settled = report({"contract": in_force})
    assert cognition.reports[settled["report_id"]].input_revisions == {"contract": in_force}
    assert cognition.discrepancies == {}

    # A revision moves what is in force, so a report still declaring the old version is
    # exactly the "someone is working from the outdated agreement" case.
    revision = propose({"task_id": task_id, "label": "接口契约 v2"}, agreed["proposal_id"])
    accept(revision)
    drifted = report({"contract": in_force})
    assert cognition.reports[drifted["report_id"]].input_revisions == {"contract": in_force}

    (discrepancy,) = cognition.discrepancies.values()
    assert discrepancy.rule_id == "claim.contract_digest_mismatch"
    assert discrepancy.severity == "hard"
    assert discrepancy.subject_key == task_id

    with pytest.raises(HTTPException) as refusal:
        report("not-an-object")
    assert refusal.value.detail["code"] == "input_revisions_object_required"


def test_contract_propose_accept_roundtrip(tmp_path: Path) -> None:
    _, authority, _, cognition, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    proposed = _call(endpoint, "contract.propose", {
        "contract_id": "c1", "contract_kind": "kind", "payload": {"x": 1},
        "participants_required": [{"slot": "self", "agent_id": receipt.agent_id}],
        "participants_optional": [], "subject_ref": "s", "input_refs": [],
    }, receipt)
    accepted = _call(endpoint, "contract.accept", {
        "proposal_id": proposed["proposal_id"], "participant_slot": "self",
        "proposal_digest": proposed["digest"], "evidence_refs": [],
    }, receipt)
    assert accepted["status"] == "accepted"
    assert cognition.proposals[proposed["proposal_id"]].status == "accepted"


def test_a_contract_proposal_asks_its_required_slots_to_answer(tmp_path: Path) -> None:
    """Proposing has to reach the people who must agree.

    Acceptances only ever happen if a slot learns it is waiting, so the daemon tells
    the required slots itself (they are mechanically derivable) and attaches a response
    obligation whose answer must quote the digest it answers — "I read it" becomes a
    checkable fact instead of a claim.
    """
    _, authority, _, cognition, _, endpoint = _harness(tmp_path)
    proposer = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    peer = _enroll_ready(authority, installation="install-b", conversation="conversation-b")

    proposed = _call(endpoint, "contract.propose", {
        "contract_id": "api", "contract_kind": "interface", "payload": {"x": 1},
        "participants_required": [{"slot": "peer", "agent_id": peer.agent_id}],
        "participants_optional": [], "subject_ref": "s", "input_refs": [], "supersedes_id": "",
    }, proposer)

    claimed = _call(endpoint, "inbox.claim", {"limit": 10}, peer)
    assert claimed["count"] == 1
    notice = claimed["messages"][0]
    assert notice["kind"] == "contract.proposed"
    assert notice["sender_agent_id"] == proposer.agent_id
    assert notice["subject_ref"] == proposed["proposal_id"]
    obligation = notice["response_obligations"][0]
    assert obligation["status"] == "open"
    assert obligation["contract"]["required"] is True

    wrong = _call(endpoint, "message.send", {
        "recipient_agent_id": proposer.agent_id, "kind": "message", "summary": "ack",
        "in_reply_to": notice["message_id"],
        "payload": {"proposal_id": proposed["proposal_id"], "proposal_digest": "stale",
                    "decision": "accept"},
    }, peer, command_id="reply-stale")
    with pytest.raises(HTTPException) as failure:
        _call(endpoint, "message.respond", {
            "obligation_id": obligation["obligation_id"],
            "response_message_id": wrong["message_id"],
        }, peer)
    assert failure.value.detail["code"] == "response_schema_violation"

    right = _call(endpoint, "message.send", {
        "recipient_agent_id": proposer.agent_id, "kind": "message", "summary": "accepted",
        "in_reply_to": notice["message_id"],
        "payload": {"proposal_id": proposed["proposal_id"], "proposal_digest": proposed["digest"],
                    "decision": "accept"},
    }, peer, command_id="reply-read")
    answered = _call(endpoint, "message.respond", {
        "obligation_id": obligation["obligation_id"],
        "response_message_id": right["message_id"],
    }, peer)
    assert answered["status"] == "responded"
    # Answering is not agreeing: the contract still needs the command that changes it.
    assert cognition.proposals[proposed["proposal_id"]].status == "proposed"


def test_begin_refuses_a_contract_that_is_not_settled(tmp_path: Path) -> None:
    """Starting work is where "which contract version governs" has to be settled.

    A task declares the contracts it depends on by naming itself in their payload. While a
    declared contract has nothing accepted yet, or a revision is still under discussion,
    the start boundary is held: otherwise the work would begin from a version that can
    still move. Accepting it is the way out, and the console reads the same facts back
    through ``context.project_read``.
    """
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    agent = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)

    def propose(label: str, supersedes_id: str = "") -> dict[str, Any]:
        return _call(endpoint, "contract.propose", {
            "contract_id": "api", "contract_kind": "interface",
            "payload": {"task_id": task_id, "label": label},
            "participants_required": [{"slot": "self", "agent_id": agent.agent_id}],
            "participants_optional": [], "subject_ref": task_id, "input_refs": [],
            "supersedes_id": supersedes_id,
        }, agent)

    def accept(proposal: dict[str, Any]) -> None:
        _call(endpoint, "contract.accept", {
            "proposal_id": proposal["proposal_id"], "participant_slot": "self",
            "proposal_digest": proposal["digest"], "evidence_refs": [],
        }, agent)

    def begin() -> dict[str, Any]:
        return _call(endpoint, "task.begin", {
            "task_id": task_id, "expected_task_revision": tasks.tasks[task_id].revision,
        }, agent)

    agreed = propose("接口契约 v1")
    with pytest.raises(HTTPException) as failure:
        begin()
    assert failure.value.detail["code"] == "contract_not_accepted"

    accept(agreed)
    assert begin()["status"] == "running"

    # A revision retires its predecessor on the spot (contract.supersede), so nothing is
    # in force again until the revision is accepted — which is exactly why both boundaries
    # hold while one is under discussion.
    revision = propose("接口契约 v2", agreed["proposal_id"])
    with pytest.raises(HTTPException) as failure:
        begin()
    assert failure.value.detail["code"] == "contract_not_accepted"

    view = _call(endpoint, "context.project_read", {}, agent)
    entry = view["contracts"]["tasks"][0]
    assert entry["task_id"] == task_id
    assert entry["in_force"] == []
    by_status = {item["status"]: item for item in entry["proposals"]}
    assert by_status["proposed"]["payload"] == {"task_id": task_id, "label": "接口契约 v2"}
    assert by_status["proposed"]["supersedes_id"] == agreed["proposal_id"]
    assert by_status["superseded"]["payload"] == {"task_id": task_id, "label": "接口契约 v1"}

    accept(revision)
    view = _call(endpoint, "context.project_read", {}, agent)
    entry = view["contracts"]["tasks"][0]
    assert entry["in_force"] == [f"{revision['proposal_id']}:{revision['digest']}"]
    assert {item["status"] for item in entry["proposals"]} == {"accepted", "superseded"}
    assert len(view["contracts"]["participating"]) == 2


def test_the_boundaries_refuse_a_contract_version_that_is_not_in_force(tmp_path: Path) -> None:
    """"Settled" is not enough: both execution boundaries also ask whether the version the
    caller read is the one that governs.

    A worker can be right in the middle of a long turn when a revision it is not party to
    lands. It finishes under the old agreement, and delivery is where that is caught:
    reading the current version, bringing the work up to date and submitting again is the
    repair, and the refusal closes nothing (the attempt keeps running).
    """
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    agent = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)

    def propose(label: str, supersedes_id: str = "") -> dict[str, Any]:
        return _call(endpoint, "contract.propose", {
            "contract_id": "api", "contract_kind": "interface",
            "payload": {"task_id": task_id, "label": label},
            "participants_required": [{"slot": "self", "agent_id": agent.agent_id}],
            "participants_optional": [], "subject_ref": task_id, "input_refs": [],
            "supersedes_id": supersedes_id,
        }, agent)

    def accept(proposal: dict[str, Any]) -> None:
        _call(endpoint, "contract.accept", {
            "proposal_id": proposal["proposal_id"], "participant_slot": "self",
            "proposal_digest": proposal["digest"], "evidence_refs": [],
        }, agent)

    agreed = propose("接口契约 v1")
    accept(agreed)
    in_force_v1 = [f"{agreed['proposal_id']}:{agreed['digest']}"]

    # A declaration that matches nothing in force holds the start boundary, and nothing
    # is claimed on the way out.
    with pytest.raises(HTTPException) as failure:
        _call(endpoint, "task.begin", {
            "task_id": task_id, "expected_task_revision": tasks.tasks[task_id].revision,
            "expected_revisions": {"contract": []},
        }, agent)
    assert failure.value.detail["code"] == "contract_revision_conflict"
    assert tasks.tasks[task_id].status == "open" and not tasks.attempts

    started = _call(endpoint, "task.begin", {
        "task_id": task_id, "expected_task_revision": tasks.tasks[task_id].revision,
        "expected_revisions": {"contract": in_force_v1},
    }, agent)
    assert started["status"] == "running"

    revision = propose("接口契约 v2", agreed["proposal_id"])
    accept(revision)

    # The attempt is still running under v1: delivery is refused, and the refusal closes
    # nothing — the attempt is still the running one afterwards.
    with pytest.raises(HTTPException) as failure:
        _call(endpoint, "task.submit", {
            "task_id": task_id, "attempt_id": started["attempt_id"], "summary": "done",
            "expected_revisions": {"contract": in_force_v1},
        }, agent)
    assert failure.value.detail["code"] == "contract_revision_conflict"
    assert tasks.tasks[task_id].status == "running"

    submitted = _call(endpoint, "task.submit", {
        "task_id": task_id, "attempt_id": started["attempt_id"], "summary": "done",
        "expected_revisions": {"contract": [f"{revision['proposal_id']}:{revision['digest']}"]},
    }, agent)
    assert submitted["result_id"] and tasks.tasks[task_id].status == "submitted"


def test_a_revision_inherits_the_participants_it_does_not_restate(tmp_path: Path) -> None:
    """A revision may not quietly narrow who has to agree: with no explicit participant
    list it carries the predecessor's over."""
    _, authority, tasks, cognition, _, endpoint = _harness(tmp_path)
    agent = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)

    first = _call(endpoint, "contract.propose", {
        "contract_id": "api", "contract_kind": "interface",
        "payload": {"task_id": task_id, "label": "v1"},
        "participants_required": [{"slot": "self", "agent_id": agent.agent_id}],
        "participants_optional": [], "subject_ref": task_id, "input_refs": [],
        "supersedes_id": "",
    }, agent)
    revision = _call(endpoint, "contract.propose", {
        "contract_id": "api", "contract_kind": "interface",
        "payload": {"task_id": task_id, "label": "v2"},
        "participants_required": [], "participants_optional": [],
        "subject_ref": task_id, "input_refs": [], "supersedes_id": first["proposal_id"],
    }, agent)

    inherited = cognition.proposals[revision["proposal_id"]]
    assert inherited.participants == cognition.proposals[first["proposal_id"]].participants
    assert inherited.required_slots == ("self",)


def test_a_refused_proposal_is_readable_with_its_reason(tmp_path: Path) -> None:
    """A refusal is a decision someone will have to explain later, so it has to survive
    the round trip: the reason is stored on the proposal (the audit trail keeps no free
    text) and the read shows both the refusal and the fact that nothing is in force."""
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    agent = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)
    _call(endpoint, "task.begin", {
        "task_id": task_id, "expected_task_revision": tasks.tasks[task_id].revision,
    }, agent)
    proposed = _call(endpoint, "contract.propose", {
        "contract_id": "api", "contract_kind": "interface", "payload": {"task_id": task_id},
        "participants_required": [{"slot": "self", "agent_id": agent.agent_id}],
        "participants_optional": [], "subject_ref": task_id, "input_refs": [], "supersedes_id": "",
    }, agent)
    rejected = _call(endpoint, "contract.reject", {
        "proposal_id": proposed["proposal_id"], "proposal_digest": proposed["digest"],
        "reason": "接口字段对不上", "evidence_refs": [],
    }, agent)
    assert rejected["status"] == "rejected"

    view = _call(endpoint, "context.project_read", {}, agent)
    entry = view["contracts"]["tasks"][0]
    assert entry["in_force"] == []
    assert entry["proposals"][0]["status"] == "rejected"
    assert entry["proposals"][0]["resolution_reason"] == "接口字段对不上"


def test_submit_refuses_while_a_revision_is_under_discussion(tmp_path: Path) -> None:
    """Delivery is the second boundary that has to settle which contract version governs.

    A result must not be published on top of an agreement that is being revised — and the
    refusal has to be *repairable*: the attempt keeps running, so settling the revision
    and submitting again is enough. Nothing has to be started over.
    """
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    agent = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)

    def propose(label: str, supersedes_id: str = "") -> dict[str, Any]:
        return _call(endpoint, "contract.propose", {
            "contract_id": "api", "contract_kind": "interface",
            "payload": {"task_id": task_id, "label": label},
            "participants_required": [{"slot": "self", "agent_id": agent.agent_id}],
            "participants_optional": [], "subject_ref": task_id, "input_refs": [],
            "supersedes_id": supersedes_id,
        }, agent)

    def accept(proposal: dict[str, Any]) -> None:
        _call(endpoint, "contract.accept", {
            "proposal_id": proposal["proposal_id"], "participant_slot": "self",
            "proposal_digest": proposal["digest"], "evidence_refs": [],
        }, agent)

    first = propose("接口契约 v1")
    accept(first)
    started = _call(endpoint, "task.begin", {
        "task_id": task_id, "expected_task_revision": tasks.tasks[task_id].revision,
    }, agent)

    def submit() -> dict[str, Any]:
        return _call(endpoint, "task.submit", {
            "task_id": task_id, "attempt_id": started["attempt_id"], "summary": "done",
        }, agent)

    # The revision lands while the attempt is already running.
    revision = propose("接口契约 v2", first["proposal_id"])

    with pytest.raises(HTTPException) as failure:
        submit()
    assert failure.value.detail["code"] == "contract_not_accepted"
    # The refusal closed nothing: same attempt, still running and still able to deliver.
    assert tasks.attempts[started["attempt_id"]].status == "running"
    assert tasks.tasks[task_id].status == "running"

    accept(revision)
    assert submit()["result_id"]
    assert tasks.tasks[task_id].status == "submitted"


def test_inbox_claim_fetch_ack_roundtrip(tmp_path: Path) -> None:
    _, authority, _, _, messages, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    messages.send(
        command_id="cmd1", sender_agent_id="other", recipient_agent_id=receipt.agent_id,
        kind="message", subject_ref="s", summary="hello", payload={"request": "private-action-sentinel"},
    )
    claimed = _call(endpoint, "inbox.claim", {"limit": 50}, receipt)
    assert claimed["count"] == 1
    message_id = claimed["messages"][0]["message_id"]
    assert "payload" not in claimed["messages"][0]

    fetched = _call(endpoint, "inbox.fetch", {"message_id": message_id}, receipt)
    assert fetched["message_id"] == message_id
    assert fetched["payload"] == {"request": "private-action-sentinel"}
    assert fetched["payload_digest"].startswith("sha256:")
    other = _enroll_ready(authority, installation="install-b", conversation="conversation-b")
    with pytest.raises(HTTPException) as denied:
        _call(endpoint, "inbox.fetch", {"message_id": message_id}, other)
    assert denied.value.status_code == 403

    acked = _call(endpoint, "inbox.ack", {"message_id": message_id, "reason": "done"}, receipt)
    assert acked["acked"] is True


def test_message_send_idempotent_dedup(tmp_path: Path) -> None:
    _, authority, _, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    payload = {"recipient_agent_id": "other-agent", "kind": "message", "subject_ref": "s", "summary": "hello"}
    first = _call(endpoint, "message.send", payload, receipt)
    second = _call(endpoint, "message.send", payload, receipt)
    assert first["message_id"] == second["message_id"]


def test_canonical_message_payloads_complete_recipient_reply_flow(tmp_path: Path) -> None:
    from uuid import uuid4

    _, authority, _, _, messages, endpoint = _harness(tmp_path)
    sender = _enroll_ready(authority, installation="sender", conversation="sender-conversation")
    recipient = _enroll_ready(authority, installation="recipient", conversation="recipient-conversation")

    def invoke(name, payload, identity):
        schema = json.loads((ROOT / "protocol/schemas/commands" / (name.replace(".", "/") + ".schema.json"))
                            .read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(payload)
        request = _request(payload).model_copy(update={"command_id": uuid4().hex})
        return endpoint(name, request, Response(), f"Bearer {identity.secret_token}",
                        identity.session_id, identity.connection_epoch)["result"]

    payload = json.loads((ROOT / "protocol/fixtures/valid/message-send.json").read_text(encoding="utf-8"))
    payload["recipient_agent_id"] = recipient.agent_id
    sent = invoke("message.send", payload, sender)
    message_id = sent["message_id"]
    # 发送者必须知道这条消息会不会唤醒对方：唤醒花掉对方一整轮，名单只由 messaging.WAKE_WORTHY_KINDS 决定。
    # fixture 的 kind=request 不在名单里，但它带了 response_contract.required=true，
    # 因此它只是 coordination.wake_candidates 的候选，需要显式 coordination.wake。
    assert "不会唤醒对方" in sent["next"] and "wake_candidates" in sent["next"]
    claimed = invoke("inbox.claim", {}, recipient)
    assert claimed["count"] == 1 and "payload" not in claimed["messages"][0]
    fetched = invoke("inbox.fetch", {"message_id": message_id}, recipient)
    assert fetched["payload"] == payload["payload"] and fetched["in_reply_to"] is None
    obligation_id = fetched["response_obligations"][0]["obligation_id"]
    with pytest.raises(HTTPException) as denied:
        invoke("inbox.fetch", {"message_id": message_id}, sender)
    assert denied.value.status_code == 403
    invoke("inbox.presented", {"message_id": message_id, "evidence_kind": "agent_asserted",
                               "evidence_digest": fetched["payload_digest"]}, recipient)
    invoke("inbox.ack", {"message_id": message_id}, recipient)
    assert messages.obligations[obligation_id].status == "open"
    reply = invoke("message.send", {"recipient_agent_id": sender.agent_id, "summary": "verified",
                                    "in_reply_to": message_id, "payload": {"status": "passed"}}, recipient)
    result = invoke("message.respond", {"obligation_id": obligation_id, "response_message_id": reply["message_id"]}, recipient)
    assert result["status"] == "responded"
    returned = invoke("inbox.fetch", {"message_id": reply["message_id"]}, sender)
    assert returned["payload"] == {"status": "passed"} and returned["in_reply_to"] == message_id


@pytest.mark.parametrize("name,payload", [
    ("inbox.claim", {"max_bytes": 1000}),
    ("inbox.fetch", {"delivery_lease_id": "old-alias"}),
    ("message.respond", {"obligation_id": "o", "response_message_id": "m", "response_payload": {}}),
])
def test_retired_message_arguments_are_rejected_by_real_dispatch(tmp_path: Path, name, payload) -> None:
    _, authority, _, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="worker", conversation="worker-conversation")
    with pytest.raises(HTTPException) as rejected:
        _call(endpoint, name, payload, receipt)
    assert rejected.value.status_code == 400 and rejected.value.detail["code"] == "unknown_payload_field"


def test_message_respond_closes_obligation(tmp_path: Path) -> None:
    _, authority, _, _, messages, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    question = messages.send(
        command_id="c1", sender_agent_id="other", recipient_agent_id=receipt.agent_id,
        kind="message", subject_ref="s", summary="question", response_contract={"required": True},
    )
    obligation = next(iter(messages.obligations.values()))
    obligation_id = obligation.obligation_id
    # A nonexistent response message must be rejected and leave the obligation open.
    with pytest.raises(HTTPException) as exc:
        _call(endpoint, "message.respond", {
            "obligation_id": obligation_id, "response_message_id": "resp-1",
        }, receipt)
    assert exc.value.status_code == 400
    assert messages.obligations[obligation_id].status == "open"
    answer = messages.send(
        command_id="c1-response", sender_agent_id=receipt.agent_id, recipient_agent_id="other",
        kind="message", subject_ref="s", summary="answer", in_reply_to=question.message_id,
    )
    result = _call(endpoint, "message.respond", {
        "obligation_id": obligation_id, "response_message_id": answer.message_id,
    }, receipt)
    assert result["status"] == "responded"
    assert messages.obligations[obligation_id].status == "responded"


def test_message_respond_validates_response_schema(tmp_path: Path) -> None:
    _, authority, _, _, messages, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    contract = {
        "required": True,
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    }
    question = messages.send(
        command_id="schema-cmd", sender_agent_id="other", recipient_agent_id=receipt.agent_id,
        kind="message", subject_ref="s", summary="question", response_contract=contract,
    )
    obligation = next(iter(messages.obligations.values()))
    bad_answer = messages.send(
        command_id="bad-answer", sender_agent_id=receipt.agent_id, recipient_agent_id="other",
        kind="message", subject_ref="s", summary="bad answer", in_reply_to=question.message_id,
        payload={"not_answer": 1},
    )
    with pytest.raises(HTTPException) as exc:
        _call(endpoint, "message.respond", {
            "obligation_id": obligation.obligation_id,
            "response_message_id": bad_answer.message_id,
        }, receipt)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "response_schema_violation"
    assert messages.obligations[obligation.obligation_id].status == "open"

    good_answer = messages.send(
        command_id="good-answer", sender_agent_id=receipt.agent_id, recipient_agent_id="other",
        kind="message", subject_ref="s", summary="good answer", in_reply_to=question.message_id,
        payload={"answer": "ok"},
    )
    result = _call(endpoint, "message.respond", {
        "obligation_id": obligation.obligation_id,
        "response_message_id": good_answer.message_id,
    }, receipt)
    assert result["status"] == "responded"
    assert messages.obligations[obligation.obligation_id].status == "responded"


def test_inbox_fetch_exposes_own_response_obligation(tmp_path: Path) -> None:
    _, authority, _, _, messages, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    message = messages.send(
        command_id="obligation-cmd", sender_agent_id="other", recipient_agent_id=receipt.agent_id,
        kind="message", subject_ref="s", summary="question", response_contract={"required": True},
    )
    fetched = _call(endpoint, "inbox.fetch", {"message_id": message.message_id}, receipt)
    assert fetched["response_obligations"][0]["obligation_id"] in messages.obligations


def test_inbox_fetch_returns_payload_only_to_the_recipient(tmp_path: Path) -> None:
    _, authority, _, _, messages, endpoint = _harness(tmp_path)
    recipient = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    outsider = _enroll_ready(authority, installation="install-b", conversation="conversation-b")
    message = messages.send(
        command_id="payload-cmd", sender_agent_id="other", recipient_agent_id=recipient.agent_id,
        kind="message", subject_ref="s", summary="payload probe",
        payload={"marker": "TG-BODY-UNIT"},
    )

    claimed = _call(endpoint, "inbox.claim", {"limit": 50}, recipient)
    assert claimed["count"] == 1
    # The claim listing must stay metadata-only: no payload projection leak.
    assert "payload" not in claimed["messages"][0]

    fetched = _call(endpoint, "inbox.fetch", {"message_id": message.message_id}, recipient)
    assert fetched["payload"] == {"marker": "TG-BODY-UNIT"}
    assert fetched["summary"] == "payload probe"

    with pytest.raises(HTTPException) as exc:
        _call(endpoint, "inbox.fetch", {"message_id": message.message_id}, outsider)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "inbox_access_denied"


def test_business_commands_denied_for_degraded_session(tmp_path: Path) -> None:
    # A degraded session has no agent_base grant and must fail closed before any
    # business command is dispatched.
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    authority = AuthorityService(tmp_path / "identity.json")
    for kind, handler in build_handlers(authority=authority).items():
        dispatcher.register(kind, handler)
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator(authority=authority))
    endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", "") == "/api/v1/commands/{command_kind}"
    )
    ticket = authority.issue_ticket("install-a", "conversation-a")
    receipt = authority.redeem_ticket(ticket, "install-a", "conversation-a", baseline={})
    assert receipt.baseline_status == "degraded"
    with pytest.raises(HTTPException) as exc:
        endpoint(
            "task.begin", _request({"task_id": "t", "capability_snapshot_id": "x"}), Response(),
            f"Bearer {receipt.secret_token}", receipt.session_id, receipt.connection_epoch,
        )
    assert exc.value.status_code == 401


def test_context_project_read_returns_own_scope(tmp_path: Path) -> None:
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)
    _call(endpoint, "task.begin", {"task_id": task_id, "expected_task_revision": tasks.tasks[task_id].revision}, receipt)

    snapshot = _call(endpoint, "context.project_read", {}, receipt)
    assert snapshot["agent_id"] == receipt.agent_id
    assert "coordination.read" in snapshot["scope"]["capabilities"]
    assert any(item["task_id"] == task_id for item in snapshot["tasks"])
    assert "secret_token" not in snapshot and "absolute_path" not in snapshot


def test_context_project_read_includes_project_id(tmp_path: Path) -> None:
    _, authority, tasks, _, _, endpoint = _harness(tmp_path, project_id="project-1")
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)
    _call(endpoint, "task.begin", {"task_id": task_id, "expected_task_revision": tasks.tasks[task_id].revision}, receipt)

    snapshot = _call(endpoint, "context.project_read", {}, receipt)
    assert snapshot["project_id"] == "project-1"
    assert any(item["task_id"] == task_id for item in snapshot["tasks"])


def test_reconnect_rejects_stale_connection_epoch(tmp_path: Path) -> None:
    _, authority, _, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")

    first = _call(endpoint, "session.reconnect", {
        "reconnect_nonce": receipt.reconnect_nonce,
        "expected_connection_epoch": receipt.connection_epoch,
    }, receipt)
    assert first["connection_epoch"] == receipt.connection_epoch + 1

    # Correct fresh nonce but a stale expected_connection_epoch must fail closed.
    with pytest.raises(HTTPException) as exc:
        endpoint(
            "session.reconnect", _request({
                "reconnect_nonce": first["reconnect_nonce"],
                "expected_connection_epoch": receipt.connection_epoch,
            }), Response(),
            f"Bearer {first['secret_token']}", first["session_id"], first["connection_epoch"],
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "stale_connection_epoch"


def test_unknown_payload_field_rejected(tmp_path: Path) -> None:
    # A forged actor field (and any unknown payload key) is rejected before any
    # handler runs: the typed-tool contract is enforced by the dispatcher.
    _, authority, _, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    with pytest.raises(HTTPException) as exc:
        _call(endpoint, "message.send", {
            "recipient_agent_id": "other-agent", "kind": "message",
            "subject_ref": "s", "summary": "hello", "actor_id": "forged-agent",
        }, receipt)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "unknown_payload_field"

def test_message_send_says_whether_it_wakes_the_recipient(tmp_path):
    """发送者必须知道这条消息会不会打断对方 —— 唤醒的代价是对方一整个宿主回合。

    三种情况各断言一条**区分得开的**句子（不用 "会唤醒" 这种子串：第三分支里也含它）。
    """

    from uuid import uuid4

    _, authority, _, _, _, endpoint = _harness(tmp_path)
    sender = _enroll_ready(authority, installation="wake-sender", conversation="wake-sender-conversation")
    recipient = _enroll_ready(authority, installation="wake-recipient", conversation="wake-recipient-conversation")

    def send(payload):
        request = _request(payload).model_copy(update={"command_id": uuid4().hex})
        return endpoint("message.send", request, Response(), f"Bearer {sender.secret_token}",
                        sender.session_id, sender.connection_epoch)["result"]

    assigned = send({"recipient_agent_id": recipient.agent_id, "kind": "task.assigned", "summary": "有任务可领"})
    assert "这类消息会唤醒对方的宿主" in assigned["next"]

    plain = send({"recipient_agent_id": recipient.agent_id, "kind": "notice", "summary": "只是知会"})
    assert "这类消息不会唤醒对方" in plain["next"]
    assert "task.assigned" in plain["next"], "要告诉它哪些形态才值得打断对方"

    required = send({"recipient_agent_id": recipient.agent_id, "kind": "notice", "summary": "需要回执",
                     "response_contract": {"required": True}})
    assert "不会唤醒对方" in required["next"]
    assert "wake_candidates" in required["next"], "带 required 的只是候选，要显式 wake"
