from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tsunagou.application import host_wake_runner
from tsunagou.application.host_wake_runner import run_host_operation, sanitize_diagnostics


def test_unknown_host_and_deepseek_fail_closed(tmp_path: Path) -> None:
    for host, code in [("deepseek", "deepseek_wake_identity_required"), ("unknown", "host_runner_unsupported")]:
        value = run_host_operation("wake", adapter=host, conversation_id="ses_example", project_root=tmp_path, message_id="m1")
        assert value["result"] == ("failed" if host == "deepseek" else "unsupported")
        assert value["error_code"] == code
        assert value["turn_started"] is False


def test_runner_timeout_is_unknown_and_does_not_expose_process_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "pwsh")

    def timeout(*_args: Any, **_kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(["secret-path", "private-conversation"], 25, output="private output")

    monkeypatch.setattr(subprocess, "run", timeout)
    value = run_host_operation("wake", adapter="opencode", conversation_id="ses_example", project_root=tmp_path, message_id="m1")
    assert value["result"] == "unknown"
    assert value["error_code"] == "host_operation_timeout"
    assert "private" not in json.dumps(value)


@pytest.mark.parametrize(("outcome", "category", "stage", "exit_code"), [
    ("spawn", "spawn_failed", "spawn", None),
    ("nonzero", "process_nonzero", "process", 9),
    ("parse", "powershell_parse_error", "process", 1),
    ("json", "invalid_json", "response", 0),
    ("shape", "invalid_response", "response", 0),
    ("malformed_result", "invalid_response", "response", 0),
    ("timeout", "timeout", "process", None),
])
def test_runner_failure_diagnostics_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str, category: str, stage: str, exit_code: int | None,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "powershell.exe")
    monkeypatch.setattr(host_wake_runner, "_interpreter_version", lambda _: "5.1.26100.0")

    def execute(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if outcome == "spawn":
            raise OSError("secret-path private-token")
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("private-session", 25, output="private-token")
        stdout = {"shape": "[]", "malformed_result": '{"result": []}'}.get(outcome, "secret-invalid-json")
        stderr = "private-token private-session secret-path " + ("ParserError" if outcome == "parse" else "error")
        return subprocess.CompletedProcess([], exit_code or 0, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", execute)
    value = run_host_operation("wake", adapter="opencode", conversation_id="ses_private", project_root=tmp_path, message_id="m1")
    assert value["result"] == "unknown"
    assert value["diagnostics"] == {
        "stage": stage, "interpreter": "powershell", "interpreter_version": "5.1.26100.0",
        "exit_code": exit_code, "error_class": category,
    }
    assert all(secret not in json.dumps(value) for secret in ("secret", "private", "ses_private", str(tmp_path)))


def test_diagnostic_sanitizer_rejects_untrusted_values() -> None:
    assert sanitize_diagnostics({
        "stage": ["secret"], "interpreter": {"private": True}, "interpreter_version": "7.0 secret",
        "exit_code": True, "error_class": "private-token", "stderr": "secret",
    }) == {"stage": "unknown", "interpreter": None, "interpreter_version": None, "exit_code": None, "error_class": None}
    assert sanitize_diagnostics("secret") is None


def test_runner_ignores_untrusted_script_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "pwsh")
    monkeypatch.setattr(host_wake_runner, "_interpreter_version", lambda _: "7.5.2")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: subprocess.CompletedProcess([], 0, json.dumps({
        "result": "unknown", "error_code": "host_api_failed",
        "diagnostics": {"stage": ["secret"], "error_class": "private"},
    }), "private stderr"))
    value = run_host_operation("status", adapter="opencode", conversation_id="ses_private", project_root=tmp_path, message_id="m1")
    assert value["diagnostics"]["stage"] == "host_operation"
    assert value["diagnostics"]["error_class"] == "host_operation_error"
    assert "private" not in json.dumps(value)


def test_packaged_runner_is_ansi_safe_for_windows_powershell() -> None:
    # 5.1 interprets BOM-less scripts as ANSI; all packaged source must be ASCII.
    Path(host_wake_runner.__file__).with_suffix(".ps1").read_bytes().decode("ascii")


@pytest.mark.parametrize("interpreter", ["pwsh", "powershell"])
@pytest.mark.parametrize("scenario", [
    "idle", "busy", "queued", "delivered", "missing", "worktree", "missing_location",
    "version", "service_version", "malformed", "array_state", "stderr",
])
def test_fixed_powershell_original_session_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, interpreter: str,
) -> None:
    executable = shutil.which(interpreter)
    if executable is None:
        pytest.skip(f"{interpreter} is not installed")
    monkeypatch.setattr(shutil, "which", lambda name: executable if name == interpreter else None)
    tmp_path = tmp_path / "测试 空间"
    tmp_path.mkdir()
    message = "message-example"
    request_id = "msg_tsunagou_" + hashlib.sha256(message.encode()).hexdigest()
    posts: list[dict[str, Any]] = []
    (tmp_path / "worktree").mkdir()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def do_GET(self) -> None:
            code = 200
            if self.path == "/api/info":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"version": "9.0.0" if scenario == "service_version" else "2.0.18"}).encode())
                return
            if self.path.endswith("/active"):
                data: Any = {"ses_example": {"type": "running"}} if scenario == "busy" else {}
                if scenario == "malformed":
                    data = None
                if scenario == "array_state":
                    data = []
            elif self.path.endswith("/inbox"):
                data = [{"id": request_id}] if scenario == "queued" else []
            elif "/message/" in self.path:
                data = {"id": request_id} if scenario == "delivered" else None
                code = 200 if scenario == "delivered" else 404
            else:
                data = {"id": "ses_example", "location": {"directory": str(tmp_path)}}
                if scenario == "worktree":
                    data["location"]["directory"] = str(tmp_path / "worktree")
                if scenario == "missing_location":
                    data["location"] = {}
                if scenario == "missing":
                    code = 404
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": data}).encode())

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            posts.append(payload)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": {"id": payload["id"], "sessionID": "ses_example"}}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    launcher = tmp_path / "opencode.ps1"
    native_cli = tmp_path / "mock_cli.py"
    native_cli.write_text(
        "import sys, json, urllib.request, urllib.error\n"
        "args = sys.argv[1:]\n"
        + ("sys.stderr.write('private-stderr\\n')\n" if scenario == "stderr" else "")
        + "if args[0] == '--version': print('opencode v"
        + ("9.0.0" if scenario == "version" else "2.0.18") + "'); sys.exit(0)\n"
        + f"base = 'http://127.0.0.1:{server.server_port}'\n"
        + "if args[0] == 'service': print(base); sys.exit(0)\n"
        + "body = json.dumps(json.loads(args[4])).encode() if len(args) > 3 else None\n"
        + "req = urllib.request.Request(base + args[2], data=body, method=args[1], headers={'Content-Type':'application/json'})\n"
        + "try:\n"
        + " with urllib.request.urlopen(req) as r: print(r.read().decode('utf-8'))\n"
        + "except urllib.error.HTTPError as e:\n"
        + " print(json.dumps({'_tag':'MessageNotFoundError'})); sys.exit(1)\n",
        encoding="utf-8",
    )
    # Same final native argument boundary as the installed OpenCode npm shim.
    launcher.write_text(
        f"& '{sys.executable.replace(chr(39), chr(39) * 2)}' \"$PSScriptRoot/mock_cli.py\" $args\nexit $LASTEXITCODE\n",
        encoding="utf-8-sig",
    )
    import os
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    try:
        value = run_host_operation("wake", adapter="opencode", conversation_id="ses_example", project_root=tmp_path, message_id=message)
        assert value["diagnostics"]["interpreter"] == interpreter
        assert value["diagnostics"]["interpreter_version"] is not None
        assert value["diagnostics"]["exit_code"] == 0
        assert value["turn_started"] is False
        if scenario in {"idle", "busy", "worktree", "stderr"}:
            assert value["result"] == "queued", value
            assert len(posts) == 1
            assert posts[0]["delivery"] == "queue"
            assert posts[0]["id"] == request_id
            assert "permissions" not in posts[0]
            assert posts[0]["text"] == (
                "Read your own Tsunagou project context and inbox, then handle message "
                + message + "; respect existing authorization."
            )
        else:
            assert posts == []
            if scenario == "queued":
                assert value["result"] == "queued"
            elif scenario == "delivered":
                assert value["result"] == "request_already_delivered"
            else:
                assert value["error_code"] is not None
        assert "ses_example" not in json.dumps(value)
        assert str(server.server_port) not in json.dumps(value)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
