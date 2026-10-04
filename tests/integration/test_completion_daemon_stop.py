"""Completion durability, response delivery and the owning process lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from fastapi import Response

from tsunagou.api.app import CommandRequest
from tsunagou.bootstrap.container import build_application
from tsunagou.bootstrap.daemon import ProjectDaemon
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES
from tsunagou.shared_kernel.ids import new_id

DIGEST = json.loads(files("tsunagou.protocol_data").joinpath("registry/commands.json").read_text(encoding="utf-8"))["schema_bundle_digest"]


def _config(root: Path) -> dict[str, str]:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    ProjectRegistry.initialize(root, name="completion", objective="test completion shutdown")
    state = root / ".tsunagou/local"
    state.mkdir(parents=True, exist_ok=True)
    (state / "control.token").write_text("control", encoding="utf-8")
    return {
        "TSUNAGOU_PROJECT_ROOT": str(root),
        "TSUNAGOU_STATE_DIR": str(state),
        "TSUNAGOU_CONTROL_TOKEN": "control",
        "TSUNAGOU_DAEMON_URL": "http://127.0.0.1:1",
        "TSUNAGOU_HOST_WAKE": "disabled",
    }


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {"command_id": new_id(), "protocol_version": "1.0", "schema_bundle_digest": DIGEST, "payload": payload}


def _call(app: Any, kind: str, payload: dict[str, Any], receipt: dict[str, Any] | None = None, secret: str = "control") -> dict[str, Any]:
    endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/v1/commands/{command_kind}")
    return endpoint(
        kind,
        CommandRequest(**_envelope(payload)),
        Response(),
        f"Bearer {secret}",
        receipt.get("session_id") if receipt else None,
        receipt.get("connection_epoch") if receipt else None,
    )["result"]


def _proposal(app: Any) -> dict[str, Any]:
    identity = {"installation_id": "completion-test", "conversation_evidence": {"conversation_id": "completion-test"}}
    ticket = _call(app, "agent.ticket.create.user", identity)
    main = _call(
        app,
        "agent.enroll",
        {
            **identity,
            "probe_payload": {
                "baseline": {name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]} for name in ADMISSION_CAPABILITIES}
            },
        },
        secret=ticket["secret"],
    )
    _call(app, "authority.appoint", {"agent_id": main["agent_id"]})
    proposed = _call(
        app,
        "project.completion.propose.main",
        {
            "expected_project_revision": 1,
            "objective_ref": "project",
            "outstanding_summary": "none",
            "evidence_refs": [],
        },
        main,
        main["secret_token"],
    )
    return _envelope(
        {
            "proposal_id": proposed["proposal_id"],
            "proposal_digest": proposed["proposal_digest"],
            "expected_project_revision": 1,
            "expected_revisions": {"decision": proposed["revision"]},
        }
    )


async def _request(
    daemon: ProjectDaemon, envelope: dict[str, Any], *, secret: str = "control", final_send: Any = None
) -> tuple[int, dict[str, Any]]:
    messages = []
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": json.dumps(envelope).encode(), "more_body": False}
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and not message.get("more_body", False) and final_send:
            await final_send()
        messages.append(message)

    project_id = next(iter(daemon.apps))
    await daemon(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/commands/project.completion.confirm",
            "query_string": b"",
            "root_path": "",
            "server": ("127.0.0.1", 1),
            "client": ("127.0.0.1", 2),
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", f"Bearer {secret}".encode()),
                (b"tsunagou-project-id", project_id.encode()),
            ],
        },
        receive,
        send,
    )
    return messages[0]["status"], json.loads(b"".join(m.get("body", b"") for m in messages))


async def _checked(daemon: ProjectDaemon) -> None:
    daemon.schedule_completion_check()
    if daemon._completion_check is not None:
        await daemon._completion_check


@pytest.mark.asyncio
async def test_response_barrier_replay_and_registration_fence(tmp_path: Path) -> None:
    exits = []
    daemon = ProjectDaemon(_config(tmp_path / "first"), request_exit=lambda: exits.append(True))
    async with daemon.control.router.lifespan_context(daemon.control):
        app = next(iter(daemon.apps.values()))
        envelope = _proposal(app)
        blocked, release = asyncio.Event(), asyncio.Event()

        async def delay() -> None:
            blocked.set()
            await release.wait()

        request = asyncio.create_task(_request(daemon, envelope, final_send=delay))
        await asyncio.wait_for(blocked.wait(), 10)
        await _checked(daemon)
        assert not exits
        # Hold registration's lock while the sent response becomes eligible.
        async with daemon.lock:
            release.set()
            status, body = await request
            assert status == 200 and body["result"]["checkpoint_status"] == "sealed"
            assert not exits
        await _checked(daemon)
        assert exits == [True]
        await _request(daemon, envelope)
        await _checked(daemon)
        assert exits == [True]
        async with daemon.lock:
            with pytest.raises(RuntimeError, match="daemon_closing"):
                await daemon.add_project(str(tmp_path / "second"), str(tmp_path / "second/.tsunagou/local"))


@pytest.mark.asyncio
async def test_shared_daemon_registration_wins_while_response_pending(tmp_path: Path) -> None:
    exits = []
    daemon = ProjectDaemon(_config(tmp_path / "first"), request_exit=lambda: exits.append(True))
    other = _config(tmp_path / "second")
    async with daemon.control.router.lifespan_context(daemon.control):
        envelope = _proposal(next(iter(daemon.apps.values())))

        async def attach() -> None:
            async with daemon.lock:
                await daemon.add_project(other["TSUNAGOU_PROJECT_ROOT"], other["TSUNAGOU_STATE_DIR"])

        assert (await _request(daemon, envelope, final_send=attach))[0] == 200
        await _checked(daemon)
        assert len(daemon.apps) == 2 and not exits and not daemon.closing


@pytest.mark.asyncio
async def test_failed_checkpoint_only_matching_retry_stops_daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exits = []
    daemon = ProjectDaemon(_config(tmp_path), request_exit=lambda: exits.append(True))
    async with daemon.control.router.lifespan_context(daemon.control):
        app = next(iter(daemon.apps.values()))
        app.state.maintenance.stop()  # Drive deferred work deterministically below.
        envelope = _proposal(app)
        materialize = app.state.checkpoint_store.materialize

        def fail(**_: Any) -> Any:
            raise OSError("disk full")

        monkeypatch.setattr(app.state.checkpoint_store, "materialize", fail)
        _, body = await _request(daemon, envelope)
        operation = body["result"]["operation_id"]
        assert body["result"]["checkpoint_status"] == "failed"
        await _checked(daemon)
        assert not exits
        monkeypatch.setattr(app.state.checkpoint_store, "materialize", materialize)
        # A successful unrelated checkpoint must not qualify the failed completion.
        _call(app, "checkpoint.create.user", {"reason": "unrelated"})
        await _checked(daemon)
        assert not exits
        # Queue the same operation without inline execution, then let existing
        # maintenance finish it and signal the owning event loop.
        with app.state.project_database.transaction("retry") as uow:
            app.state.checkpoint_worker.retry(uow, actor="user_control", operation_id=operation)
        await _checked(daemon)
        assert not exits
        await asyncio.to_thread(app.state.maintenance.run_once)
        await _checked(daemon)
        assert exits == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent_replay", [False, True])
async def test_lost_response_concurrent_replay_and_restart(tmp_path: Path, concurrent_replay: bool) -> None:
    exits = []
    config = _config(tmp_path)
    daemon = ProjectDaemon(config, request_exit=lambda: exits.append(True))
    async with daemon.control.router.lifespan_context(daemon.control):
        envelope = _proposal(next(iter(daemon.apps.values())))

        async def lost() -> None:
            # The replay completes before the original response fails.
            if concurrent_replay:
                assert (await _request(daemon, envelope))[0] == 200
            await _checked(daemon)
            assert not exits
            raise OSError("client disconnected")

        with pytest.raises(OSError, match="client disconnected"):
            await _request(daemon, envelope, final_send=lost)
        await _checked(daemon)
        if not concurrent_replay:
            assert not exits
            assert (await _request(daemon, envelope))[0] == 200
            await _checked(daemon)
        assert exits == [True]
    restarted = ProjectDaemon(config, request_exit=lambda: exits.append(True))
    async with restarted.control.router.lifespan_context(restarted.control):
        await _checked(restarted)
        assert (await _request(restarted, envelope))[0] == 200
        await _checked(restarted)
        assert exits == [True] and not restarted.closing


@pytest.mark.asyncio
async def test_denied_and_stale_confirmation_do_not_arm_shutdown(tmp_path: Path) -> None:
    exits = []
    daemon = ProjectDaemon(_config(tmp_path), request_exit=lambda: exits.append(True))
    async with daemon.control.router.lifespan_context(daemon.control):
        envelope = _proposal(next(iter(daemon.apps.values())))
        assert (await _request(daemon, envelope, secret="wrong"))[0] == 401
        envelope["payload"]["expected_project_revision"] = 500
        assert (await _request(daemon, envelope))[0] >= 400
        envelope["payload"]["expected_project_revision"] = 1
        envelope["payload"]["proposal_digest"] = "sha256:" + "0" * 64
        assert (await _request(daemon, envelope))[0] >= 400
        await _checked(daemon)
        assert not exits and not daemon.completions


def test_real_process_completion_returns_response_exits_and_releases_port(tmp_path: Path) -> None:
    config = _config(tmp_path)
    app = build_application(config)
    envelope = _proposal(app)
    app.state.project_database.release_process_lock()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    config["TSUNAGOU_DAEMON_URL"] = url
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TSUNAGOU_", "CODEX_"))}
    env.update(config)
    with (tmp_path / "daemon.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "tsunagou.bootstrap.daemon", "--host", "127.0.0.1", "--port", str(port)],
            env=env,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    with urllib.request.urlopen(url + "/api/v1/health", timeout=1) as response:
                        assert json.load(response)["runtime"]["pid"] > 0
                    break
                except (OSError, urllib.error.URLError):
                    assert process.poll() is None and time.monotonic() < deadline
                    time.sleep(0.05)
            request = urllib.request.Request(
                url + "/api/v1/commands/project.completion.confirm",
                data=json.dumps(envelope).encode(),
                headers={"Authorization": "Bearer control", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.load(response)["result"]
                assert result["status"] == "completed" and result["checkpoint_status"] == "sealed"
            assert process.wait(timeout=15) == 0
            with socket.socket() as released:
                released.bind(("127.0.0.1", port))
                released.listen()
            # A new container can acquire the same project's process lock.
            rebuilt = build_application(config)
            rebuilt.state.project_database.release_process_lock()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
