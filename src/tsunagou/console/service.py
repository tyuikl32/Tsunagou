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

from tsunagou.console.config import ConsoleConfig
from tsunagou.shared_kernel.time import format_timestamp, now_ms

CONSOLE_MANIFEST = ".tsunagou-console.local.json"
STATUS_TIMEOUT = 1.0


def manifest_path(config: ConsoleConfig) -> Path:
    """Beside the config file when there is one, in the working directory otherwise."""

    base = config.path.parent if config.path is not None else Path.cwd()
    return base / CONSOLE_MANIFEST


def choose_port(host: str, requested: int) -> int:
    """Honour an explicit port; pick a free one when the config asks for ``0``."""

    if requested:
        return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def serve(
    config: ConsoleConfig, *, on_ready: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the console until interrupted, announcing where it listens."""

    import uvicorn

    from tsunagou.console.app import create_console_app

    port = choose_port(config.host, config.port)
    url = f"http://{config.host}:{port}"
    manifest = manifest_path(config)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "url": url, "host": config.host, "port": port, "pid": os.getpid(),
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
