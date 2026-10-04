from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tsunagou.application.host_wake_runner import run_host_operation


def test_unknown_host_and_deepseek_fail_closed(tmp_path: Path) -> None:
    for host, code in [("deepseek", "deepseek_form_unverified"), ("unknown", "host_runner_unsupported")]:
        value = run_host_operation("wake", adapter=host, conversation_id="ses_example", project_root=tmp_path, message_id="m1")
        assert value["result"] == "unsupported"
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


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell runner integration needs pwsh")
@pytest.mark.parametrize("scenario", [
    "idle", "busy", "queued", "delivered", "missing", "worktree", "missing_location",
    "version", "service_version", "malformed", "array_state",
])
def test_fixed_powershell_original_session_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str,
) -> None:
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
    launcher.write_text(
        "if ($args[0] -eq '--version') { Write-Output 'opencode v"
        + ("9.0.0" if scenario == "version" else "2.0.18")
        + "'; exit 0 } elseif ($args[0] -eq 'service') { Write-Output 'http://127.0.0.1:"
        + str(server.server_port) + "'; exit 0 }\n"
        + "$params = @{Uri='http://127.0.0.1:" + str(server.server_port) + "' + $args[2];Method=$args[1]}\n"
        + "if ($args.Count -gt 3) {$params.Body=[Text.Encoding]::UTF8.GetBytes($args[4]);$params.ContentType='application/json'}\n"
        + "try {Invoke-RestMethod @params | ConvertTo-Json -Depth 9 -Compress; exit 0} catch {\n"
        + "if ($_.Exception.Response.StatusCode -eq 404) {Write-Output '{\"_tag\":\"MessageNotFoundError\"}'};exit 1}\n",
        encoding="utf-8",
    )
    import os
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    try:
        value = run_host_operation("wake", adapter="opencode", conversation_id="ses_example", project_root=tmp_path, message_id=message)
        assert value["turn_started"] is False
        if scenario in {"idle", "busy", "worktree"}:
            assert value["result"] == "queued", value
            assert len(posts) == 1
            assert posts[0]["delivery"] == "queue"
            assert posts[0]["id"] == request_id
            assert "permissions" not in posts[0]
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
