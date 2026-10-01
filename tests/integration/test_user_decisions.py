"""User decisions retain their proposal and notify main through the existing UoW."""

from __future__ import annotations

import contextlib
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from fastapi import FastAPI, HTTPException
from tests.integration.test_execution_begin import begin, published
from tests.integration.test_project_timings_http import cli, database_snapshot, http_server
from tests.unit.test_trace_audit import Runtime
from tests.unit.test_trace_audit import runtime as _runtime_fixture
from typer.testing import CliRunner

from tsunagou.bootstrap.container import build_application
from tsunagou.bootstrap.daemon import ProjectDaemon
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.platform.shared_checkpoint import export_shared
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.time import format_timestamp


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


def proposal(runtime, main, subject="design-choice"):
    return runtime.call("user_decision.propose", {
        "kind": "design.change", "proposal_ref": subject,
        "choices": ["approved", "rejected"], "summary": "Keep the demonstrated behavior?",
        "expected_revisions": {"decision": 7},
    }, main)


def resolution(item, choice="approved"):
    return {"decision_id": item["decision_id"], "choice": choice,
            "expected_revisions": {"decision": item["revision"]},
            "proposal_digest": item["proposal_digest"], "reason": "User reviewed the proposal"}


def decisions(runtime, viewer=None):
    return runtime.endpoint("/api/v1/decisions")(**runtime.credentials(viewer))


def test_decision_cli_http_content_times_pending_restart_and_resolve(runtime, monkeypatch):
    clock = 1_790_520_000_000
    monkeypatch.setattr("tsunagou.platform.state.now_ms", lambda: clock)
    main, _ = runtime.enroll("main")
    worker, _ = runtime.enroll("worker")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    item = proposal(runtime, main)
    private = runtime.call("message.send", {
        "recipient_agent_id": worker["agent_id"], "summary": "PRIVATE-DECISION-SUMMARY",
        "payload": {"body": "PRIVATE-DECISION-BODY"},
    }, main)
    runner = CliRunner()
    with http_server(runtime.app, monkeypatch):
        before = database_snapshot(runtime)
        output = runner.invoke(cli.app, ["decision", "list"])
        assert output.exit_code == 0, output.output
        page = json.loads(output.output)
        assert page["project_id"] == runtime.project_id
        row = page["items"][0]
        extra = {key: row[key] for key in ("expected_revision", "input_digest", "payload")}
        row = {key: value for key, value in row.items() if key not in extra}
        assert row == {
            "decision_id": item["decision_id"], "kind": "design.change", "subject_ref": "design-choice",
            "revision": 7, "proposal_digest": item["proposal_digest"], "status": "pending",
            "choices": ["approved", "rejected"], "summary": "Keep the demonstrated behavior?",
            "decision": None, "reason": None,
            "created_at": format_timestamp(clock), "updated_at": format_timestamp(clock),
        }
        # The console's decision panel also reads what the proposer actually asked, the
        # revision the question was raised against, and the digest the answer has to
        # echo back; the local daemon keeps all three beside the choices/summary
        # spellings (see bootstrap/container.py).
        assert extra["expected_revision"] == 7
        assert extra["payload"] == {"choices": ["approved", "rejected"], "summary": "Keep the demonstrated behavior?"}
        assert extra["input_digest"].startswith("sha256:")
        for secret in (private["message_id"], "PRIVATE-DECISION-SUMMARY", "PRIVATE-DECISION-BODY", main["secret_token"]):
            assert secret not in output.output
        clock += 24 * 60 * 60 * 1000
        assert runner.invoke(cli.app, ["decision", "list"]).output == output.output
        assert database_snapshot(runtime) == before
        with pytest.raises(HTTPError) as denied:
            urlopen(cli._daemon_url() + "/api/v1/decisions", timeout=5)
        assert denied.value.code == 401
        headers = {"Authorization": f"Bearer {worker['secret_token']}", "Tsunagou-Session-Id": worker["session_id"],
                   "Tsunagou-Connection-Epoch": str(worker["connection_epoch"])}
        with urlopen(Request(cli._daemon_url() + "/api/v1/decisions", headers=headers), timeout=5) as response:
            assert json.load(response) == page
    runtime.db.release_process_lock()
    rebuilt = build_application()
    try:
        restored = Runtime(rebuilt, runtime.project_id)
        with http_server(rebuilt, monkeypatch):
            assert runner.invoke(cli.app, ["decision", "list"]).output == output.output
            resolved = runner.invoke(cli.app, [
                "decision", "resolve", item["decision_id"], "--choice", "approved",
                "--expected-revision", str(row["revision"]), "--digest", row["proposal_digest"], "--reason", "confirmed",
            ])
            assert resolved.exit_code == 0, resolved.output
            assert json.loads(resolved.output)["status"] == "resolved"
            updated = decisions(restored)["items"][0]
            assert updated["created_at"] == row["created_at"] and updated["updated_at"] == format_timestamp(clock)
            assert updated["summary"] == row["summary"] and updated["choices"] == row["choices"]
            monkeypatch.setattr(cli, "_control_token", lambda: "wrong-control")
            assert "authentication_failed" in runner.invoke(cli.app, ["decision", "list"]).output
            monkeypatch.setattr(cli, "_control_token", lambda: None)
            assert "control_credential_missing" in runner.invoke(cli.app, ["decision", "list"]).output
    finally:
        rebuilt.state.project_database.release_process_lock()


@pytest.mark.parametrize("choice", ["approved", "rejected"])
def test_resolve_notifies_current_main_once_without_resuming_owner(runtime, choice):
    main, _ = runtime.enroll("main")
    worker, _ = runtime.enroll("worker")
    successor, _ = runtime.enroll("successor")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    task = published(runtime.call, main)
    started = begin(runtime.call, task, worker)
    item = proposal(runtime, main, task["task_id"])
    state = runtime.app.state.state_runtime
    assert state.tasks.tasks[task["task_id"]].status == "running"
    assert state.tasks.attempts[started["attempt_id"]].status == "running"
    blocked = runtime.call("task.block", {
        "task_id": task["task_id"], "attempt_id": started["attempt_id"], "reason": "await user decision",
    }, worker)
    with pytest.raises(HTTPException, match="user_decision_pending"):
        begin(runtime.call, blocked, worker)
    independent = published(runtime.call, main)
    other = begin(runtime.call, independent, worker)
    submitted = runtime.call("task.submit", {
        "task_id": independent["task_id"], "attempt_id": other["attempt_id"], "summary": "independent result",
    }, worker)
    runtime.call("task.review.accept", {
        "task_id": independent["task_id"], "result_id": submitted["result_id"], "result_digest": submitted["digest"],
    }, main)
    assert state.tasks.tasks[independent["task_id"]].status == "completed"
    assert decisions(runtime)["items"][0]["status"] == "pending"
    runtime.call("authority.appoint", {"agent_id": successor["agent_id"]})
    task_before = state.capture()["tasks"]
    command_id = "user-reply-idempotent"
    payload = resolution(item, choice)
    result = runtime.call("user_decision.resolve", payload, command_id=command_id)
    notices = [message for message in state.messages.messages.values() if message.kind == "user_decision.resolved"]
    assert len(notices) == 1
    notice = notices[0]
    assert notice.sender_agent_id == "user_control" and notice.recipient_agent_id == successor["agent_id"]
    assert notice.subject_ref == "decision/" + item["decision_id"]
    assert notice.payload == {
        "decision_id": item["decision_id"], "kind": "design.change", "subject_ref": task["task_id"],
        "revision": 7, "proposal_digest": item["proposal_digest"], "status": "resolved",
        "decision": choice, "reason": payload["reason"], "related_task_id": task["task_id"],
    }
    assert state.capture()["tasks"] == task_before
    with contextlib.closing(runtime.db._connect()) as conn:
        outbox = conn.execute(
            "SELECT event_seq,kind,payload_digest FROM outbox WHERE target_ref=?", ("message/" + notice.message_id,),
        ).fetchall()
        assert len(outbox) == 1
        assert outbox[0]["kind"] == "host_wake"
        assert outbox[0]["payload_digest"] == canonical_digest({
            "message_id": notice.message_id, "recipient_agent_id": successor["agent_id"],
        })
        event = conn.execute("SELECT * FROM events WHERE event_seq=?", (outbox[0]["event_seq"],)).fetchone()
        assert event["event_type"] == "user_decision.resolve" and event["caused_by_command_id"] == command_id
    before = database_snapshot(runtime)
    assert runtime.call("user_decision.resolve", payload, command_id=command_id) == result
    assert database_snapshot(runtime) == before
    with pytest.raises(HTTPException):
        runtime.call("inbox.fetch", {"message_id": notice.message_id}, main)
    assert runtime.call("inbox.fetch", {"message_id": notice.message_id}, successor)["payload"] == notice.payload
    # Other project members can see the decision fact, never this private notice's ID/body.
    serialized = json.dumps(runtime.page(worker, limit=200))
    assert item["decision_id"] in serialized and notice.message_id not in serialized
    assert payload["reason"] not in serialized
    runtime.db.release_process_lock()
    rebuilt = build_application()
    try:
        restored = Runtime(rebuilt, runtime.project_id)
        before = database_snapshot(restored)
        assert restored.call("user_decision.resolve", payload, command_id=command_id) == result
        assert database_snapshot(restored) == before
        assert rebuilt.state.state_runtime.messages.messages[notice.message_id].payload == notice.payload
        assert rebuilt.state.state_runtime.tasks.tasks[task["task_id"]].status == "blocked"
    finally:
        rebuilt.state.project_database.release_process_lock()


@pytest.mark.parametrize("bad", ["principal", "digest", "revision", "choice"])
def test_invalid_resolution_preserves_pending_and_emits_no_notice(runtime, bad):
    main, _ = runtime.enroll("main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    item = proposal(runtime, main)
    payload = resolution(item)
    if bad == "digest":
        payload["proposal_digest"] = "sha256:wrong"
    elif bad == "revision":
        payload["expected_revisions"] = {"decision": 8}
    elif bad == "choice":
        payload["choice"] = "invented-option"
    before = database_snapshot(runtime)
    with pytest.raises(HTTPException) as denied:
        runtime.call("user_decision.resolve", payload, main if bad == "principal" else None)
    assert denied.value.status_code == (401 if bad == "principal" else 400)
    assert database_snapshot(runtime) == before
    assert decisions(runtime)["items"][0]["status"] == "pending"
    assert not runtime.app.state.state_runtime.messages.messages


def test_notification_failure_rolls_back_decision_message_and_outbox(runtime, monkeypatch):
    main, _ = runtime.enroll("main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    item = proposal(runtime, main)
    state = runtime.app.state.state_runtime
    send = state.messages.send

    def fail_after_send(**kwargs):
        send(**kwargs)
        raise RuntimeError("notification_fixture_failure")

    monkeypatch.setattr(state.messages, "send", fail_after_send)
    before = database_snapshot(runtime)
    memory = state.capture()
    with pytest.raises(HTTPException, match="notification_fixture_failure"):
        runtime.call("user_decision.resolve", resolution(item))
    assert database_snapshot(runtime) == before and state.capture() == memory


def test_resolution_without_current_main_stays_queryable_and_does_not_invent_a_recipient(runtime):
    main, _ = runtime.enroll("main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    item = proposal(runtime, main)
    runtime.call("authority.revoke", {})
    result = runtime.call("user_decision.resolve", resolution(item), command_id="answer-without-main")
    assert result["status"] == "resolved"
    row = decisions(runtime)["items"][0]
    assert row["decision"] == "approved" and row["proposal_digest"] == item["proposal_digest"]
    assert row["choices"] == ["approved", "rejected"]
    assert not runtime.app.state.state_runtime.messages.messages
    with contextlib.closing(runtime.db._connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM outbox WHERE kind='host_wake'").fetchone()[0] == 0
    before = database_snapshot(runtime)
    assert runtime.call("user_decision.resolve", resolution(item), command_id="answer-without-main") == result
    assert database_snapshot(runtime) == before


def test_object_choices_match_the_public_proposal_digest_and_bad_digest_rolls_back(runtime):
    main, _ = runtime.enroll("main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    payload = {
        "kind": "design.change", "proposal_ref": "design-choice", "expected_revisions": {"decision": 7},
        "choices": [{"choice": "approved", "description": "keep behavior"}, {"choice": "rejected", "description": "revise"}],
        "summary": "Confirm the reviewed design",
    }
    before = database_snapshot(runtime)
    with pytest.raises(HTTPException, match="proposal_digest_mismatch"):
        runtime.call("user_decision.propose", {**payload, "proposal_digest": "sha256:wrong"}, main)
    assert database_snapshot(runtime) == before and decisions(runtime)["items"] == []
    item = runtime.call("user_decision.propose", payload, main)
    row = decisions(runtime)["items"][0]
    assert row["choices"] == payload["choices"] and row["summary"] == payload["summary"]
    assert canonical_digest({
        "subject_ref": row["subject_ref"], "revision": row["revision"],
        "payload": {"choices": row["choices"], "summary": row["summary"]},
    }) == item["proposal_digest"] == row["proposal_digest"]


def test_the_project_objective_is_an_ordinary_decision_the_console_can_read(runtime):
    """项目目标就是一条普通用户决定：主 Agent 提、用户答，答完界面才按它显示。

    目标文字放在 ``summary``（命令里唯一的自由文本位），``kind`` 用约定的保留值；
    没有为它新增命令或字段，见 docs/decisions/2026-10-01-objective-from-dialogue.md。
    界面只认 ``status=resolved`` 的那条（web/assets/js/behavior.js 的 confirmedObjective）。
    """

    main, _ = runtime.enroll("main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    asked = "让两个 Agent 对齐 API 并交付可运行实现"
    item = runtime.call("user_decision.propose", {
        "kind": "project.objective", "proposal_ref": "project/objective/v1",
        "choices": ["确认", "要改"], "summary": asked,
    }, main)

    rows = decisions(runtime)["items"]
    pending = next(entry for entry in rows if entry["decision_id"] == item["decision_id"])
    assert pending["kind"] == "project.objective" and pending["status"] == "pending"
    assert pending["summary"] == asked

    runtime.call("user_decision.resolve", {
        "decision_id": item["decision_id"], "choice": "确认",
        "expected_revisions": {"decision": item["revision"]},
        "proposal_digest": item["proposal_digest"], "reason": "用户确认目标",
    })

    resolved = [entry for entry in decisions(runtime)["items"] if entry["decision_id"] == item["decision_id"]][0]
    assert resolved["status"] == "resolved" and resolved["decision"] == "确认"
    assert resolved["summary"] == asked


def test_decision_list_uses_selected_project_credentials(runtime, tmp_path, monkeypatch):
    main, _ = runtime.enroll("main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    item = proposal(runtime, main)
    second_root = tmp_path / "second"
    (second_root / ".git").mkdir(parents=True)
    project = ProjectRegistry.initialize(second_root, name="second", objective="isolated")
    config = {"TSUNAGOU_PROJECT_ROOT": str(second_root), "TSUNAGOU_STATE_DIR": str(second_root / ".tsunagou/local"),
              "TSUNAGOU_CONTROL_TOKEN": "second-control"}
    second = build_application(config)
    daemon = ProjectDaemon(config)
    daemon.apps = {runtime.project_id: runtime.app, project.project.project_id: second}
    router = FastAPI()
    router.mount("/", daemon)
    try:
        # Exercise real HTTP routing without rerunning daemon's registry startup.
        with http_server(router, monkeypatch):
            url = cli._daemon_url() + "/api/v1/decisions"
            for selected, token, expected_status in [
                (None, "control", 400), (project.project.project_id, "control", 401),
                (runtime.project_id, "second-control", 401),
            ]:
                headers = {"Authorization": "Bearer " + token}
                if selected:
                    headers["Tsunagou-Project-Id"] = selected
                with pytest.raises(HTTPError) as denied:
                    urlopen(Request(url, headers=headers), timeout=5)
                assert denied.value.code == expected_status
            for selected, token, expected in [(runtime.project_id, "control", [item["decision_id"]]),
                                               (project.project.project_id, "second-control", [])]:
                request = Request(url, headers={"Authorization": "Bearer " + token, "Tsunagou-Project-Id": selected})
                with urlopen(request, timeout=5) as response:
                    page = json.load(response)
                assert page["project_id"] == selected
                assert [row["decision_id"] for row in page["items"]] == expected
    finally:
        second.state.project_database.release_process_lock()


def test_checkpoint_retains_proposal_and_missing_content_stays_unknown(runtime):
    main, _ = runtime.enroll("main")
    runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
    item = proposal(runtime, main)
    state = runtime.app.state.state_runtime
    snapshot = state.capture()
    exported = export_shared(snapshot)["lifecycle"][0]["decisions"][item["decision_id"]]
    assert exported["choices"] == ["approved", "rejected"] and exported["summary"] == "Keep the demonstrated behavior?"
    # A historical record without its original text cannot be reconstructed from a digest.
    stored = snapshot["lifecycle"]["decisions"][item["decision_id"]]
    del stored["choices"], stored["summary"]
    state.restore(snapshot)
    row = decisions(runtime)["items"][0]
    assert row["choices"] is None and row["summary"] is None
    assert row["proposal_digest"] == item["proposal_digest"]
