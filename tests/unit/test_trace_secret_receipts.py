"""Authenticated bounded credential handoff through the real dispatcher/SQLite."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest
import uvicorn
from fastapi import HTTPException, Response
from tests.unit.test_trace_audit import Runtime
from tests.unit.test_trace_audit import runtime as runtime

from tsunagou.bootstrap.container import build_application
from tsunagou.platform.delivery import SecretDeliveryStore
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES
from tsunagou.shared_kernel.ids import new_id


def _identity(conversation: str) -> dict[str, Any]:
    return {"installation_id": "same-ide", "conversation_evidence": {"conversation_id": conversation}}


def _enroll_payload(conversation: str) -> dict[str, Any]:
    return {**_identity(conversation), "probe_payload": {"baseline": {
        name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]} for name in ADMISSION_CAPABILITIES
    }}}


def _ack(runtime: Runtime, ref: str, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    response = Response()
    value = runtime.endpoint("/api/v1/credential-deliveries/{delivery_ref}/ack")(
        ref, response, **runtime.credentials(receipt),
    )
    assert response.headers["Cache-Control"] == "no-store"
    return value


def test_enrollment_replay_ack_and_sqlite_never_contain_usable_credentials(runtime: Runtime) -> None:
    ticket = runtime.call("agent.ticket.create.user", _identity("worker"))
    command_id = new_id()
    payload = _enroll_payload("worker")
    first = runtime.call("agent.enroll", payload, ticket=ticket["secret"], command_id=command_id)
    assert first["delivery_ref"] and first["delivery_status"] == "delivered"
    assert first["created_at"].endswith("Z")
    assert runtime.call("agent.enroll", payload, ticket=ticket["secret"], command_id=command_id) == first
    assert len(runtime.app.state.state_runtime.authority.agents) == 1
    with runtime.db._connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM commands")]
        all_rows = json.dumps(rows) + json.dumps([dict(row) for row in conn.execute("SELECT * FROM events")])
        # Keep WAL materialized during this sentinel check; do not conflate
        # a missing file with proof that writes were safe.
        disk = runtime.db.path.read_bytes()
        wal = runtime.db.path.with_name(runtime.db.path.name + "-wal")
        if wal.exists():
            disk += wal.read_bytes()
    for secret in (ticket["secret"], first["secret_token"], first["reconnect_nonce"]):
        assert secret not in all_rows and secret.encode() not in disk
    enrollment = next(row for row in rows if row["command_kind"] == "agent.enroll")
    assert enrollment["principal_id"].startswith("ticket-sha256:")
    assert "conversation_id" not in json.dumps(rows)
    assert runtime.db.sensitive_command_rows() == []
    other, _ = runtime.enroll("other")
    for outsider in (None, other):
        with pytest.raises(HTTPException) as denied:
            _ack(runtime, first["delivery_ref"], outsider)
        assert denied.value.status_code == 403
    ack = _ack(runtime, first["delivery_ref"], first)
    assert ack["delivery_status"] == "consumed"
    assert _ack(runtime, first["delivery_ref"], first) == ack
    replay = runtime.call("agent.enroll", payload, ticket=ticket["secret"], command_id=command_id)
    assert replay["agent_id"] == first["agent_id"] and replay["session_id"] == first["session_id"]
    assert replay["delivery_status"] == "consumed" and replay["recovery_action"] == "reconnect_required"
    assert "secret_token" not in replay and "reconnect_nonce" not in replay
    assert _ack(runtime, ticket["delivery_ref"])["delivery_status"] == "consumed"


def test_lost_reconnect_response_accepts_only_exact_old_proof_then_safe_ack(runtime: Runtime) -> None:
    receipt, _ = runtime.enroll("worker")
    command_id = new_id()
    payload = {"reconnect_nonce": receipt["reconnect_nonce"], "expected_connection_epoch": receipt["connection_epoch"]}
    refreshed = runtime.call("session.reconnect", payload, receipt, command_id=command_id)
    assert refreshed["connection_epoch"] == receipt["connection_epoch"] + 1
    event_seq = runtime.db.last_event_seq()
    replay = runtime.call("session.reconnect", payload, receipt, command_id=command_id)
    assert replay == refreshed
    assert runtime.db.last_event_seq() == event_seq
    for kind, body, identifier in (
        ("context.project_read", {}, new_id()),
        ("session.reconnect", payload, new_id()),
        ("session.reconnect", {**payload, "reconnect_nonce": "changed"}, command_id),
    ):
        with pytest.raises(HTTPException) as denied:
            runtime.call(kind, body, receipt, command_id=identifier)
        assert denied.value.status_code in {401, 403}
    with pytest.raises(HTTPException) as wrong_proof:
        runtime.call("session.reconnect", payload, {**receipt, "secret_token": "incorrect"}, command_id=command_id)
    assert wrong_proof.value.status_code in {401, 403}
    _ack(runtime, refreshed["delivery_ref"], refreshed)
    safe = runtime.call("session.reconnect", payload, receipt, command_id=command_id)
    assert safe["delivery_status"] == "consumed" and "secret_token" not in safe
    runtime.call("context.project_read", {}, refreshed)


def test_response_loss_after_commit_preserves_memory_and_restart_replays_identity(runtime: Runtime) -> None:
    ticket = runtime.call("agent.ticket.create.user", _identity("worker"))
    command_id = new_id()
    payload = _enroll_payload("worker")

    def lost_response() -> None:
        raise RuntimeError("simulated_response_loss")

    runtime.db.post_commit_hook = lost_response
    with pytest.raises(HTTPException) as lost:
        runtime.call("agent.enroll", payload, ticket=ticket["secret"], command_id=command_id)
    assert lost.value.status_code == 503
    assert len(runtime.app.state.state_runtime.authority.agents) == 1
    first = runtime.call("agent.enroll", payload, ticket=ticket["secret"], command_id=command_id)
    # General authentication proves the committed session was not rolled back in memory.
    runtime.call("context.project_read", {}, first)
    runtime.db.release_process_lock()
    rebuilt = build_application()
    try:
        restored = Runtime(rebuilt, runtime.project_id)
        replay = restored.call("agent.enroll", payload, ticket=ticket["secret"], command_id=command_id)
        assert replay == first
        assert len(restored.app.state.state_runtime.authority.agents) == 1
        assert _ack(restored, first["delivery_ref"], first)["delivery_status"] == "consumed"
    finally:
        rebuilt.state.project_database.release_process_lock()


def test_vault_failure_before_commit_rolls_back_identity_and_can_retry(runtime: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    ticket = runtime.call("agent.ticket.create.user", _identity("worker"))
    command_id = new_id()
    original_put = runtime.db.delivery_store.put

    def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("simulated_vault_failure")

    monkeypatch.setattr(runtime.db.delivery_store, "put", unavailable)
    with pytest.raises(HTTPException):
        runtime.call("agent.enroll", _enroll_payload("worker"), ticket=ticket["secret"], command_id=command_id)
    assert not runtime.app.state.state_runtime.authority.agents
    monkeypatch.setattr(runtime.db.delivery_store, "put", original_put)
    receipt = runtime.call("agent.enroll", _enroll_payload("worker"), ticket=ticket["secret"], command_id=command_id)
    assert receipt["agent_id"] in runtime.app.state.state_runtime.authority.agents


def test_delivery_expiry_and_superseded_session_do_not_reissue_identity(runtime: Runtime) -> None:
    tick = 1_790_520_000_000
    runtime.db.delivery_store = SecretDeliveryStore(runtime.db.delivery_store.root, clock=lambda: tick)
    ticket = runtime.call("agent.ticket.create.user", _identity("worker"))
    command_id = new_id()
    payload = _enroll_payload("worker")
    first = runtime.call("agent.enroll", payload, ticket=ticket["secret"], command_id=command_id)
    tick += 120_001
    expired = runtime.call("agent.enroll", payload, ticket=ticket["secret"], command_id=command_id)
    assert expired["delivery_status"] == "expired" and "secret_token" not in expired
    assert len(runtime.app.state.state_runtime.authority.agents) == 1
    with pytest.raises(HTTPException) as late_ack:
        _ack(runtime, first["delivery_ref"], first)
    assert late_ack.value.status_code == 409
    renewed = runtime.call("session.reconnect", {"reconnect_nonce": first["reconnect_nonce"],
                                                 "expected_connection_epoch": first["connection_epoch"]}, first)
    old = runtime.call("agent.enroll", payload, ticket=ticket["secret"], command_id=command_id)
    assert old["delivery_status"] == "revoked" and "secret_token" not in old
    assert renewed["agent_id"] == first["agent_id"]


def test_parallel_exact_replays_share_one_receipt_and_ack_cannot_revive_it(runtime: Runtime) -> None:
    ticket = runtime.call("agent.ticket.create.user", _identity("worker"))
    command_id = new_id()
    payload = _enroll_payload("worker")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(runtime.call, "agent.enroll", payload, ticket=ticket["secret"], command_id=command_id) for _ in range(4)]
        receipts = [future.result(timeout=15) for future in futures]
    assert all(item == receipts[0] for item in receipts)
    assert len(runtime.app.state.state_runtime.authority.agents) == 1
    _ack(runtime, receipts[0]["delivery_ref"], receipts[0])
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(runtime.call, "agent.enroll", payload, ticket=ticket["secret"], command_id=command_id) for _ in range(4)]
        after_ack = [future.result(timeout=15) for future in futures]
    assert all(item["delivery_status"] == "consumed" and "secret_token" not in item for item in after_ack)


def test_credential_http_handoff_and_ack_never_cache_or_echo_secrets(runtime: Runtime, caplog: pytest.LogCaptureFixture) -> None:
    ticket = runtime.call("agent.ticket.create.user", _identity("http-worker"))
    server = uvicorn.Server(uvicorn.Config(runtime.app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}/api/v1"
        envelope = {"command_id": new_id(), "protocol_version": "1.0",
                    "schema_bundle_digest": runtime.registry["schema_bundle_digest"], "payload": _enroll_payload("http-worker")}
        request = Request(base + "/commands/agent.enroll", data=json.dumps(envelope).encode(),
                          headers={"Authorization": f"Bearer {ticket['secret']}", "Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            assert response.headers["Cache-Control"] == "no-store"
            enrolled = json.load(response)["result"]
        ack_url = base + "/credential-deliveries/" + quote(enrolled["delivery_ref"], safe="") + "/ack"
        with pytest.raises(HTTPError) as anonymous:
            urlopen(Request(ack_url, data=b"{}", headers={"Content-Type": "application/json"}), timeout=5)
        assert anonymous.value.code == 401
        headers = {"Authorization": f"Bearer {enrolled['secret_token']}", "Tsunagou-Session-Id": enrolled["session_id"],
                   "Tsunagou-Connection-Epoch": str(enrolled["connection_epoch"]), "Content-Type": "application/json"}
        with pytest.raises(HTTPError) as forged:
            urlopen(Request(ack_url, data=b'{"actor_id":"user_control"}', headers=headers), timeout=5)
        assert forged.value.code == 400
        with urlopen(Request(ack_url, data=b"{}", headers=headers), timeout=5) as response:
            assert response.headers["Cache-Control"] == "no-store"
            ack = json.load(response)
            assert ack["delivery_status"] == "consumed"
            assert ack["consumed_at"].endswith("Z")
            assert "secret_token" not in ack
        with urlopen(request, timeout=5) as response:
            replay = json.load(response)["result"]
        assert replay["agent_id"] == enrolled["agent_id"] and "secret_token" not in replay
        for secret in (ticket["secret"], enrolled["secret_token"], enrolled["reconnect_nonce"]):
            assert secret not in caplog.text and secret not in json.dumps(ack)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()
