"""Exercise the current assembled server over loopback, including a process restart.

This is a backend audit, not an agent host certification or the future MVP suite.
Fixtures are local to disposable projects. No credential is included in the report.
Exit 0: no audited defect; 1: defects found; 2: the audit itself could not finish.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tsunagou.application.handlers import build_handlers
from tsunagou.modules.authority import AuthorityService
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES
from tsunagou.shared_kernel.ids import new_id

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Audit:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.registry = json.loads((ROOT / "protocol/registry/commands.json").read_text(encoding="utf-8"))
        self.control = secrets.token_urlsafe(32)
        self.port = free_port()
        self.process: subprocess.Popen[bytes] | None = None
        self.checks: list[dict[str, Any]] = []
        self.env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "TSUNAGOU_CONTROL_TOKEN": self.control,
            "TSUNAGOU_STATE_DIR": str(directory / ".tsunagou/local"),
            "TSUNAGOU_PROJECT_ROOT": str(directory),
            "TSUNAGOU_DAEMON_URL": f"http://127.0.0.1:{self.port}",
        }
        self.env.pop("TSUNAGOU_PROJECT_ID", None)

    def record(self, name: str, passed: bool, **observed: Any) -> None:
        self.checks.append({"check": name, "passed": passed, "observed": observed})

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "tsunagou", *args], cwd=ROOT, env=self.env,
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )

    def start(self) -> None:
        with (self.directory / "server.log").open("ab") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "tsunagou.bootstrap.container:build_application",
                 "--factory", "--host", "127.0.0.1", "--port", str(self.port), "--no-access-log"],
                cwd=ROOT, env=self.env, stdout=log, stderr=log,
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("server_exited_before_health")
            try:
                if self.http("GET", "/api/v1/health")[0] == 200:
                    return
            except (URLError, TimeoutError):
                pass
            time.sleep(0.1)
        raise RuntimeError("server_health_timeout")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)

    def http(
        self, method: str, path: str, body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request = Request(
            f"http://127.0.0.1:{self.port}{path}", method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"error": "non_json_response"}

    def command(
        self, kind: str, payload: dict[str, Any], actor: dict[str, Any] | str,
        *, command_id: str | None = None, version: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        if isinstance(actor, str):
            headers = {"Authorization": f"Bearer {actor}"}
        else:
            headers = {
                "Authorization": f"Bearer {actor['secret_token']}",
                "Tsunagou-Session-Id": actor["session_id"],
                "Tsunagou-Connection-Epoch": str(actor["connection_epoch"]),
            }
        status, body = self.http("POST", f"/api/v1/commands/{kind}", {
            "command_id": command_id or new_id(),
            "protocol_version": version or self.registry["protocol_version"],
            "schema_bundle_digest": self.registry["schema_bundle_digest"],
            "payload": payload,
        }, headers)
        return status, body.get("result", body)

    def a2a(
        self, path: str, body: dict[str, Any] | None = None,
        actor: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers: dict[str, str] = {}
        if actor is not None:
            headers = {
                "Authorization": f"Bearer {actor['secret_token']}",
                "Tsunagou-Session-Id": actor["session_id"],
                "Tsunagou-Connection-Epoch": str(actor["connection_epoch"]),
            }
        return self.http("POST", path, body, headers)

    def ok(self, kind: str, payload: dict[str, Any], actor: dict[str, Any] | str) -> dict[str, Any]:
        status, result = self.command(kind, payload, actor)
        if status != 200:
            raise RuntimeError(f"fixture_command_failed:{kind}:{status}")
        return result

    def enroll(self, name: str) -> dict[str, Any]:
        identity = {"installation_id": "backend-audit", "conversation_evidence": {"conversation_id": name}}
        ticket = self.ok("agent.ticket.create.user", identity, self.control)
        # This fixture only permits backend paths to execute. It makes no claim
        # about any IDE and is never written to host evidence or release records.
        baseline = {"baseline": {
            key: {"status": "supported", "evidence_refs": ["fixture:backend-audit"]}
            for key in ADMISSION_CAPABILITIES
        }}
        return self.ok("agent.enroll", {**identity, "probe_payload": baseline}, ticket["secret"])

    def run(self) -> dict[str, Any]:
        subprocess.run(["git", "init", "--quiet", str(self.directory)], check=True, capture_output=True)
        initialized = self.cli("project", "init", "--coordination-root", str(self.directory))
        if initialized.returncode:
            raise RuntimeError("project_init_failed")
        project_id = json.loads(initialized.stdout)["project_id"]
        handlers = build_handlers(authority=AuthorityService())
        policies = set(self.registry["commands"])
        coverage = {
            "registered": len(handlers), "declared": len(policies),
            "missing": sorted(policies - handlers.keys()),
        }
        offline = self.cli("decision", "resolve", "not-a-real-decision", "--choice", "approve",
                           "--expected-revision", "1", "--digest", "sha256:not-real")
        self.record("offline_decision_must_not_report_success", offline.returncode != 0,
                    exit_code=offline.returncode, reported=json.loads(offline.stdout).get("status"))
        self.start()
        self.record("health", self.http("GET", "/api/v1/health")[0] == 200)
        card_status, card = self.http("GET", "/.well-known/agent-card.json")
        self.record(
            "a2a_agent_card_truthful_capabilities",
            card_status == 200
            and card.get("protocolVersion") == "1.0"
            and card.get("capabilities", {}).get("streaming") is False
            and card.get("capabilities", {}).get("pushNotifications") is False
            and card.get("x-tsunagou", {}).get("wake") == "unsupported",
            http_status=card_status,
        )
        doctor = self.cli("--json", "doctor")
        try:
            doctor_body = json.loads(doctor.stdout)
        except json.JSONDecodeError:
            doctor_body = {}
        self.record(
            "doctor_reports_a2a_boundary",
            doctor.returncode == 0
            and doctor_body.get("a2a", {}).get("protocol_version") == "1.0"
            and doctor_body.get("a2a", {}).get("wake") == "unsupported",
            exit_code=doctor.returncode,
        )
        main, worker = self.enroll("main"), self.enroll("worker")
        self.ok("authority.appoint", {"agent_id": main["agent_id"]}, self.control)

        payload = {"title": "duplicate", "objective": "one command, one task"}
        key = new_id()
        a_status, first = self.command("task.create", payload, main, command_id=key)
        b_status, second = self.command("task.create", payload, main, command_id=key)
        self.record("task_create_idempotency", a_status == b_status == 200 and first == second,
                    statuses=[a_status, b_status], same_task=first.get("task_id") == second.get("task_id"))
        self.record("task_create_is_draft", first.get("status") == "draft", actual=first.get("status"))
        self.ok("task.ready", {"task_id": first["task_id"]}, main)
        self.ok("task.publish", {"task_id": first["task_id"]}, main)
        status, _ = self.command("task.create", {**payload, "title": "bad version"}, main, version="999")
        self.record("protocol_version_rejected", status == 400, http_status=status)
        status, _ = self.http("GET", f"/api/v1/projects/{project_id}/tasks")
        self.record("project_task_query_available", status == 200, http_status=status)

        self.ok("task.claim", {"task_id": first["task_id"]}, main)
        status, _ = self.command("task.start", {"task_id": first["task_id"]}, main)
        self.record("start_requires_preflight_and_resources", status >= 400, http_status=status)
        status, _ = self.command("task.block", {"task_id": first["task_id"], "reason": "foreign owner"}, worker)
        self.record("worker_cannot_block_main_attempt", status >= 400, http_status=status)
        status, _ = self.command("task.resume", {"task_id": first["task_id"]}, worker)
        self.record("worker_cannot_take_over_main_attempt", status >= 400, http_status=status)

        partial = self.ok("task.create", {"title": "atomicity", "objective": "reject before mutation"}, main)
        self.ok("task.ready", {"task_id": partial["task_id"]}, main)
        self.ok("task.publish", {"task_id": partial["task_id"]}, main)
        self.ok("task.claim", {"task_id": partial["task_id"]}, main)
        status, _ = self.command("task.start", {"task_id": partial["task_id"], "attempt_id": new_id()}, main)
        context = self.ok("context.project_read", {}, main)
        state = next(item["status"] for item in context["tasks"] if item["task_id"] == partial["task_id"])
        self.record("failed_start_is_atomic", status >= 400 and state == "claimed", http_status=status, task_status=state)

        status, _ = self.command("cognition.report", {"task_id": new_id(), "attempt_id": new_id()}, worker)
        self.record("report_requires_real_task_relationship", status >= 400, http_status=status)
        durable = self.ok("task.create", {"title": "restart", "objective": "survive process restart"}, main)
        self.ok("task.ready", {"task_id": durable["task_id"]}, main)
        self.ok("task.publish", {"task_id": durable["task_id"]}, main)
        self.ok("task.claim", {"task_id": durable["task_id"]}, worker)
        proposal = self.ok("contract.propose", {
            "payload": {"field": "user_id"},
            "participants_required": [{"slot": "main", "agent_id": main["agent_id"]}],
        }, main)
        message = self.ok("message.send", {
            "recipient_agent_id": worker["agent_id"], "kind": "notice",
            "subject_ref": durable["task_id"], "summary": "persist this message",
        }, main)
        a2a_body = {
            "jsonrpc": "2.0", "id": "audit-a2a-message", "method": "message/send",
            "params": {"message": {
                "messageId": "audit-a2a-message-1", "contextId": durable["task_id"],
                "role": "agent", "parts": [{"text": "A2A durable audit message."}],
                "metadata": {"tsunagou": {"kind": "request", "subject_ref": durable["task_id"]}},
            }},
        }
        a2a_path = f"/api/v1/a2a/agents/{worker['agent_id']}"
        a2a_status, a2a_first = self.a2a(a2a_path, a2a_body, main)
        _, a2a_second = self.a2a(a2a_path, a2a_body, main)
        first_message_id = a2a_first.get("result", {}).get("message", {}).get("messageId")
        second_message_id = a2a_second.get("result", {}).get("message", {}).get("messageId")
        self.record(
            "a2a_message_send_is_durable_and_idempotent",
            a2a_status == 200
            and bool(first_message_id)
            and first_message_id == second_message_id
            and a2a_first.get("result", {}).get("message", {}).get("metadata", {}).get("tsunagou", {}).get("wake") == "unsupported",
            http_status=a2a_status,
        )
        task_status, a2a_task = self.a2a(
            "/api/v1/a2a",
            {"jsonrpc": "2.0", "id": "audit-a2a-task", "method": "tasks/get",
             "params": {"id": f"tsunagou:task:{durable['task_id']}"}},
            main,
        )
        self.record(
            "a2a_task_get_maps_internal_task",
            task_status == 200
            and a2a_task.get("result", {}).get("id") == f"tsunagou:task:{durable['task_id']}"
            and a2a_task.get("result", {}).get("status", {}).get("state") == "submitted",
            http_status=task_status,
        )
        cancel_task = self.ok("task.create", {"title": "a2a cancel", "objective": "audit cancel transition"}, main)
        self.ok("task.ready", {"task_id": cancel_task["task_id"]}, main)
        self.ok("task.publish", {"task_id": cancel_task["task_id"]}, main)
        cancel_status, cancel_result = self.a2a(
            "/api/v1/a2a",
            {"jsonrpc": "2.0", "id": "audit-a2a-cancel", "method": "tasks/cancel",
             "params": {"id": f"tsunagou:task:{cancel_task['task_id']}", "reason": "audit cancellation"}},
            main,
        )
        self.record(
            "a2a_cancel_uses_main_authority",
            cancel_status == 200
            and cancel_result.get("result", {}).get("metadata", {}).get("tsunagou", {}).get("transition") == "task.cancel_request",
            http_status=cancel_status,
        )
        fail_task = self.ok("task.create", {"title": "a2a fail", "objective": "audit failure transition"}, main)
        self.ok("task.ready", {"task_id": fail_task["task_id"]}, main)
        self.ok("task.publish", {"task_id": fail_task["task_id"]}, main)
        fail_attempt = self.ok("task.claim", {"task_id": fail_task["task_id"]}, worker)
        fail_status, fail_result = self.a2a(
            "/api/v1/a2a",
            {"jsonrpc": "2.0", "id": "audit-a2a-fail", "method": "tasks/fail",
             "params": {"id": fail_task["task_id"], "attemptId": fail_attempt["attempt_id"],
                        "reason": "audit failure", "stopEvidence": {"kind": "audit"}}},
            worker,
        )
        self.record(
            "a2a_fail_uses_attempt_owner",
            fail_status == 200 and fail_result.get("result", {}).get("status", {}).get("state") == "failed",
            http_status=fail_status,
        )
        retry_task = self.ok("task.create", {"title": "a2a retry", "objective": "audit retry transition"}, main)
        self.ok("task.ready", {"task_id": retry_task["task_id"]}, main)
        self.ok("task.publish", {"task_id": retry_task["task_id"]}, main)
        retry_attempt = self.ok("task.claim", {"task_id": retry_task["task_id"]}, worker)
        self.ok(
            "task.block",
            {"task_id": retry_task["task_id"], "attempt_id": retry_attempt["attempt_id"], "reason": "audit retry"},
            worker,
        )
        retry_status, retry_result = self.a2a(
            "/api/v1/a2a",
            {"jsonrpc": "2.0", "id": "audit-a2a-retry", "method": "tasks/retry",
             "params": {"id": retry_task["task_id"], "attemptId": retry_attempt["attempt_id"],
                        "reason": "audit retry"}},
            main,
        )
        self.record(
            "a2a_retry_reuses_recovery_transition",
            retry_status == 200 and retry_result.get("result", {}).get("status", {}).get("state") == "submitted",
            http_status=retry_status,
        )
        unsupported_status, unsupported = self.a2a(
            "/api/v1/a2a",
            {"jsonrpc": "2.0", "id": "audit-a2a-unsupported", "method": "message/stream", "params": {}},
        )
        self.record(
            "a2a_rejects_unsupported_stream_without_auth",
            unsupported_status == 200
            and unsupported.get("error", {}).get("data", {}).get("code") == "a2a_method_not_supported",
            http_status=unsupported_status,
        )
        self.stop()
        self.start()
        context = self.ok("context.project_read", {}, worker)
        self.record("task_survives_restart", any(t["task_id"] == durable["task_id"] for t in context["tasks"]),
                    owned_tasks_after_restart=len(context["tasks"]))
        status, _ = self.command("contract.accept", {
            "proposal_id": proposal["proposal_id"], "participant_slot": "main",
            "proposal_digest": proposal["digest"],
        }, main)
        self.record("contract_survives_restart", status == 200, http_status=status)
        inbox = self.ok("inbox.claim", {}, worker)
        self.record("message_survives_restart", any(m["message_id"] == message["message_id"] for m in inbox["messages"]))
        self.record("project_sqlite_created", (self.directory / ".tsunagou/local/state.sqlite3").is_file())

        ticket_file = self.directory / "cli-ticket.json"
        issued = self.cli("agent", "enroll", "--adapter", "codex", "--installation-id", "cli-audit",
                          "--conversation-id", "cli-worker", "--ticket-file", str(ticket_file))
        if issued.returncode == 0 and ticket_file.is_file():
            ticket = json.loads(ticket_file.read_text(encoding="utf-8"))
            status, _ = self.command("agent.enroll", {
                "installation_id": ticket["installation_id"],
                "conversation_evidence": {"conversation_id": ticket["conversation_id"]},
            }, ticket["secret"])
            self.record("cli_ticket_visible_to_running_server", status == 200, http_status=status)
        else:
            self.record("cli_ticket_visible_to_running_server", False, cli_exit=issued.returncode)
        a2a_checks = [
            check for check in self.checks
            if check["check"].startswith("a2a_") or check["check"] == "doctor_reports_a2a_boundary"
        ]
        return {
            "audit_kind": "assembled_backend", "handler_coverage": coverage, "checks": self.checks,
            "a2a_checks": a2a_checks,
            "a2a_passed": sum(check["passed"] for check in a2a_checks),
            "a2a_failed": sum(not check["passed"] for check in a2a_checks),
            "passed": sum(check["passed"] for check in self.checks),
            "failed": sum(not check["passed"] for check in self.checks),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tsunagou-backend-audit-") as directory:
        audit = Audit(Path(directory))
        try:
            result = audit.run()
        except Exception as exc:
            result = {"audit_kind": "assembled_backend", "error_type": type(exc).__name__,
                      "checks": audit.checks, "status": "audit_incomplete"}
            exit_code = 2
        else:
            exit_code = 1 if result["failed"] else 0
        finally:
            audit.stop()
            if os.environ.get("TSUNAGOU_KEEP_AUDIT"):
                print(f"audit_temp_directory={directory}", file=sys.stderr)
    rendered = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
