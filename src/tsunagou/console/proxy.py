"""Forwarding a browser request to the daemon that owns the project.

The point of this module is that the control token is added here, on the server
side, and the browser never learns it. Nothing else is rewritten: status codes and
bodies travel back untouched, so the page sees exactly what the daemon said —
including the daemon's own ``{"detail": {"code": ...}}`` refusals.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.console.errors import ConsoleError

CONTROL_TOKEN_FILENAME = "control.token"
REQUEST_TIMEOUT = 15.0
FORWARDED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


@dataclass(frozen=True)
class ForwardResponse:
    status: int
    body: bytes
    content_type: str


def project_token(root: Path, endpoint: dict[str, Any] | None = None) -> str | None:
    """Read the U-principal token of a project, preferring the daemon's own state dir."""

    candidates: list[Path] = []
    state_dir = (endpoint or {}).get("state_dir")
    if isinstance(state_dir, str) and state_dir:
        candidates.append(Path(state_dir) / CONTROL_TOKEN_FILENAME)
    candidates.append(root / ".tsunagou" / "local" / CONTROL_TOKEN_FILENAME)
    for candidate in candidates:
        if candidate.is_file():
            try:
                token = candidate.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if token:
                return token
    return None


def ensure_matching_project(endpoint: dict[str, Any], project_id: str) -> None:
    """A daemon serves exactly one project; refusing a mismatch beats mixing data."""

    served = endpoint.get("project_id")
    if served and served != project_id:
        raise ConsoleError(
            "daemon_project_mismatch", status=409,
            detail={"requested_project_id": project_id, "daemon_project_id": served},
        )


def forward(
    *,
    endpoint: dict[str, Any],
    method: str,
    path: str,
    query: str = "",
    body: bytes | None = None,
    token: str | None = None,
    timeout: float = REQUEST_TIMEOUT,
) -> ForwardResponse:
    """Send one request and bring the daemon's answer back unchanged."""

    if method.upper() not in FORWARDED_METHODS:
        raise ConsoleError("method_not_allowed", status=405, detail={"method": method})
    url = str(endpoint["url"]).rstrip("/") + path + (f"?{query}" if query else "")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return ForwardResponse(
                status=response.status,
                body=response.read(),
                content_type=response.headers.get_content_type(),
            )
    except urllib.error.HTTPError as exc:
        return ForwardResponse(
            status=exc.code,
            body=exc.read(),
            content_type=exc.headers.get_content_type() if exc.headers else "application/json",
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConsoleError(
            "daemon_unreachable", status=503,
            detail={"url": str(endpoint.get("url")), "error": str(exc)[:200]},
        ) from exc
