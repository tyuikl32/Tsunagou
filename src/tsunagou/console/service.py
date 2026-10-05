"""Starting the console, and telling whether it is already running.

The console keeps one small local file saying where it listens, next to its
configuration. ``web start`` writes it and removes it on exit; ``web status``
reads it and then *asks* the console rather than trusting the file, because a
crashed process leaves a file behind.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tsunagou.console.config import ConsoleConfig, is_loopback_host
from tsunagou.shared_kernel.time import format_timestamp, now_ms

CONSOLE_MANIFEST = ".tsunagou-console.local.json"
STATUS_TIMEOUT = 1.0


def manifest_path(config: ConsoleConfig) -> Path:
    """Beside the config file when there is one, in the working directory otherwise."""

    base = config.path.parent if config.path is not None else Path.cwd()
    return base / CONSOLE_MANIFEST


def choose_port(host: str, requested: int, *, fallback: bool = True) -> tuple[int, bool]:
    """Listen where we were asked to, and say whether we had to move.

    Returns ``(port, moved)``. The default port is fixed on purpose (a person bookmarks
    the page), so when it is already taken we take a free one instead of refusing to
    start; that case is reported so nobody bookmarks a stale address. A port somebody
    deliberately wrote down is never moved: a tunnel or firewall rule was written
    against it, and a silent switch would look like a successful start that nobody can
    reach. The probe socket is closed before the caller binds for real — a small window
    in which somebody else could take the port, which is why the bind failure is still
    possible and still surfaces.
    """

    if requested and not fallback:
        return requested, False
    if requested:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, requested))
            except OSError:
                pass
            else:
                return requested, False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1]), bool(requested)


def serve(
    config: ConsoleConfig, *, on_ready: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the console until interrupted, announcing where it listens."""

    # 先拒绝，再去导入 uvicorn：拒绝不该依赖一个只在真要监听时才需要的东西。
    if not is_loopback_host(config.host):
        raise RuntimeError(f"console_host_must_be_loopback:{config.host}")

    import uvicorn

    from tsunagou.console.app import create_console_app

    port, moved = choose_port(config.host, config.port, fallback=not config.port_explicit)
    url = f"http://{config.host}:{port}"
    manifest = manifest_path(config)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "url": url, "host": config.host, "port": port, "pid": os.getpid(),
        "port_requested": config.port, "port_fallback": moved,
        "config": str(config.path) if config.path is not None else None,
        "started_at": format_timestamp(now_ms()),
    }
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if on_ready is not None:
        on_ready(record)
    try:
        uvicorn.run(create_console_app(config), host=config.host, port=port, log_level="info")
    finally:
        manifest.unlink(missing_ok=True)
    return {"status": "stopped", "url": url}


def stop(config: ConsoleConfig) -> dict[str, Any]:
    """Stop this machine's console, and leave the projects' daemons running.

    The manifest is what makes this safe: it carries the pid, and `status` has just asked
    that address and received an answer, so the pid belongs to the console rather than to
    something that inherited a recycled number. (The remaining window -- the console dying
    between that answer and the signal -- is small enough to accept, and the worst case is
    a failed stop rather than a wrong process killed for long.)

    Daemons are deliberately untouched: they are started detached, with
    ``CREATE_BREAKAWAY_FROM_JOB`` on Windows (see ``cli/app.py``), precisely so that
    closing the console does not take them down. A stop that killed them would be the
    opposite of what that flag is for.
    """

    current = status(config)
    manifest = manifest_path(config)
    if current["status"] != "running":
        # 过期或读不出来的清单会让人以为"还在跑"：顺手清掉，并如实说原来的状态。
        manifest.unlink(missing_ok=True)
        return {"status": "unknown" if current["status"] == "unknown" else "stopped",
                "was": current["status"], "manifest": str(manifest)}
    pid = int(current.get("pid") or 0)
    if pid <= 0:
        raise RuntimeError("console_pid_missing")
    url = str(current.get("url") or "")
    _terminate(pid)
    _wait_until_silent(url)
    manifest.unlink(missing_ok=True)
    return {"status": "stopped", "was": "running", "pid": pid, "url": url or None}


def _terminate(pid: int) -> None:
    """Ask one process to stop. Windows has no SIGTERM, so this is a terminate."""

    import signal

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        raise RuntimeError(f"console_stop_failed:{exc}") from exc


def _wait_until_silent(url: str, *, seconds: float = 5.0) -> None:
    """Wait until the console stops answering.

    Deliberately not "is that pid alive": ``os.kill(pid, 0)`` **terminates** on Windows,
    so it cannot be used as a probe there. Asking the console's own address means the same
    thing on every platform, and it is what we actually care about.
    """

    if not url:
        return
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url.rstrip("/") + "/api/v1/console/config", timeout=STATUS_TIMEOUT).close()
        except (urllib.error.URLError, OSError, ValueError):
            return
        time.sleep(0.1)
    raise RuntimeError("console_stop_timeout")


def status(config: ConsoleConfig) -> dict[str, Any]:
    """Report the running console, if any, by asking it directly."""

    manifest = manifest_path(config)
    if not manifest.is_file():
        return {"status": "stopped", "manifest": str(manifest)}
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unknown", "manifest": str(manifest)}
    url = str(record.get("url") or "")
    answer: dict[str, Any] | None = None
    if url:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/api/v1/console/config", timeout=STATUS_TIMEOUT) as response:
                answer = json.loads(response.read())
        except (urllib.error.URLError, OSError, ValueError):
            answer = None
    return {
        "status": "running" if answer else "stale",
        "url": url or None,
        "pid": record.get("pid"),
        "started_at": record.get("started_at"),
        "manifest": str(manifest),
        "console": answer,
    }
