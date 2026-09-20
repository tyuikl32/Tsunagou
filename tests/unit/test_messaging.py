import time
from pathlib import Path

import pytest

from tsunagou.modules.messaging import MessageStore


def test_pull_ack_is_idempotent_and_recipient_scoped(tmp_path: Path) -> None:
    store = MessageStore(tmp_path / "messages.json")
    message = store.send(
        command_id="cmd-1", sender_agent_id="main", recipient_agent_id="worker",
        kind="task.offer", subject_ref="task/1", summary="Please inspect", response_contract={"required": True},
    )
    # The same command_id with identical input is idempotent; with changed input it
    # must conflict instead of silently creating a second delivery.
    assert store.send(
        command_id="cmd-1", sender_agent_id="main", recipient_agent_id="worker",
        kind="task.offer", subject_ref="task/1", summary="Please inspect",
        response_contract={"required": True},
    ).message_id == message.message_id
    with pytest.raises(ValueError):
        store.send(
            command_id="cmd-1", sender_agent_id="main", recipient_agent_id="worker",
            kind="task.offer", subject_ref="task/1", summary="duplicate",
        )
    assert store.fetch("other") == []
    fetched = store.fetch("worker")
    assert [item.message_id for item in fetched] == [message.message_id]
    store.ack("worker", message.message_id)
    with pytest.raises(PermissionError):
        store.ack("other", message.message_id)
    assert store.sync("worker")[0].message_id == message.message_id


def test_send_conflict_covers_all_semantic_fields(tmp_path: Path) -> None:
    store = MessageStore(tmp_path / "messages.json")
    contract = {"required": True, "schema": {"type": "object"}}
    store.send(
        command_id="cmd-all", sender_agent_id="main", recipient_agent_id="worker",
        kind="task.offer", subject_ref="task/1", summary="Please inspect",
        priority=7, response_contract=contract, in_reply_to="parent-1",
    )
    changed_variants = [
        {"priority": 8},
        {"response_contract": {"required": False}},
        {"in_reply_to": "parent-2"},
    ]
    for changed in changed_variants:
        with pytest.raises(ValueError, match="command_id_conflict"):
            store.send(
                command_id="cmd-all", sender_agent_id="main", recipient_agent_id="worker",
                kind="task.offer", subject_ref="task/1", summary="Please inspect",
                priority=changed.get("priority", 7),
                response_contract=changed.get("response_contract", contract),
                in_reply_to=changed.get("in_reply_to", "parent-1"),
            )


def test_ack_does_not_claim_presentation_and_obligation_requires_response(tmp_path: Path) -> None:
    store = MessageStore(tmp_path / "messages.json")
    message = store.send(
        command_id="cmd-2", sender_agent_id="main", recipient_agent_id="worker",
        kind="decision", subject_ref="decision/1", summary="Choose", response_contract={"required": True},
    )
    obligation = next(iter(store.obligations.values()))
    store.ack("worker", message.message_id)
    assert store.deliveries[message.message_id].presented_at is None
    with pytest.raises(ValueError):
        store.present("worker", message.message_id, {})
    store.present("worker", message.message_id, {"ui": "cli", "at": "now"})
    # A response message id that does not exist must not close the obligation.
    with pytest.raises(ValueError):
        store.respond("worker", obligation.obligation_id, "response-1")
    assert store.obligations[obligation.obligation_id].status == "open"
    response = store.send(
        command_id="cmd-2-response", sender_agent_id="worker", recipient_agent_id="main",
        kind="decision.response", subject_ref="decision/1", summary="Chosen", in_reply_to=message.message_id,
    )
    store.respond("worker", obligation.obligation_id, response.message_id)
    assert store.obligations[obligation.obligation_id].status == "responded"


def test_expired_delivery_can_be_pulled_again_and_push_is_suppressed(tmp_path: Path) -> None:
    store = MessageStore(tmp_path / "messages.json")
    message = store.send(
        command_id="cmd-3", sender_agent_id="a", recipient_agent_id="b",
        kind="info", subject_ref="x", summary="hello",
    )
    now = time.time()
    assert store.fetch("b", now=now)[0].message_id == message.message_id
    assert store.fetch("b", now=now + 31)[0].message_id == message.message_id
    assert store.mark_push_failure("b") is False
    assert store.mark_push_failure("b") is False
    assert store.mark_push_failure("b") is True
    assert store.push_suppressed("b")
