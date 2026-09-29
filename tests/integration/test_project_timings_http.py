"""CLI public Result timing through real HTTP, SQLite replay and same-db restart."""

from __future__ import annotations

import contextlib
import importlib
import json
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from fastapi import HTTPException
from tests.unit.test_trace_audit import Runtime
from tests.unit.test_trace_audit import runtime as _runtime_fixture
from typer.testing import CliRunner

from tsunagou.bootstrap.container import build_application
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import format_timestamp

cli = importlib.import_module("tsunagou.cli.app")


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


@contextlib.contextmanager
def http_server(app: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        monkeypatch.setattr(cli, "_daemon_url", lambda: f"http://127.0.0.1:{port}")
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


def database_snapshot(runtime: Runtime) -> list[str]:
    with contextlib.closing(runtime.db._connect()) as conn:
        return list(conn.iterdump())


def test_private_submit_public_result_and_repeat_reads_replay_restart(runtime: Runtime, monkeypatch):
    clock = 1_790_520_000_000
    monkeypatch.setattr("tsunagou.platform.state.now_ms", lambda: clock)
    main, _ = runtime.enroll("main")
    worker, _ = runtime.enroll("worker")
    recipient, _ = runtime.enroll("private-recipient")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    task = runtime.call("task.create", {"title": "public", "objective": "check timing"}, main)
    runtime.call("task.ready", {"task_id": task["task_id"]}, main)
    published = runtime.call("task.publish", {"task_id": task["task_id"]}, main)
    started = runtime.call("task.begin", {"task_id": task["task_id"], "expected_task_revision": published["revision"]}, worker)
    # A new begin command for a running Attempt is a resume, not a new start.
    clock += 1000
    resumed = runtime.call("task.begin", {"task_id": task["task_id"], "expected_task_revision": started["revision"]}, worker)
    assert resumed["attempt_id"] == started["attempt_id"]
    begins = [row for row in runtime.page(limit=200)["items"] if row["action"] == "task.begin"]
    assert len(begins) == 1  # No new domain fact for an unchanged running Attempt.
    message = runtime.call("message.send", {
        "recipient_agent_id": recipient["agent_id"], "summary": "PRIVATE-SUMMARY",
        "payload": {"content": "PRIVATE-BODY"},
    }, worker)
    clock += 4123
    command_id = new_id()
    submit_payload = {"task_id": task["task_id"], "attempt_id": started["attempt_id"], "summary": "result",
                      "evidence_refs": [f"message/{message['message_id']}"]}
    submitted = runtime.call("task.submit", submit_payload, worker, command_id=command_id)
    submit_event = next(row for row in runtime.page(worker, limit=200)["items"] if row["action"] == "task.submit")
    for viewer in (None, main):
        assert all(row["action"] != "task.submit" for row in runtime.page(viewer, limit=200)["items"])
    with pytest.raises(HTTPException) as hidden:
        runtime.endpoint("/api/v1/audit/events/{event_id}")(
            submit_event["event_id"], project_id=runtime.project_id, authorization="Bearer control",
        )
    assert hidden.value.status_code in {403, 404}
    exported = runtime.endpoint("/api/v1/projects/{project_id}/history/export")(
        runtime.project_id, authorization="Bearer control", limit=200,
    )
    assert all(row["action"] != "task.submit" for row in exported["items"])
    clock += 2000
    runtime.call("task.review.accept", {
        "task_id": task["task_id"], "result_id": submitted["result_id"], "result_digest": submitted["digest"],
        "slot_id": "main", "evidence_refs": [], "reason": "verified",
    }, main)
    args = ["project", "timings", runtime.project_id, "--task-id", task["task_id"], "--json"]
    runner = CliRunner()
    with http_server(runtime.app, monkeypatch):
        before = database_snapshot(runtime)
        output = runner.invoke(cli.app, args)
        assert output.exit_code == 0, output.output
        row = json.loads(output.output)["items"][0]
        assert row["attempt_id"] == started["attempt_id"] and row["owner_agent_id"] == worker["agent_id"]
        assert row["submitted_at"] == submit_event["occurred_at"] and row["submitted_source"] == "result_created_at"
        assert row["begin_events"] == 1 and row["submit_events"] == 0
        assert row["work_elapsed"] == {"elapsed_ms": 5123, "clock_status": "ok"}
        assert row["review_wait_elapsed"] == {"elapsed_ms": 2000, "clock_status": "ok"}
        assert row["review_action"] == "task.review.accept" and row["state"] == "completed"
        for secret in (message["message_id"], "PRIVATE-SUMMARY", "PRIVATE-BODY", worker["secret_token"], worker["session_id"]):
            assert secret not in output.output
        assert runner.invoke(cli.app, args).output == output.output
        assert database_snapshot(runtime) == before
        clock += 9999
        assert runtime.call("task.submit", submit_payload, worker, command_id=command_id) == submitted
        assert database_snapshot(runtime) == before
        assert runner.invoke(cli.app, args).output == output.output
        monkeypatch.setattr(cli, "_control_token", lambda: "wrong-token")
        denied = runner.invoke(cli.app, args)
        assert denied.exit_code == 3 and "items" not in denied.output
        monkeypatch.setattr(cli, "_control_token", lambda: "control")
    runtime.db.release_process_lock()
    rebuilt = build_application()
    try:
        restored = Runtime(rebuilt, runtime.project_id)
        with http_server(rebuilt, monkeypatch):
            before = database_snapshot(restored)
            assert runner.invoke(cli.app, args).output == output.output
            assert database_snapshot(restored) == before
    finally:
        rebuilt.state.project_database.release_process_lock()


def test_rework_attempts_keep_exact_times_after_running_restart_resume(runtime: Runtime, monkeypatch):
    clock = 1_790_520_000_000
    monkeypatch.setattr("tsunagou.platform.state.now_ms", lambda: clock)
    main, _ = runtime.enroll("main")
    worker, _ = runtime.enroll("worker")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    task = runtime.call("task.create", {"title": "rework", "objective": "keep separate Attempt intervals"}, main)
    runtime.call("task.ready", {"task_id": task["task_id"]}, main)
    published = runtime.call("task.publish", {"task_id": task["task_id"]}, main)
    first = runtime.call("task.begin", {"task_id": task["task_id"], "expected_task_revision": published["revision"]}, worker)
    first_start = format_timestamp(clock)
    clock += 1000
    submitted = runtime.call("task.submit", {
        "task_id": task["task_id"], "attempt_id": first["attempt_id"], "summary": "first result",
    }, worker)
    first_submit = format_timestamp(clock)
    clock += 2000
    runtime.call("task.review.request_changes", {
        "task_id": task["task_id"], "result_id": submitted["result_id"], "result_digest": submitted["digest"],
        "slot_id": "main", "evidence_refs": [], "reason": "needs rework",
    }, main)
    first_review = format_timestamp(clock)
    clock += 10_000
    runtime.call("task.ready", {"task_id": task["task_id"]}, main)
    republished = runtime.call("task.publish", {"task_id": task["task_id"]}, main)
    second = runtime.call("task.begin", {"task_id": task["task_id"], "expected_task_revision": republished["revision"]}, worker)
    second_start = format_timestamp(clock)
    assert second["attempt_id"] != first["attempt_id"]
    runtime.db.release_process_lock()
    rebuilt = build_application()
    try:
        restored = Runtime(rebuilt, runtime.project_id)
        clock += 5000
        resumed = restored.call("task.begin", {
            "task_id": task["task_id"], "expected_task_revision": second["revision"],
        }, worker)
        assert resumed["attempt_id"] == second["attempt_id"]
        clock += 3000
        submitted = restored.call("task.submit", {
            "task_id": task["task_id"], "attempt_id": second["attempt_id"], "summary": "revised result",
        }, worker)
        second_submit = format_timestamp(clock)
        clock += 4000
        restored.call("task.review.accept", {
            "task_id": task["task_id"], "result_id": submitted["result_id"], "result_digest": submitted["digest"],
            "slot_id": "main", "evidence_refs": [], "reason": "verified",
        }, main)
        with http_server(rebuilt, monkeypatch):
            output = CliRunner().invoke(cli.app, ["project", "timings", runtime.project_id, "--json"])
            assert output.exit_code == 0, output.output
            rows = {item["attempt_id"]: item for item in json.loads(output.output)["items"]}
        old, current = rows[first["attempt_id"]], rows[second["attempt_id"]]
        assert (old["started_at"], old["submitted_at"], old["reviewed_at"]) == (first_start, first_submit, first_review)
        assert (current["started_at"], current["submitted_at"], current["reviewed_at"]) == (
            second_start, second_submit, format_timestamp(clock),
        )
        assert old["state"] == "orphaned" and old["review_action"] == "task.review.request_changes"
        assert current["state"] == "completed" and current["review_action"] == "task.review.accept"
        assert old["work_elapsed"]["elapsed_ms"] == 1000 and old["review_wait_elapsed"]["elapsed_ms"] == 2000
        assert current["work_elapsed"]["elapsed_ms"] == 8000 and current["review_wait_elapsed"]["elapsed_ms"] == 4000
        for row in rows.values():
            assert row["begin_events"] == row["submit_events"] == 1
            assert row["submitted_source"] == "task_submit_event"
    finally:
        rebuilt.state.project_database.release_process_lock()
