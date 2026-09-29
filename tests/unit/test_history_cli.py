import importlib
import json
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from typer.testing import CliRunner

cli = importlib.import_module("tsunagou.cli.app")
ROOT = Path(__file__).resolve().parents[2]


def test_diagnostic_cli_encodes_filters_without_mutation(monkeypatch):
    calls = []

    def request(method, path, **headers):
        calls.append((method, path))
        return {"project_id": "project-1", "items": []}

    monkeypatch.setattr(cli, "_control_token", lambda: "private-sentinel")
    monkeypatch.setattr(cli, "_daemon_request", request)
    result = CliRunner().invoke(cli.app, ["project", "diagnostics", "project-1", "--json",
        "--message-id", "message-1", "--task-id", "task-1", "--from", "2026-09-28T13:00:00+08:00",
        "--to", "2026-09-28T14:00:00Z"])
    assert result.exit_code == 0 and json.loads(result.output)["items"] == []
    assert calls[0][0] == "GET"
    assert parse_qs(urlparse(calls[0][1]).query) == {
        "message_id": ["message-1"], "task_id": ["task-1"],
        "from": ["2026-09-28T13:00:00+08:00"], "to": ["2026-09-28T14:00:00Z"],
    }
    assert "private-sentinel" not in result.output


def test_history_cli_uses_authenticated_http_and_preserves_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    page = json.loads((ROOT / "protocol/fixtures/valid/audit-page.json").read_text())
    calls: list[tuple] = []

    def request(method: str, path: str, **headers: object) -> dict:
        calls.append((method, path, headers))
        return page

    monkeypatch.setattr(cli, "_control_token", lambda: "private-control-sentinel")
    monkeypatch.setattr(cli, "_daemon_request", request)
    result = CliRunner().invoke(cli.app, [
        "project", "history", "project-1", "--from", "2026-09-27T01:00:00+08:00", "--to", "2026-09-27T23:00:00Z",
        "--actor", "agent/worker-1", "--subject", "task/task-1", "--limit", "200", "--cursor", "opaque-cursor", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == page
    method, path, headers = calls[0]
    assert method == "GET"
    assert urlparse(path).path == "/api/v1/projects/project-1/history"
    assert parse_qs(urlparse(path).query) == {
        "from": ["2026-09-27T01:00:00+08:00"], "to": ["2026-09-27T23:00:00Z"],
        "actor_ref": ["agent/worker-1"], "subject_ref": ["task/task-1"], "limit": ["200"], "cursor": ["opaque-cursor"],
    }
    assert headers == {"authorization": "Bearer private-control-sentinel"}
    assert "private-control-sentinel" not in result.output
    human = CliRunner().invoke(cli.app, ["project", "history", "project-1"])
    assert human.exit_code == 0
    assert "unknown_time" in human.output and "as_of_event_seq=2" in human.output


def test_history_cli_rejects_invalid_page_without_printing_server_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_control_token", lambda: "control")
    monkeypatch.setattr(cli, "_daemon_request", lambda *args, **kwargs: {"secret_token": "do-not-echo"})
    result = CliRunner().invoke(cli.app, ["--json", "project", "history", "project-1"])
    assert result.exit_code == 5
    assert json.loads(result.output)["error"] == "invalid_audit_response"
    assert "do-not-echo" not in result.output


@pytest.mark.parametrize(("status", "exit_code"), [(401, 3), (403, 3), (400, 2), (422, 2), (503, 5)])
def test_history_cli_keeps_auth_and_input_errors_distinct(
    monkeypatch: pytest.MonkeyPatch, status: int, exit_code: int,
) -> None:
    def request(*args: object, **kwargs: object) -> dict:
        raise RuntimeError("http_error") from urllib.error.HTTPError("http://localhost", status, "fixture", {}, None)

    monkeypatch.setattr(cli, "_control_token", lambda: "control")
    monkeypatch.setattr(cli, "_daemon_request", request)
    result = CliRunner().invoke(cli.app, ["project", "history", "project-1", "--json"])
    assert result.exit_code == exit_code
    assert json.loads(result.output)["error"] == "http_error"


def test_history_cli_missing_credential_and_invalid_limit_do_not_issue_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_control_token", lambda: None)
    missing = CliRunner().invoke(cli.app, ["project", "history", "project-1", "--json"])
    assert missing.exit_code == 3
    assert json.loads(missing.output)["status"] == "control_credential_missing"
    assert CliRunner().invoke(cli.app, ["project", "history", "project-1", "--limit", "201"]).exit_code == 2


def test_related_query_cli_commands_use_shared_routes_and_dto_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    page = json.loads((ROOT / "protocol/fixtures/valid/audit-page.json").read_text())
    event = page["items"][0]
    export = {
        "schema": "tsunagou.audit-export.v1", "exported_at": "2026-09-27T14:00:00.000Z",
        "source": {"project_id": "project-1", "lineage_id": "lineage-1"},
        "projection_version": "v1", "as_of_event_seq": 2, "next_cursor": None, "items": page["items"],
    }
    checkpoint = {
        "project_id": "project-1", "current": {"digest": "sha256:checkpoint", "status": "sealed", "through_event_seq": 2},
        "items": [{
            "digest": "sha256:checkpoint", "parent_digest": None, "project_id": "project-1", "lineage_id": "lineage-1",
            "through_event_seq": 2, "format_version": 1, "schema_bundle_digest": "sha256:schema",
            "created_at": "2026-09-27T14:00:00.000Z", "created_by": "user_control", "reason": "test",
            "projection_version": "shared-v1", "verified_at": None, "status": "sealed", "artifact_digests": [],
        }],
        "projection_version": "v1", "as_of_event_seq": 2,
    }
    verified = {
        "digest": "sha256:checkpoint", "status": "verified", "project_id": "project-1", "lineage_id": "lineage-1",
        "through_event_seq": 2, "created_at": "2026-09-27T14:00:00.000Z", "verified_at": None, "git_anchors": [],
    }
    calls: list[str] = []

    def request(method: str, path: str, **headers: object) -> dict:
        calls.append(path)
        if path.startswith("/api/v1/projects/project-1/history/export"):
            return export
        if "/tasks/task-1/history" in path:
            return page
        if path.startswith("/api/v1/audit/events/event-1"):
            return event
        if path.startswith("/api/v1/projects/project-1/checkpoints"):
            return checkpoint
        if path.startswith("/api/v1/checkpoints/sha256%3Acheckpoint/verify"):
            return verified
        raise AssertionError(path)

    monkeypatch.setattr(cli, "_control_token", lambda: "control")
    monkeypatch.setattr(cli, "_daemon_request", request)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["project", "history", "project-1", "--export", "--json"]).exit_code == 0
    assert runner.invoke(cli.app, ["task", "history", "task-1", "--project-id", "project-1", "--json"]).exit_code == 0
    assert runner.invoke(cli.app, ["audit", "event", "event-1", "--project-id", "project-1", "--json"]).exit_code == 0
    assert runner.invoke(cli.app, ["checkpoint", "list", "project-1", "--verify"]).exit_code == 0
    assert runner.invoke(cli.app, ["checkpoint", "verify", "sha256:checkpoint"]).exit_code == 0
    assert any(path.startswith("/api/v1/projects/project-1/history/export") for path in calls)
    assert any("/tasks/task-1/history" in path for path in calls)
    assert any(path.startswith("/api/v1/audit/events/event-1") for path in calls)
    assert any(path.startswith("/api/v1/projects/project-1/checkpoints") for path in calls)
