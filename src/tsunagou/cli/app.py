from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, cast


def _restrict_file_access(path: Path) -> None:
    """Restrict a ticket file to its creator, with a real ACL on Windows.

    ``chmod 0o600`` is only meaningful on POSIX. On Windows it merely toggles the
    read-only attribute: ``st_mode`` stays ``0o666`` and the file inherits its
    parent directory ACL, so a ticket written next to the repo ends up readable by
    ``Authenticated Users`` / ``Users``. Here we strip inherited ACEs and grant
    full control to ``CREATOR OWNER`` (``S-1-3-0``), which resolves to the account
    that just created the file (this process). Fails closed: if the ACL cannot be
    restricted, the secret-bearing file is removed rather than left world-readable.
    """
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    proc = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", "*S-1-3-0:(F)"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"failed to restrict ticket file ACL: {proc.stderr.strip()}")


def _write_ticket_private(
    installation_id: str, conversation_id: str, secret: str, ticket_file: Path | None,
    requested_role: str = "worker",
) -> Path:
    """Deliver a one-time enrollment ticket through a private file, never stdout.

    The ticket secret is a bearer credential for ``agent.enroll``; echoing it to a
    terminal leaks it into scrollback, logs and shell history. The bridge reads it
    from this file through its own private channel instead. The file is restricted
    to its creator (POSIX ``0600``, or a stripped Windows ACL) so other local
    accounts cannot read the secret.
    """
    if ticket_file is None:
        fd, temp_name = tempfile.mkstemp(prefix="tsunagou-ticket-", suffix=".json")
        os.close(fd)
        path = Path(temp_name)
    else:
        path = ticket_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({
            "installation_id": installation_id,
            "conversation_id": conversation_id,
            "secret": secret,
            "requested_role": requested_role,
        }, handle, sort_keys=True)
        handle.write("\n")
    _restrict_file_access(path)
    return path


try:
    import typer
except ImportError:  # pragma: no cover
    typer = None  # type: ignore[assignment]


if typer is not None:
    app = typer.Typer(add_completion=False, invoke_without_command=True)
    project_app = typer.Typer(help="Project control commands.")
    agent_app = typer.Typer(help="Agent enrollment and appointment.")
    decision_app = typer.Typer(help="User decision commands.")
    operation_app = typer.Typer(help="Durable operation queries.")
    checkpoint_app = typer.Typer(help="Checkpoint creation and queries.")
    daemon_app = typer.Typer(help="Local daemon lifecycle commands.")
    app.add_typer(project_app, name="project")
    app.add_typer(agent_app, name="agent")
    app.add_typer(decision_app, name="decision")
    app.add_typer(operation_app, name="operation")
    app.add_typer(checkpoint_app, name="checkpoint")
    app.add_typer(daemon_app, name="daemon")

    @app.callback()
    def callback(
        ctx: typer.Context,
        version: bool = typer.Option(False, "--version", is_eager=True),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        ctx.ensure_object(dict)
        ctx.obj["json"] = json_output
        if version:
            print("0.1.0")
            raise typer.Exit()
        if ctx.invoked_subcommand is None:
            print("Tsunagou 0.1.0 — local coordination runtime")

    @app.command("doctor")
    def doctor(ctx: typer.Context) -> None:
        try:
            result = _daemon_request("GET", "/api/v1/health")
            result["daemon"] = "reachable"
            card = _daemon_request("GET", "/.well-known/agent-card.json")
            capabilities = card.get("capabilities", {})
            result["a2a"] = {
                "status": "reachable",
                "protocol_version": card.get("protocolVersion"),
                "streaming": capabilities.get("streaming"),
                "push_notifications": capabilities.get("pushNotifications"),
                "wake": card.get("x-tsunagou", {}).get("wake"),
            }
        except RuntimeError as exc:
            print(json.dumps({"status": "unavailable", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(5) from exc
        print(json.dumps(result, sort_keys=True) if ctx.obj.get("json") else "Tsunagou doctor: ok")

    @project_app.command("init")
    def project_init(
        coordination_root: Path = typer.Option(..., "--coordination-root"),  # noqa: B008
        name: str = typer.Option("Tsunagou project", "--name"),
        objective: str = typer.Option("Coordinate local agents", "--objective"),
    ) -> None:
        from tsunagou.modules.projects import ProjectRegistry

        registry = ProjectRegistry.initialize(coordination_root, name=name, objective=objective)
        assert registry.project is not None
        print(json.dumps({"project_id": registry.project.project_id, "status": "active"}, sort_keys=True))

    @project_app.command("bootstrap")
    def project_bootstrap(
        ctx: typer.Context,
        coordination_root: Path = typer.Option(..., "--coordination-root"),  # noqa: B008
        source_root: Path | None = typer.Option(None, "--source-root"),  # noqa: B008
        source_ref: str | None = typer.Option(None, "--source-ref"),
        hosts: list[str] = typer.Option([], "--host"),  # noqa: B008
        refresh: bool = typer.Option(False, "--refresh"),
        force_managed: bool = typer.Option(False, "--force-managed"),
    ) -> None:
        """Materialize non-secret Tsunagou rules in a coordination project."""
        from tsunagou.application.project_integration import ProjectIntegration, ProjectIntegrationError

        try:
            result = ProjectIntegration(coordination_root).bootstrap(
                source_root=source_root,
                source_ref=source_ref,
                hosts=hosts or ["generic"],
                refresh=refresh,
                force_managed=force_managed,
            )
        except (ProjectIntegrationError, OSError, ValueError) as exc:
            payload = {"status": "error", "error": str(exc)}
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            raise typer.Exit(1) from exc
        if ctx.obj.get("json"):
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return
        print(f"Tsunagou project bootstrap: {result['project_id']}")
        for item in result["files"]:
            print(f"{item['status']}: {item['path']}")
        print("No credentials or runtime secrets were written.")

    @project_app.command("complete")
    def project_complete(
        proposal_id: str = typer.Argument(...),
        expected_project_revision: int = typer.Option(..., "--expected-project-revision"),
        digest: str = typer.Option(..., "--digest"),
    ) -> None:
        """Confirm a main Agent's project-completion proposal as the user."""
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            result = _invoke_command(
                "project.completion.confirm",
                {
                    "proposal_id": proposal_id,
                    "expected_project_revision": expected_project_revision,
                    "expected_revisions": {"decision": expected_project_revision},
                    "proposal_digest": digest,
                },
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    def _coordination_state_dir(coordination_root: Path) -> Path:
        return coordination_root.expanduser().resolve() / ".tsunagou" / "local"

    def _project_root() -> Path:
        configured = os.environ.get("TSUNAGOU_PROJECT_ROOT")
        if configured:
            return Path(configured).expanduser().resolve()
        return Path.cwd().resolve()

    def _state_dir_from_environment() -> Path | None:
        value = os.environ.get("TSUNAGOU_STATE_DIR")
        if value:
            return Path(value)
        root = os.environ.get("TSUNAGOU_PROJECT_ROOT")
        if root:
            return _coordination_state_dir(Path(root))
        candidate = _coordination_state_dir(Path.cwd())
        if candidate.is_dir():
            return candidate
        return None

    def _control_token() -> str | None:
        value = os.environ.get("TSUNAGOU_CONTROL_TOKEN")
        if value:
            return value
        state_dir = _state_dir_from_environment()
        if state_dir is None:
            return None
        try:
            value = (state_dir / "control.token").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None

    def _endpoint_manifest(coordination_root: Path) -> Path:
        return _coordination_state_dir(coordination_root) / "endpoint.json"

    def _choose_port(host: str) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])

    def _wait_for_daemon(url: str, process: subprocess.Popen[bytes], timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        request = urllib.request.Request(url.rstrip("/") + "/api/v1/health", method="GET")
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("daemon_exited_during_start")
            try:
                with urllib.request.urlopen(request, timeout=0.5) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.1)
        raise RuntimeError("daemon_start_timeout")

    @daemon_app.command("start")
    def daemon_start(
        coordination_root: Path = typer.Option(Path("."), "--coordination-root"),  # noqa: B008
        host: str = typer.Option("127.0.0.1", "--host"),
        port: int = typer.Option(0, "--port", min=0, max=65535),
        name: str = typer.Option("Tsunagou project", "--name"),
        objective: str = typer.Option("Coordinate local agents", "--objective"),
    ) -> None:
        from tsunagou.modules.projects import ProjectRegistry

        root = coordination_root.expanduser().resolve()
        try:
            registry = ProjectRegistry.initialize(root, name=name, objective=objective)
        except (OSError, RuntimeError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        assert registry.project is not None
        state_dir = _coordination_state_dir(root)
        state_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = state_dir / "endpoint.json"
        if manifest_path.is_file():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                existing_url = existing.get("url")
                if isinstance(existing_url, str):
                    with urllib.request.urlopen(existing_url.rstrip("/") + "/api/v1/health", timeout=1):
                        print(json.dumps({"status": "already_running", **existing}, sort_keys=True))
                        return
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
        token_path = state_dir / "control.token"
        if token_path.is_file():
            token = token_path.read_text(encoding="utf-8").strip()
        else:
            token = secrets.token_urlsafe(32)
            token_path.write_text(token + "\n", encoding="utf-8", newline="\n")
            _restrict_file_access(token_path)
        selected_port = port or _choose_port(host)
        url = f"http://{host}:{selected_port}"
        log_path = state_dir / "daemon.log"
        child_env = os.environ.copy()
        child_env.update({
            "TSUNAGOU_PROJECT_ROOT": str(root),
            "TSUNAGOU_PROJECT_ID": registry.project.project_id,
            "TSUNAGOU_STATE_DIR": str(state_dir),
            "TSUNAGOU_CONTROL_TOKEN": token,
            "PYTHONPATH": os.pathsep.join(
                [str(Path(__file__).resolve().parents[2]), child_env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep),
        })
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with open(log_path, "ab") as log_handle:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "tsunagou.bootstrap.container:build_application",
                 "--factory", "--host", host, "--port", str(selected_port)],
                cwd=str(root), env=child_env, stdout=log_handle, stderr=log_handle,
                creationflags=flags,
            )
        try:
            _wait_for_daemon(url, process)
        except RuntimeError as exc:
            if process.poll() is None:
                process.terminate()
            print(json.dumps({"status": "error", "error": str(exc), "log": str(log_path)}, sort_keys=True))
            raise typer.Exit(1) from exc
        manifest = {
            "url": url, "pid": process.pid, "project_id": registry.project.project_id,
            "state_dir": str(state_dir), "started_at": int(time.time()),
        }
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({"status": "started", **manifest}, sort_keys=True))

    @daemon_app.command("status")
    def daemon_status(
        coordination_root: Path = typer.Option(Path("."), "--coordination-root"),  # noqa: B008
    ) -> None:
        path = _endpoint_manifest(coordination_root)
        if not path.is_file():
            print(json.dumps({"status": "stopped", "manifest": str(path)}, sort_keys=True))
            raise typer.Exit(3)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            with urllib.request.urlopen(manifest["url"].rstrip("/") + "/api/v1/health", timeout=2) as response:
                running = response.status == 200
        except (OSError, urllib.error.URLError, KeyError, json.JSONDecodeError):
            running = False
        print(json.dumps({**manifest, "status": "running" if running else "stopped"}, sort_keys=True))
        if not running:
            raise typer.Exit(3)

    @daemon_app.command("stop")
    def daemon_stop(
        coordination_root: Path = typer.Option(Path("."), "--coordination-root"),  # noqa: B008
    ) -> None:
        path = _endpoint_manifest(coordination_root)
        if not path.is_file():
            print(json.dumps({"status": "already_stopped"}, sort_keys=True))
            return
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            pid = int(manifest["pid"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "error", "error": "invalid_endpoint_manifest"}, sort_keys=True))
            raise typer.Exit(1) from exc
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
            else:
                os.kill(pid, 15)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        print(json.dumps({"status": "stopped", "pid": pid}, sort_keys=True))

    def _daemon_url() -> str:
        value = os.environ.get("TSUNAGOU_DAEMON_URL")
        if value:
            return value.rstrip("/")
        state_dir = os.environ.get("TSUNAGOU_STATE_DIR")
        if not state_dir:
            project_root = os.environ.get("TSUNAGOU_PROJECT_ROOT")
            if project_root:
                state_dir = str(_coordination_state_dir(Path(project_root)))
        if state_dir:
            manifest = Path(state_dir) / "endpoint.json"
            if manifest.is_file():
                try:
                    value = json.loads(manifest.read_text(encoding="utf-8")).get("url")
                    if isinstance(value, str) and value:
                        return value.rstrip("/")
                except (OSError, json.JSONDecodeError):
                    pass
        raise RuntimeError("daemon_endpoint_not_configured")

    def _daemon_request(
        method: str, path: str, body: dict[str, Any] | None = None,
        *, authorization: str | None = None, session_id: str | None = None,
        connection_epoch: int | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if authorization:
            headers["Authorization"] = authorization
        if session_id:
            headers["Tsunagou-Session-Id"] = session_id
        if connection_epoch is not None:
            headers["Tsunagou-Connection-Epoch"] = str(connection_epoch)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(_daemon_url() + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = json.load(response)
                return cast(dict[str, Any], raw.get("result", raw))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("detail", {})
            except (OSError, json.JSONDecodeError):
                detail = {}
            code = detail.get("code", f"http_{exc.code}") if isinstance(detail, dict) else f"http_{exc.code}"
            raise RuntimeError(str(code)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("daemon_unreachable") from exc

    def _invoke_command(
        command_kind: str, payload: dict[str, Any], *, authorization: str,
    ) -> dict[str, Any]:
        from importlib.resources import files
        registry = json.loads(
            files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8")
        )
        return _daemon_request(
            "POST", f"/api/v1/commands/{command_kind}",
            {
                "command_id": __import__("uuid").uuid4().hex,
                "protocol_version": registry["protocol_version"],
                "schema_bundle_digest": registry["schema_bundle_digest"],
                "payload": payload,
            },
            authorization=authorization,
        )

    def _write_bridge_config(
        *, adapter: str, mode: str, installation_id: str, output_dir: Path,
        ticket_path: Path,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        session_path = output_dir / "bridge-session.json"
        file_component = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{adapter}-{installation_id}").strip(".")
        bridge_config_path = output_dir / f"{file_component or 'bridge'}.json"
        bridge_entry = Path(__file__).resolve().parents[3] / "packages" / "bridge-server" / "dist" / "server.js"
        bridge_config_path.write_text(json.dumps({
            "adapter": adapter,
            "mode": mode,
            "command": "node",
            "args": [str(bridge_entry) if bridge_entry.is_file() else "<tsunagou-bridge-server>/dist/server.js"],
            "env": {
                "TSUNAGOU_HTTP_URL": _daemon_url(),
                "TSUNAGOU_DAEMON_STATE_DIR": str(_state_dir_from_environment() or ""),
                "TSUNAGOU_TICKET_FILE": str(ticket_path),
                "TSUNAGOU_SESSION_FILE": str(session_path),
                "TSUNAGOU_PROJECT_ROOT": str(_project_root()),
                "TSUNAGOU_STATE_DIR": str(output_dir),
            },
            "secret_fields": [],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return bridge_config_path

    def _register_codex_mcp(*, profile: str, bridge_config_path: Path) -> str:
        codex = shutil.which("codex")
        if codex is None:
            return "codex_not_found"
        config = json.loads(bridge_config_path.read_text(encoding="utf-8"))
        safe_profile = re.sub(r"[^A-Za-z0-9_-]+", "-", profile).strip("-") or "session"
        project_root = str(config.get("env", {}).get("TSUNAGOU_PROJECT_ROOT", ""))
        project_tag = hashlib.sha256(project_root.encode("utf-8")).hexdigest()[:8]
        name = f"tsunagou-{safe_profile}-{project_tag}"
        # This name is generated by Tsunagou, so replacing an earlier entry is
        # safe and makes re-enrollment/recovery idempotent.
        subprocess.run([codex, "mcp", "remove", name], capture_output=True, text=True, check=False)
        command = [codex, "mcp", "add", name]
        for key, value in sorted(config["env"].items()):
            if value:
                command.extend(["--env", f"{key}={value}"])
        command.extend(["--", config["command"], *config["args"]])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return "codex_registration_failed"
        return f"registered:{name}"

    def _profile_identity(output_dir: Path, adapter: str, profile: str) -> tuple[str, str]:
        """Return a stable local fallback identity when the host hides its ID.

        The native host ID wins when the adapter exposes it. Otherwise the
        profile file gives one conversation a stable binding while keeping
        separately named subagent profiles isolated.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        identity_path = output_dir / "host-identity.json"
        configured = os.environ.get("TSUNAGOU_HOST_CONVERSATION_ID")
        if configured:
            conversation_id = configured
        elif identity_path.is_file():
            try:
                stored = json.loads(identity_path.read_text(encoding="utf-8"))
                conversation_id = stored.get("conversation_id", "")
            except (OSError, json.JSONDecodeError):
                conversation_id = ""
        else:
            conversation_id = ""
        if not isinstance(conversation_id, str) or not conversation_id:
            conversation_id = f"tsunagou:{adapter}:{profile}:{uuid.uuid4()}"
        installation_id = os.environ.get("TSUNAGOU_INSTALLATION_ID") or f"{adapter}:{profile}"
        identity_path.write_text(json.dumps({
            "adapter": adapter, "profile": profile,
            "installation_id": installation_id, "conversation_id": conversation_id,
        }, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
        return installation_id, conversation_id

    @agent_app.command("connect")
    def agent_connect(
        adapter: str = typer.Option(..., "--adapter"),
        role: str = typer.Option("worker", "--role"),
        profile: str = typer.Option("current", "--profile"),
        mode: str = typer.Option("attach", "--mode"),
        output_dir: Path | None = typer.Option(None, "--output-dir"),  # noqa: B008
        register_host: bool = typer.Option(True, "--register-host/--no-register-host"),
    ) -> None:
        """Prepare one host conversation in one user-control action.

        The daemon still creates the Agent/session/token. ``--role main`` is
        an explicit user request carried by the one-time ticket; an Agent
        cannot invoke this command through its bridge.
        """
        if mode not in {"attach", "launch"}:
            raise typer.BadParameter("mode must be attach or launch")
        if role not in {"worker", "main"}:
            raise typer.BadParameter("role must be worker or main")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", adapter):
            raise typer.BadParameter("adapter must contain only letters, digits, '_' or '-'")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
            raise typer.BadParameter("profile must contain only letters, digits, '_' or '-'")
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(1)
        root = _project_root()
        destination = (output_dir or (root / ".tsunagou" / "bridges" / f"{adapter}-{profile}")).expanduser().resolve()
        installation_id, conversation_id = _profile_identity(destination, adapter, profile)
        ticket_file = destination / "ticket.json"
        result = _invoke_command(
            "agent.ticket.create.user",
            {
                "kind": role, "role": role,
                "installation_id": installation_id,
                "conversation_evidence": {"conversation_id": conversation_id},
            },
            authorization=f"Bearer {token}",
        )
        ticket_path = _write_ticket_private(
            installation_id, conversation_id, result["secret"], ticket_file, role,
        )
        bridge_config_path = _write_bridge_config(
            adapter=adapter, mode=mode, installation_id=installation_id,
            output_dir=destination, ticket_path=ticket_path,
        )
        registration = "not_requested"
        if register_host and adapter == "codex":
            registration = _register_codex_mcp(profile=profile, bridge_config_path=bridge_config_path)
        print(json.dumps({
            "adapter": adapter,
            "mode": mode,
            "status": "ticket_issued",
            "requested_role": role,
            "profile": profile,
            "installation_id": installation_id,
            "bridge_config": str(bridge_config_path),
            "host_registration": registration,
            "next": "restart_or_reload_host_then_call_context__project_read",
        }, sort_keys=True))

    @agent_app.command("enroll")
    def agent_enroll(
        adapter: str = typer.Option(..., "--adapter"),
        mode: str = typer.Option("attach", "--mode"),
        installation_id: str | None = typer.Option(None, "--installation-id"),
        conversation_id: str | None = typer.Option(None, "--conversation-id"),
        ticket_file: Path | None = typer.Option(None, "--ticket-file"),  # noqa: B008
        output_dir: Path | None = typer.Option(None, "--output-dir"),  # noqa: B008
    ) -> None:
        if mode not in {"attach", "launch"}:
            raise typer.BadParameter("mode must be attach or launch")
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(1)
        if not installation_id or not conversation_id:
            print(json.dumps({
                "adapter": adapter, "mode": mode, "status": "ticket_required",
                "reason": "target_conversation_identity_required",
            }, sort_keys=True))
            raise typer.Exit(0)
        if output_dir is not None and ticket_file is None:
            output_dir = output_dir.expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            ticket_file = output_dir / "ticket.json"
        result = _invoke_command(
            "agent.ticket.create.user",
            {"kind": "worker", "installation_id": installation_id,
             "conversation_evidence": {"conversation_id": conversation_id}},
            authorization=f"Bearer {token}",
        )
        secret = result["secret"]
        path = _write_ticket_private(installation_id, conversation_id, secret, ticket_file)
        bridge_config_path = None
        if output_dir is not None:
            output_dir = output_dir.expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            session_path = output_dir / "bridge-session.json"
            bridge_config_path = output_dir / f"{adapter}-{installation_id}.json"
            bridge_entry = Path(__file__).resolve().parents[3] / "packages" / "bridge-server" / "dist" / "server.js"
            bridge_config_path.write_text(json.dumps({
                "adapter": adapter,
                "mode": mode,
                "command": "node",
                "args": [str(bridge_entry) if bridge_entry.is_file() else "<tsunagou-bridge-server>/dist/server.js"],
                "env": {
                    "TSUNAGOU_HTTP_URL": _daemon_url(),
                    "TSUNAGOU_DAEMON_STATE_DIR": str(_state_dir_from_environment() or ""),
                    "TSUNAGOU_TICKET_FILE": str(path),
                    "TSUNAGOU_SESSION_FILE": str(session_path),
                    "TSUNAGOU_PROJECT_ROOT": os.environ.get("TSUNAGOU_PROJECT_ROOT", ""),
                    "TSUNAGOU_STATE_DIR": str(output_dir),
                },
                "secret_fields": [],
            }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({
            "adapter": adapter, "mode": mode, "status": "ticket_issued",
            "installation_id": installation_id, "conversation_id": conversation_id,
            "ticket_file": str(path),
            **({"bridge_config": str(bridge_config_path)} if bridge_config_path else {}),
        }, sort_keys=True))

    @agent_app.command("appoint")
    def agent_appoint(agent_id: str = typer.Argument(...)) -> None:
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(1)
        result = _invoke_command(
            "authority.appoint",
            {"agent_id": agent_id}, authorization=f"Bearer {token}",
        )
        print(json.dumps({
            "agent_id": agent_id, "status": "appointed", **result,
        }, sort_keys=True))

    @decision_app.command("list")
    def decision_list() -> None:
        try:
            result = _daemon_request("GET", "/api/v1/decisions")
        except RuntimeError as exc:
            print(json.dumps({"status": "unavailable", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(5) from exc
        print(json.dumps(result, sort_keys=True))

    @decision_app.command("resolve")
    def decision_resolve(
        decision_id: str,
        choice: str = typer.Option(..., "--choice"),
        expected_revision: int = typer.Option(..., "--expected-revision"),
        digest: str = typer.Option(..., "--digest"),
        reason: str | None = typer.Option(None, "--reason"),
    ) -> None:
        token = _control_token()
        if not token:
            raise typer.Exit(5)
        try:
            result = _invoke_command(
                "user_decision.resolve",
                {
                    "decision_id": decision_id, "choice": choice,
                    "expected_revisions": {"decision": expected_revision},
                    "proposal_digest": digest, "reason": reason or "",
                },
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    @operation_app.command("show")
    def operation_show(operation_id: str) -> None:
        try:
            result = _daemon_request("GET", f"/api/v1/operations/{operation_id}")
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    @checkpoint_app.command("create")
    def checkpoint_create() -> None:
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            result = _invoke_command("checkpoint.create.user", {}, authorization=f"Bearer {token}")
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    @checkpoint_app.command("retry")
    def checkpoint_retry() -> None:
        """Retry checkpoint materialization after a recorded failed operation."""
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            result = _invoke_command(
                "checkpoint.create.user", {"reason": "user_retry_after_failure"},
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    @checkpoint_app.command("list")
    def checkpoint_list() -> None:
        try:
            result = _daemon_request("GET", "/api/v1/checkpoints")
        except RuntimeError as exc:
            print(json.dumps({"status": "unavailable", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(5) from exc
        print(json.dumps(result, sort_keys=True))

    @app.command("recover")
    def recover() -> None:
        try:
            result = _daemon_request("GET", "/api/v1/recovery")
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(5) from exc
        print(json.dumps(result, sort_keys=True))

    main = app
else:
    def main() -> None:
        print("Tsunagou 0.1.0 — local coordination runtime")
