"""Durable failure diagnostics and shared-fact visibility across real commands."""

from __future__ import annotations

import contextlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from tests.integration import test_desktop_wake as desktop_fixtures
from tests.integration.test_m1_runtime_flow import _baseline
from tests.unit.test_trace_audit import Runtime
from tests.unit.test_trace_audit import runtime as runtime

from tsunagou.hostwake.dispatcher import WakeDispatcher
from tsunagou.hostwake.port import HostBindingRef, WakeAttempt
from tsunagou.shared_kernel.query_models import DiagnosticPageModel

desktop_runtime = desktop_fixtures.runtime


class FailingHost:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.store = SimpleNamespace(get=lambda _: (HostBindingRef("b", "worker", "fixture", "fixture", status="ready"), {}))

    def wake(self, request):
        if self.mode == "raise":
            raise RuntimeError("SENTINEL-CREDENTIAL")
        return WakeAttempt(request.wake_attempt_id, request.agent_id, request.message_id,
                           "failed", error_code="host_rejected", error_message="SENTINEL-CREDENTIAL")


@pytest.mark.parametrize("mode", ["failed", "raise"])
def test_direct_provider_failures_have_utc_diagnostics_without_evidence(tmp_path: Path, mode: str) -> None:
    dispatcher = WakeDispatcher(FailingHost(mode), attempts_path=tmp_path / "attempts.json", diagnostics_path=tmp_path / "diagnostics.json")
    result = dispatcher.on_delivery(message_id="message", recipient_agent_id="worker", project_id="project",
                                    task_id="task", attempt_id="attempt", command_id="command", actor_id="sender")
    assert result["state"] == "failed"
    events = dispatcher.diagnostics(project_id="project")
    DiagnosticPageModel.model_validate({"project_id": "project", "items": events})
    failure = next(item for item in events if item["kind"] == "wake_failed")
    assert failure["occurred_at"].endswith("Z") and failure["recorded_at"].endswith("Z")
    assert failure["task_id"] == "task" and failure["attempt_id"] == "attempt"
    assert failure["trigger_source"] == "daemon_delivery" and failure["error_code"]
    dispatcher.record_presented(agent_id="worker", message_id="message", evidence_digest="sha256:evidence", evidence_kind="visible")
    assert dispatcher.status(message_id="message", recipient_agent_id="worker")["state"] == "failed"
    presented = dispatcher.diagnostics()[-1]
    assert presented["kind"] == "agent_presented" and presented["trigger_source"] == "unknown"
    dispatcher.stop()
    rebuilt = WakeDispatcher(FailingHost(mode), attempts_path=tmp_path / "attempts.json", diagnostics_path=tmp_path / "diagnostics.json")
    assert rebuilt.diagnostics() == dispatcher.diagnostics()
    assert "SENTINEL" not in (tmp_path / "attempts.json").read_text(encoding="utf-8")
    assert "SENTINEL" not in (tmp_path / "diagnostics.json").read_text(encoding="utf-8")
    rebuilt.stop()


def test_host_source_time_is_distinct_from_observation_and_unknown_stays_null() -> None:
    dispatcher = WakeDispatcher(FailingHost("failed"))
    item = {"project_id": "project", "agent_id": "worker", "message_id": "message", "wake_attempt_id": "wake",
            "evidence": [{"kind": "turn_started", "evidence_digest": "one", "observed_at": "2026-09-28T08:00:05+08:00",
                          "details": {"host_started_at": 1790553600, "trigger_source": "daemon_delivery"}},
                         {"kind": "turn_completed", "evidence_digest": "two", "observed_at": "2026-09-28T00:00:10Z", "details": {}}]}
    dispatcher._record_evidence(item)
    start, completed = dispatcher.diagnostics()
    assert start["occurred_at"] == "2026-09-28T00:00:00.000Z"
    assert start["observed_at"] == "2026-09-28T00:00:05.000Z"
    assert completed["occurred_at"] is None and completed["observed_at"] == "2026-09-28T00:00:10.000Z"


def test_shared_submit_fact_survives_private_notification_without_exposing_it(runtime: Runtime) -> None:
    main, _ = runtime.enroll("main")
    worker, _ = runtime.enroll("worker")
    outsider, _ = runtime.enroll("outsider")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    task = runtime.call("task.create", {"title": "shared", "objective": "verify only", "execution_scope": {}}, main)
    runtime.call("task.ready", {"task_id": task["task_id"]}, main)
    runtime.call("task.publish", {"task_id": task["task_id"]}, main)
    state = runtime.app.state.state_runtime
    begin = runtime.call("task.begin", {"task_id": task["task_id"],
                                        "expected_task_revision": state.tasks.tasks[task["task_id"]].revision}, worker)
    runtime.call("task.submit", {"task_id": task["task_id"], "attempt_id": begin["attempt_id"], "summary": "finished"}, worker)
    message = next(message for message in state.messages.messages.values() if message.subject_ref == f"task/{task['task_id']}")
    for viewer in (None, outsider):
        page = runtime.page(viewer, subject_ref=f"task/{task['task_id']}")
        submitted = next(item for item in page["items"] if item["action"] == "task.submit")
        assert all(not change["subject_ref"].startswith(("message/", "delivery/", "obligation/")) for change in submitted["changes"])
        assert message.message_id not in json.dumps(page)
        assert any(change["state_after"] == "submitted" for change in submitted["changes"])


def test_filters_privacy_and_rejected_commands_do_not_create_domain_events(runtime: Runtime) -> None:
    main, _ = runtime.enroll("main")
    worker, _ = runtime.enroll("worker")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    wake = WakeDispatcher(FailingHost("failed"))
    runtime.app.state.wake_dispatcher = wake
    # The query closure has no dispatcher in this fixture; build its projection
    # through the real composition helper with this explicit diagnostic source.
    from tsunagou.bootstrap.container import _query_provider
    from tsunagou.interfaces.runtime import PrincipalContext

    state = runtime.app.state.state_runtime
    query = _query_provider(project_id=runtime.project_id, registry=state, database=runtime.db,
                            authority=state.authority, tasks=state.tasks, cognition=state.cognition,
                            messages=state.messages, resources=state.resources, workspaces=state.workspaces,
                            lifecycle=state.lifecycle, project_registry=state.project_registry,
                            checkpoint_store=None, coordination=state.coordination, wake_dispatcher=wake)
    sent = runtime.call("message.send", {"recipient_agent_id": worker["agent_id"], "summary": "SENTINEL-PRIVATE"}, main)
    wake.on_delivery(message_id=sent["message_id"], recipient_agent_id=worker["agent_id"], project_id=runtime.project_id, task_id="task")
    before = runtime.db.last_event_seq()
    sender = PrincipalContext("B", main["agent_id"])
    user = PrincipalContext("U", "user_control")
    page = query("diagnostics", runtime.project_id, viewer=sender, message_id=sent["message_id"], task_id="task",
                 from_timestamp="2020-01-01T08:00:00+08:00", to_timestamp="2030-01-01T00:00:00Z")
    assert page["items"]
    DiagnosticPageModel.model_validate(page)
    assert all(row["message_id"] is None for row in query("diagnostics", runtime.project_id, viewer=user)["items"])
    assert not query("diagnostics", runtime.project_id, viewer=user, message_id=sent["message_id"])["items"]
    assert "SENTINEL" not in json.dumps(page)
    assert runtime.db.last_event_seq() == before
    with pytest.raises(ValueError, match="invalid_time_range"):
        query("diagnostics", runtime.project_id, viewer=user, from_timestamp="2030-01-01T00:00:00Z", to_timestamp="2020-01-01T00:00:00Z")
    runtime.app.state.a2a_gateway.dispatcher.record_failure = wake.record_command_failure
    with pytest.raises(HTTPException):
        runtime.call("task.begin", {"task_id": "missing", "expected_task_revision": 1}, worker)
    assert wake.diagnostics()[-1]["kind"] == "command_rejected"
    assert runtime.db.last_event_seq() == before


def test_five_real_sdk_boundaries_and_durable_outbox_parent(desktop_runtime, tmp_path: Path) -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    from tools.dev.collect_acceptance_trace import create_collector

    from tsunagou.platform.telemetry import Telemetry
    from tsunagou.shared_kernel.ids import new_id

    app, call, sender, receiver, _host = desktop_runtime
    output = tmp_path / "spans.jsonl"
    collector = create_collector(output)
    thread = threading.Thread(target=collector.serve_forever, daemon=True)
    thread.start()
    telemetry = Telemetry(f"http://127.0.0.1:{collector.server_port}")
    app.state.host_delivery.telemetry = telemetry
    try:
        with telemetry.activate():
            identity = {"installation_id": "fixture", "conversation_evidence": {"conversation_id": "SENTINEL-CONVERSATION"}}
            ticket = call("agent.ticket.create.user", identity)
            call("agent.enroll", {**identity, "probe_payload": _baseline()}, token=ticket["secret"])
            sent = call("message.send", {"recipient_agent_id": receiver["agent_id"], "summary": "SENTINEL-PRIVATE"}, sender)
            response = app.state.a2a_gateway.dispatch({
                "jsonrpc": "2.0", "id": 1, "method": "message/send",
                "params": {"message": {"messageId": new_id(), "role": "user", "parts": [{"text": "SENTINEL-PRIVATE"}]}},
            }, authorization=f"Bearer {sender['secret_token']}", session_id=sender["session_id"],
                connection_epoch=sender["connection_epoch"], recipient_agent_id=receiver["agent_id"])
            assert "result" in response
        # The submission context has ended. Delivery runs in the worker's own
        # executor and recovers the committed parent through outbox.event_seq.
        desktop_fixtures.drain(app)
        with contextlib.closing(app.state.project_database._connect()) as conn:
            event = conn.execute("SELECT e.payload_json FROM outbox o JOIN events e ON "
                                 "o.project_id=e.project_id AND o.event_seq=e.event_seq WHERE o.target_ref=?",
                                 (f"message/{sent['message_id']}",)).fetchone()
            persisted = json.loads(event[0])["traceparent"]
        telemetry.close()
        raw = output.read_text(encoding="utf-8")
        assert "SENTINEL" not in raw and sender["secret_token"] not in raw
        rows = list(map(json.loads, raw.splitlines()))
        assert {row["name"] for row in rows} == {"command.execute", "a2a.submit", "outbox.deliver", "host.wake", "onboarding.restore"}
        assert any(row["name"] == "command.execute" and row["attributes"].get("tsunagou.message_id") == sent["message_id"]
                   for row in rows)
        delivery = next(row for row in rows if row["name"] == "outbox.deliver"
                        and row["attributes"].get("tsunagou.message_id") == sent["message_id"])
        assert delivery["trace_id"] == persisted[3:35] and delivery["parent_span_id"] == persisted[36:52]
    finally:
        collector.shutdown()
        collector.server_close()
        thread.join(timeout=3)
