"""Join inherits the console selection, never cwd or an implicit worker role."""

from __future__ import annotations

import importlib
import json

import pytest
from typer.testing import CliRunner

from tsunagou.application import onboarding
from tsunagou.platform.enrollment_store import EnrollmentStore

cli = importlib.import_module("tsunagou.cli.app")
runner = CliRunner()


@pytest.fixture
def join_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "intents"))
    monkeypatch.setenv("TSUNAGOU_ROUTING_DIR", str(tmp_path / "routes"))
    monkeypatch.setenv("CODEX_THREAD_ID", "fixture-original-thread")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "fixture-private-pipe")
    for name in ("TSUNAGOU_PROJECT_ROOT", "TSUNAGOU_PROJECT_ID", "TSUNAGOU_STATE_DIR", "TSUNAGOU_DAEMON_URL"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "chosen-project"
    (root / ".tsunagou").mkdir(parents=True)
    (root / ".tsunagou/project.json").write_text(json.dumps({"project_id": "chosen-project-id"}))
    outside = tmp_path / "unrelated-directory"
    outside.mkdir()
    monkeypatch.chdir(outside)

    class Host:
        def __init__(self, endpoint, thread):
            assert endpoint == "fixture-private-pipe"
            self.thread = thread

        def call_tool(self, name, args):
            assert name == "read_thread" and args["threadId"] == self.thread
            return {"thread": {"id": self.thread}}

        def close(self):
            pass

    monkeypatch.setattr(onboarding, "NativeAppToolsClient", Host)
    calls = []

    def connect(operations, *, adapter, role, profile, request_file):
        runtime = operations.runtime()
        request = onboarding.read_codex_request(request_file, runtime)
        calls.append((runtime.project_root, role, request["conversation_id"]))
        onboarding.write_codex_route(request, runtime, request_file.parent)
        return {
            "status": "enrolled",
            "project_id": runtime.project_id,
            "agent_id": "fixture-agent",
            "role": role,
            "host_registration": "unchanged:tsunagou",
            "session": {"status": "ready", "connection_epoch": 1},
            "next": "call_context__project_read_in_original_conversation",
        }

    monkeypatch.setattr("tsunagou.application.agent_connection.connect_agent", connect)
    return EnrollmentStore(), root, outside, calls


@pytest.mark.parametrize("role", ["main", "worker"])
def test_join_uses_console_root_and_role_from_unrelated_cwd_and_retries_same_agent(join_setup, role):
    store, root, outside, calls = join_setup
    pending = store.create(project_id="chosen-project-id", project_root=root, role=role, nickname="fixture")
    first = runner.invoke(cli.app, ["agent", "join"])
    assert first.exit_code == 0, first.output
    again = runner.invoke(cli.app, ["agent", "join"])
    assert again.exit_code == 0, again.output
    a, b = json.loads(first.output), json.loads(again.output)
    assert a["project_id"] == "chosen-project-id" and a["role"] == role
    assert a["agent_id"] == b["agent_id"] == "fixture-agent"
    assert a["enrollment_id"] == pending["enrollment_id"]
    assert calls == [(root, role, "fixture-original-thread")] * 2
    assert not (outside / ".tsunagou").exists()
    assert cli._selected_project_root.get() is None
    route = json.loads(
        (onboarding.codex_routing_directory() / (onboarding.conversation_key("fixture-original-thread") + ".json")).read_text()
    )
    assert route["console_enrollment"]["requested_role"] == role
    assert route["console_enrollment"]["enrollment_id"] == pending["enrollment_id"]
    assert "fixture-private-pipe" not in first.output and "fixture-original-thread" not in first.output


def test_no_pending_does_not_initialize_or_call_connect(join_setup):
    _store, _root, outside, calls = join_setup
    result = runner.invoke(cli.app, ["agent", "join"])
    assert result.exit_code == 4
    assert "enrollment_not_pending" in result.output
    assert not calls and not (outside / ".tsunagou").exists()


def test_join_cannot_override_console_role(join_setup):
    store, root, _outside, calls = join_setup
    store.create(project_id="chosen-project-id", project_root=root, role="worker")
    result = runner.invoke(cli.app, ["agent", "join", "--role", "main"])
    assert result.exit_code != 0 and not calls


def test_unverified_host_cannot_claim_intent(join_setup, monkeypatch):
    store, root, _outside, calls = join_setup
    pending = store.create(project_id="chosen-project-id", project_root=root, role="main")

    class WrongHost:
        def __init__(self, *_):
            pass

        def call_tool(self, *_):
            return {"thread": {"id": "another-thread"}}

        def close(self):
            pass

    monkeypatch.setattr(onboarding, "NativeAppToolsClient", WrongHost)
    result = runner.invoke(cli.app, ["agent", "join"])
    assert result.exit_code == 4 and "desktop_conversation_mismatch" in result.output
    assert store.get(pending["enrollment_id"])["status"] == "pending" and not calls


def test_foreign_project_manifest_is_rejected_before_claim(join_setup):
    store, root, _outside, calls = join_setup
    pending = store.create(project_id="expected-project", project_root=root, role="main")
    result = runner.invoke(cli.app, ["agent", "join"])
    assert result.exit_code == 4 and "onboarding_project_mismatch" in result.output
    assert store.get(pending["enrollment_id"])["status"] == "pending" and not calls


def test_connect_failure_keeps_intent_owned_for_retry(join_setup, monkeypatch):
    store, root, _outside, calls = join_setup
    pending = store.create(project_id="chosen-project-id", project_root=root, role="main")

    def fail(*args, **kwargs):
        raise RuntimeError("daemon_unreachable")

    monkeypatch.setattr("tsunagou.application.agent_connection.connect_agent", fail)
    result = runner.invoke(cli.app, ["agent", "join"])
    assert result.exit_code == 4 and "daemon_unreachable" in result.output
    record = store.get(pending["enrollment_id"])
    assert record["thread_id"] == "fixture-original-thread" and record["status"] == "failed"
    monkeypatch.setenv("CODEX_THREAD_ID", "another-thread")
    result = runner.invoke(cli.app, ["agent", "join"])
    assert result.exit_code == 4 and not calls


def test_route_refresh_preserves_receipt_binding(join_setup):
    store, root, _outside, _calls = join_setup
    pending = store.create(project_id="chosen-project-id", project_root=root, role="main")
    assert runner.invoke(cli.app, ["agent", "join"]).exit_code == 0
    from tsunagou.platform.runtime_context import resolve_runtime

    runtime = resolve_runtime(root)
    request_file = onboarding.prepare_codex_request(runtime)
    request = onboarding.read_codex_request(request_file, runtime)
    route = onboarding.write_codex_route(request, runtime, request_file.parent)
    assert json.loads(route.read_text())["console_enrollment"]["enrollment_id"] == pending["enrollment_id"]


@pytest.mark.parametrize("conflict", ["project", "root"])
def test_existing_foreign_route_does_not_consume_claim(join_setup, conflict):
    store, root, _outside, calls = join_setup
    pending = store.create(project_id="chosen-project-id", project_root=root, role="main")
    route = onboarding.codex_routing_directory() / (onboarding.conversation_key("fixture-original-thread") + ".json")
    route.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "project_id": "different-project" if conflict == "project" else "chosen-project-id",
        "project_root": str(root.parent / "different-root") if conflict == "root" else str(root),
    }
    route.write_text(json.dumps(value), encoding="utf-8")
    result = runner.invoke(cli.app, ["agent", "join"])
    assert result.exit_code == 4 and "host_route_project_conflict" in result.output
    assert store.get(pending["enrollment_id"])["status"] == "pending" and not calls
    assert json.loads(route.read_text()) == value


def test_missing_manifest_cannot_be_substituted_by_environment(join_setup, monkeypatch):
    store, root, _outside, calls = join_setup
    pending = store.create(project_id="chosen-project-id", project_root=root, role="main")
    (root / ".tsunagou/project.json").unlink()
    monkeypatch.setenv("TSUNAGOU_PROJECT_ID", "chosen-project-id")
    result = runner.invoke(cli.app, ["agent", "join"])
    assert result.exit_code == 4 and "onboarding_project_mismatch" in result.output
    assert store.get(pending["enrollment_id"])["status"] == "pending" and not calls
