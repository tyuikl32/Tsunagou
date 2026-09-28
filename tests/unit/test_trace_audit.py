"""PT1 acceptance against the assembled dispatcher and real SQLite audit path."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
import uvicorn
from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest
from tsunagou.bootstrap.container import build_application
from tsunagou.generated.protocol.audit import AuditPageModel
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.modules.tasks import TaskResult
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.query_models import (
    AuditExportModel,
    CheckpointPageModel,
    CheckpointVerificationModel,
)
from tsunagou.shared_kernel.time import format_timestamp, parse_timestamp


class Runtime:
    def __init__(self, app: Any, project_id: str) -> None:
        self.app, self.project_id = app, project_id
        self.db = app.state.project_database
        self.registry = json.loads(files("tsunagou.protocol_data").joinpath("registry/commands.json").read_text(encoding="utf-8"))
        self.command = self.endpoint("/api/v1/commands/{command_kind}")
        self.audit = self.endpoint("/api/v1/projects/{project_id}/audit")

    def endpoint(self, path: str) -> Any:
        return next(route.endpoint for route in self.app.routes if getattr(route, "path", "") == path)

    @staticmethod
    def credentials(receipt: dict[str, Any] | None = None) -> dict[str, Any]:
        return ({"authorization": f"Bearer {receipt['secret_token']}",
                 "session_id": receipt["session_id"], "connection_epoch": receipt["connection_epoch"]}
                if receipt else {"authorization": "Bearer control", "session_id": None, "connection_epoch": None})

    def call(self, kind: str, payload: dict[str, Any], receipt: dict[str, Any] | None = None,
             *, command_id: str | None = None, ticket: str | None = None) -> dict[str, Any]:
        request = CommandRequest(command_id=command_id or new_id(), protocol_version="1.0",
                                 schema_bundle_digest=self.registry["schema_bundle_digest"], payload=payload)
        credentials = self.credentials(receipt)
        if ticket:
            credentials["authorization"] = f"Bearer {ticket}"
        return self.command(kind, request, Response(), **credentials)["result"]

    def enroll(self, conversation: str) -> tuple[dict[str, Any], str]:
        identity = {"installation_id": "same-ide", "conversation_evidence": {"conversation_id": conversation}}
        ticket = self.call("agent.ticket.create.user", identity)["secret"]
        receipt = self.call("agent.enroll", {**identity, "probe_payload": {"baseline": {
            name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]} for name in ADMISSION_CAPABILITIES
        }}}, ticket=ticket)
        return receipt, ticket

    def page(self, receipt: dict[str, Any] | None = None, **filters: Any) -> dict[str, Any]:
        page = self.audit(self.project_id, **filters, **self.credentials(receipt))
        AuditPageModel.model_validate(page)
        return page


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Runtime]:
    (tmp_path / ".git").mkdir()
    registry = ProjectRegistry.initialize(tmp_path, name="audit", objective="trace facts")
    assert registry.project
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_PROJECT_ID", registry.project.project_id)
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path / ".tsunagou/local"))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    monkeypatch.delenv("TSUNAGOU_HOST_WAKE", raising=False)
    app = build_application()
    try:
        yield Runtime(app, registry.project.project_id)
    finally:
        app.state.project_database.release_process_lock()


def test_actual_actor_subject_causation_entity_times_and_noop_revisions(runtime: Runtime) -> None:
    main, main_ticket = runtime.enroll("main")
    worker, worker_ticket = runtime.enroll("worker")
    assert main["agent_id"] != worker["agent_id"]
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    appointment = next(item for item in runtime.page()["items"] if item["action"] == "authority.appoint")
    assert appointment["evidence_level"] == "user_confirmed"
    command_id = new_id()
    task = runtime.call("task.create", {"title": "T", "objective": "do"}, main, command_id=command_id)
    task_ref = f"task/{task['task_id']}"
    original = runtime.page(subject_ref=task_ref)["items"][0]
    assert original["actor_ref"] == main["agent_id"]
    assert original["actor_session_id"] == main["session_id"]
    assert original["action"] == "task.create"
    assert original["revision_before"] is None and original["revision_after"] == 1
    assert original["caused_by_command_id"] == command_id
    assert original["lineage_id"] == runtime.app.state.state_runtime.lineage_id
    assert original["occurred_at"] == original["recorded_at"]
    assert original["changes"][0]["created_at"] == original["occurred_at"]
    watermark = runtime.db.last_event_seq()
    with runtime.db._connect() as conn:
        before = [tuple(row) for row in conn.execute("SELECT * FROM module_state ORDER BY module")]
    replay = runtime.call("task.create", {"title": "T", "objective": "do"}, main, command_id=command_id)
    assert replay == task
    runtime.call("context.project_read", {}, main)
    runtime.call("context.project_read", {}, worker)
    assert runtime.db.last_event_seq() == watermark
    with runtime.db._connect() as conn:
        assert [tuple(row) for row in conn.execute("SELECT * FROM module_state ORDER BY module")] == before
    assert runtime.page(subject_ref=task_ref)["items"][0] == original
    with pytest.raises(HTTPException) as conflict:
        runtime.call("task.create", {"title": "changed", "objective": "do"}, main, command_id=command_id)
    assert conflict.value.status_code == 409
    assert runtime.db.last_event_seq() == watermark
    runtime.call("task.ready", {"task_id": task["task_id"]}, main)
    runtime.call("task.publish", {"task_id": task["task_id"]}, main)
    claim = runtime.call("task.claim", {"task_id": task["task_id"]}, worker)
    event = runtime.page(subject_ref=task_ref)["items"][-1]
    assert event["actor_ref"] == worker["agent_id"]
    assert event["action"] == "task.claim"
    changes = {item["subject_ref"]: item for item in event["changes"]}
    assert changes[task_ref]["state_before"] == "open"
    assert changes[task_ref]["state_after"] == "claimed"
    assert f"attempt/{claim['attempt_id']}" in changes
    assert changes[task_ref]["created_at"] == original["occurred_at"]
    task_view = runtime.endpoint("/api/v1/projects/{project_id}/tasks")(runtime.project_id)["items"][0]
    assert task_view["created_at"] == original["occurred_at"]
    assert task_view["updated_at"] == event["occurred_at"]
    serialized = json.dumps(runtime.db.list_events(limit=201))
    assert main_ticket not in serialized and worker_ticket not in serialized
    assert main["secret_token"] not in serialized and worker["reconnect_nonce"] not in serialized
    enrollment = [item for item in runtime.page()["items"] if item["action"] == "agent.enroll"]
    assert all(item["actor_ref"].startswith("ticket/") for item in enrollment)
    assert len({item["actor_session_id"] for item in enrollment}) == 2


def test_signed_snapshot_pages_over_200_have_no_gaps_or_duplicates(runtime: Runtime) -> None:
    genesis_events = runtime.db.last_event_seq()
    with runtime.db.transaction("many-events") as uow:
        for number in range(451):
            uow.append_event(lineage_id=runtime.db.lineage_id, event_type="fixture.updated",
                             aggregate_ref=f"task/{number}", actor_ref="worker-a" if number % 2 else "worker-b", payload={})
    first = runtime.page(limit=200)
    assert len(first["items"]) == 200 and first["next_cursor"]
    assert first["as_of_event_seq"] == genesis_events + 451
    with runtime.db.transaction("later") as uow:
        uow.append_event(lineage_id=runtime.db.lineage_id, event_type="fixture.updated",
                         aggregate_ref="task/later", actor_ref="worker-a", payload={})
    second = runtime.page(limit=200, cursor=first["next_cursor"])
    third = runtime.page(limit=200, cursor=second["next_cursor"])
    assert len(second["items"]) == 200 and len(third["items"]) == genesis_events + 51
    assert third["next_cursor"] is None
    seqs = [item["event_seq"] for page in (first, second, third) for item in page["items"]]
    assert seqs == list(range(1, genesis_events + 452))
    assert all(page["snapshot_event_seq"] == genesis_events + 451 for page in (first, second, third))
    for filters in ({"actor_ref": "worker-a"}, {"limit": 199}, {"cursor": "1"},
                    {"cursor": first["next_cursor"][:-10] + "tampered"}):
        kwargs = {"limit": 200, "cursor": first["next_cursor"], **filters}
        with pytest.raises(HTTPException) as invalid:
            runtime.page(**kwargs)
        assert invalid.value.status_code == 400
    with pytest.raises(HTTPException) as wrong_project:
        runtime.audit("another-project", authorization="Bearer control")
    assert wrong_project.value.status_code == 404
    assert all(item["actor_ref"] == "worker-a" for item in runtime.page(actor_ref="worker-a")["items"])


def test_private_message_subject_and_refs_are_recipient_scoped(runtime: Runtime) -> None:
    main, _ = runtime.enroll("main")
    sender, _ = runtime.enroll("sender")
    recipient, _ = runtime.enroll("recipient")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    sent = runtime.call("message.send", {"recipient_agent_id": recipient["agent_id"], "summary": "private summary",
                                         "payload": {"private": "DO-NOT-EXPOSE"}, "subject_ref": "private-subject"}, sender)
    message_ref = f"message/{sent['message_id']}"
    for outsider in (None, main):
        assert runtime.page(outsider, subject_ref=message_ref)["items"] == []
        assert sent["message_id"] not in json.dumps(runtime.page(outsider))
    for participant in (sender, recipient):
        page = runtime.page(participant, subject_ref=message_ref)
        assert page["items"][0]["subject_ref"] == message_ref
        assert "DO-NOT-EXPOSE" not in json.dumps(page) and "private summary" not in json.dumps(page)
    with runtime.db.transaction("private-evidence") as uow:
        uow.append_event(lineage_id=runtime.db.lineage_id, event_type="task.progress", aggregate_ref="task/public",
                         actor_ref=sender["agent_id"], payload={}, evidence_refs=[message_ref])
    assert not runtime.page(main, subject_ref="task/public")["items"]
    assert runtime.page(sender, subject_ref="task/public")["items"][0]["evidence_refs"] == [message_ref]
    # Older rows kept evidence only in payload; visibility must use the same
    # fallback as the projection, including message aliases and unknown IDs.
    for evidence in (message_ref, f"message:{sent['message_id']}", "message/unknown-private-message"):
        with runtime.db.transaction("legacy-private-evidence") as uow:
            uow.append_event(lineage_id=runtime.db.lineage_id, event_type="task.progress",
                             aggregate_ref="task/legacy-evidence", actor_ref=sender["agent_id"],
                             payload={"evidence_refs": [evidence]})
    assert not runtime.page(main, subject_ref="task/legacy-evidence")["items"]
    assert not runtime.page(subject_ref="task/legacy-evidence")["items"]
    assert len(runtime.page(sender, subject_ref="task/legacy-evidence")["items"]) == 2
    with pytest.raises(HTTPException) as unauthenticated:
        runtime.audit(runtime.project_id)
    assert unauthenticated.value.status_code == 401
    with pytest.raises(HTTPException) as stale:
        runtime.audit(runtime.project_id, authorization=f"Bearer {sender['secret_token']}",
                      session_id=sender["session_id"], connection_epoch=sender["connection_epoch"] + 1)
    assert stale.value.status_code == 401


def test_visible_pagination_scans_over_full_batches_of_hidden_legacy_rows(runtime: Runtime) -> None:
    genesis_events = runtime.db.last_event_seq()
    with runtime.db.transaction("mixed-audiences") as uow:
        for number in range(405):
            public = number in {0, 202, 404}
            uow.append_event(
                lineage_id=runtime.db.lineage_id, event_type="task.progress" if public else "command.message.send",
                aggregate_ref="project/legacy", actor_ref="legacy-actor", payload={},
            )
    first = runtime.page(actor_ref="legacy-actor", limit=1)
    second = runtime.page(actor_ref="legacy-actor", limit=1, cursor=first["next_cursor"])
    third = runtime.page(actor_ref="legacy-actor", limit=1, cursor=second["next_cursor"])
    assert [page["items"][0]["event_seq"] for page in (first, second, third)] == [genesis_events + seq for seq in (1, 203, 405)]
    assert third["next_cursor"] is None
    assert all(page["as_of_event_seq"] == genesis_events + 405 for page in (first, second, third))


def test_query_entity_times_use_own_identity_and_survive_restart(runtime: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = 1_790_520_000_001
    monkeypatch.setattr("tsunagou.platform.state.now_ms", lambda: clock)
    main, _ = runtime.enroll("main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    clock += 1_000
    task = runtime.call("task.create", {"title": "T", "objective": "do"}, main)
    runtime.call("task.ready", {"task_id": task["task_id"]}, main)
    runtime.call("task.publish", {"task_id": task["task_id"]}, main)
    clock += 1_000
    claim = runtime.call("task.claim", {"task_id": task["task_id"]}, main)
    clock += 1_000
    state = runtime.app.state.state_runtime
    before = state.capture()
    # Domain-owned result fixture; persistence and public queries are the real runtime.
    state.tasks.results["result-fixture"] = TaskResult(
        "result-fixture", task["task_id"], claim["attempt_id"], {}, "digest", main["agent_id"],
    )
    with runtime.db.transaction("result-observed") as uow:
        state.persist(uow, actor_ref=main["agent_id"], command_kind="task.submit", before=before,
                      result={"task_id": task["task_id"], "result_id": "result-fixture"})
    expected = {"agents": 1_790_520_000_001, "tasks": 1_790_520_001_001,
                "attempts": 1_790_520_002_001, "results": 1_790_520_003_001}
    for kind, expected_time in expected.items():
        items = runtime.endpoint(f"/api/v1/projects/{{project_id}}/{kind}")(runtime.project_id)["items"]
        assert items[0]["created_at"] == format_timestamp(expected_time)
    events_before = runtime.page()["items"]
    runtime.db.release_process_lock()
    rebuilt = build_application()
    try:
        restored = Runtime(rebuilt, runtime.project_id)
        assert restored.page()["items"][:len(events_before)] == events_before
        result_view = restored.endpoint("/api/v1/projects/{project_id}/results")(runtime.project_id)["items"][0]
        assert result_view["created_at"] == format_timestamp(expected["results"])
    finally:
        rebuilt.state.project_database.release_process_lock()


def test_legacy_unknown_times_are_not_migration_time(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE events(project_id TEXT,event_seq INTEGER,event_id TEXT,lineage_id TEXT,
                     event_type TEXT,schema_version TEXT,aggregate_ref TEXT,actor_ref TEXT,command_id TEXT,
                     occurred_at INTEGER,payload_json TEXT,digest TEXT)""")
        conn.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            "legacy", 1, "old-event", "old-lineage", "old.action", "1", "task/old", "old-actor", "old-command", None, "{}", "old",
        ))
    db = ProjectDatabase(path, project_id="legacy")
    row = db.list_events()[0]
    assert row["occurred_at"] is None and row["recorded_at"] is None
    assert row["revision_before"] is None and row["revision_after"] is None
    assert db.entity_metadata(db.lineage_id) == {}
    assert db.list_events(from_ms=0) == []  # No false placement at migration time.
    with db.transaction("first-observed-update") as uow:
        change = uow.record_entity_change(lineage_id=db.lineage_id, subject_ref="task/old", existed=True,
                                          revision_before=4, revision_after=5)
    assert change["created_at"] is None and isinstance(change["updated_at"], int)
    assert db.entity_metadata(db.lineage_id)["task/old"]["created_at"] is None


def test_audit_read_connections_are_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = ProjectDatabase(tmp_path / "read-handles.sqlite3")
    opened: list[sqlite3.Connection] = []
    connect = db._connect

    def tracked_connect() -> sqlite3.Connection:
        connection = connect()
        opened.append(connection)
        return connection

    monkeypatch.setattr(db, "_connect", tracked_connect)
    lineage = db.lineage_id
    db.entity_metadata(lineage)
    db.last_event_seq()
    db.list_events()
    try:
        for connection in opened:
            with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
                connection.execute("SELECT 1")
    finally:
        for connection in opened:
            connection.close()


def test_rfc3339_offsets_and_exact_milliseconds() -> None:
    assert parse_timestamp("2026-09-27T07:39:38.123-07:00") == parse_timestamp("2026-09-27T22:39:38.123+08:00")
    assert format_timestamp(parse_timestamp("2026-09-27T07:39:38.123-07:00")) == "2026-09-27T14:39:38.123Z"
    assert format_timestamp(-1) == "1969-12-31T23:59:59.999Z"
    assert parse_timestamp("1969-12-31T23:59:59.999Z") == -1
    for invalid in ("2026-09-27", "2026-09-27 14:00:00Z", "20260927T14:00:00Z", "2026-09-27T14:00:00+0800",
                    "2026-09-27T14:00:00+00:60", "9999-12-31T23:59:59.999-23:59", "0001-01-01T00:00:00+23:59"):
        with pytest.raises(ValueError):
            parse_timestamp(invalid)


def test_audit_http_query_validation_and_schema(runtime: Runtime) -> None:
    server = uvicorn.Server(uvicorn.Config(runtime.app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}/api/v1/projects/{runtime.project_id}/audit"
        for query, expected_status in (({"limit": 201}, 422), ({"limit": 0}, 422),
                                       ({"from": "2026-09-27T00:00:00"}, 400),
                                       ({"from": "2026-09-27T14:00:00+00:60"}, 400),
                                       ({"from": "9999-12-31T23:59:59.999-23:59"}, 400),
                                       ({"from": "2026-09-28T00:00:00Z", "to": "2026-09-27T00:00:00Z"}, 400)):
            with pytest.raises(HTTPError) as invalid:
                urlopen(Request(url + "?" + urlencode(query), headers={"Authorization": "Bearer control"}), timeout=5)
            assert invalid.value.code == expected_status
        with pytest.raises(HTTPError) as anonymous:
            urlopen(url, timeout=5)
        assert anonymous.value.code == 401
        with urlopen(Request(url, headers={"Authorization": "Bearer control"}), timeout=5) as response:
            AuditPageModel.model_validate(json.load(response))
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


def test_task_event_checkpoint_and_export_queries_share_public_projection(runtime: Runtime) -> None:
    main, _ = runtime.enroll("timeline-main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    task = runtime.call("task.create", {"title": "timeline", "objective": "query me"}, main)
    task_page_route = runtime.endpoint("/api/v1/projects/{project_id}/tasks/{task_id}/history")
    page = task_page_route(
        runtime.project_id, task["task_id"], authorization="Bearer control", limit=50,
    )
    AuditPageModel.model_validate(page)
    assert page["items"] and any(item["subject_ref"] == f"task/{task['task_id']}" for item in page["items"])

    event_id = page["items"][0]["event_id"]
    event_route = runtime.endpoint("/api/v1/audit/events/{event_id}")
    event = event_route(event_id, project_id=runtime.project_id, authorization="Bearer control")
    assert event["event_id"] == event_id
    assert event["caused_by_command_id"]

    export_route = runtime.endpoint("/api/v1/projects/{project_id}/history/export")
    exported = export_route(runtime.project_id, authorization="Bearer control")
    AuditExportModel.model_validate(exported)
    assert exported["schema"] == "tsunagou.audit-export.v1"
    assert exported["source"] == {"project_id": runtime.project_id, "lineage_id": page["items"][0]["lineage_id"]}
    assert isinstance(exported["exported_at"], str) and exported["items"]

    before = runtime.db.last_event_seq()
    checkpoint = runtime.call("checkpoint.create.user", {"reason": "timeline query"})
    checkpoints_route = runtime.endpoint("/api/v1/projects/{project_id}/checkpoints")
    checkpoints = checkpoints_route(runtime.project_id, authorization="Bearer control", verify=True)
    CheckpointPageModel.model_validate(checkpoints)
    assert checkpoints["current"]["digest"] == checkpoint["checkpoint_digest"]
    assert any(item["digest"] == checkpoint["checkpoint_digest"] and item["status"] == "verified"
               for item in checkpoints["items"])
    verify_route = runtime.endpoint("/api/v1/checkpoints/{checkpoint_digest:path}/verify")
    verified = verify_route(checkpoint["checkpoint_digest"], authorization="Bearer control")
    CheckpointVerificationModel.model_validate(verified)
    assert verified["status"] == "verified"
    assert runtime.db.last_event_seq() > before


def test_task_history_includes_related_entities_without_writing(runtime: Runtime) -> None:
    main, _ = runtime.enroll("timeline-main")
    worker, _ = runtime.enroll("timeline-worker")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    task = runtime.call("task.create", {"title": "related", "objective": "trace relations"}, main)
    runtime.call("task.ready", {"task_id": task["task_id"]}, main)
    runtime.call("task.publish", {"task_id": task["task_id"]}, main)
    claim = runtime.call("task.claim", {"task_id": task["task_id"]}, worker)
    task_ref = f"task/{task['task_id']}"
    message = runtime.call(
        "message.send",
        {"recipient_agent_id": main["agent_id"], "summary": "task evidence", "subject_ref": task_ref},
        worker,
    )
    before = runtime.db.last_event_seq()
    route = runtime.endpoint("/api/v1/projects/{project_id}/tasks/{task_id}/history")
    page = route(runtime.project_id, task["task_id"], limit=200, **runtime.credentials(worker))
    AuditPageModel.model_validate(page)
    after = runtime.db.last_event_seq()
    assert after == before
    refs = {change["subject_ref"] for event in page["items"] for change in event["changes"]}
    assert f"attempt/{claim['attempt_id']}" in refs
    assert f"message/{message['message_id']}" in refs
    assert all(item["project_id"] == runtime.project_id for item in page["items"])


def test_timeline_queries_fail_closed_without_user_authentication(runtime: Runtime) -> None:
    task_route = runtime.endpoint("/api/v1/projects/{project_id}/tasks/{task_id}/history")
    with pytest.raises(HTTPException) as task_error:
        task_route(runtime.project_id, "missing-task")
    assert task_error.value.status_code == 401
    checkpoint_route = runtime.endpoint("/api/v1/projects/{project_id}/checkpoints")
    with pytest.raises(HTTPException) as checkpoint_error:
        checkpoint_route(runtime.project_id)
    assert checkpoint_error.value.status_code == 401
    diagnostics_route = runtime.endpoint("/api/v1/projects/{project_id}/diagnostics")
    diagnostics = diagnostics_route(runtime.project_id, authorization="Bearer control")
    assert diagnostics == {"project_id": runtime.project_id, "items": []}
    with pytest.raises(HTTPException) as diagnostics_error:
        diagnostics_route(runtime.project_id)
    assert diagnostics_error.value.status_code == 401
