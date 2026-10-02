"""Resolve one local project and installation consistently, without credentials."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def read_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("runtime_metadata_invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeError("runtime_metadata_invalid")
    return value


def installation_path() -> Path:
    return Path.home() / ".tsunagou" / "installation.json"


def is_source_root(path: Path) -> bool:
    return (path / "src/tsunagou/__init__.py").is_file() and (path / "packages/bridge-server/package.json").is_file()


def running_source_root() -> Path | None:
    # Editable installation and the installer's non-editable .venv fallback.
    candidates = [Path(__file__).resolve().parents[3]]
    executable_parents = Path(sys.executable).absolute().parents
    if len(executable_parents) > 2:
        candidates.append(executable_parents[2])
    for candidate in candidates:
        if is_source_root(candidate):
            return candidate
    return None


def find_project_root(cwd: Path) -> Path:
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".tsunagou/project.json").is_file():
            return candidate
    return cwd


@dataclass(frozen=True)
class RuntimeContext:
    project_root: Path
    state_dir: Path
    project_id: str | None
    endpoint: dict[str, Any]
    daemon_url: str | None
    source_root: Path | None


def resolve_runtime(
    project_root: Path | None = None, *, cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> RuntimeContext:
    env = os.environ if environ is None else environ
    configured_root = Path(env["TSUNAGOU_PROJECT_ROOT"]).expanduser().resolve() if env.get("TSUNAGOU_PROJECT_ROOT") else None
    explicit_root = project_root.expanduser().resolve() if project_root else None
    if explicit_root and configured_root and explicit_root != configured_root:
        raise RuntimeError("project_context_conflict")
    root = explicit_root or configured_root or find_project_root((cwd or Path.cwd()).resolve())
    project = read_object(root / ".tsunagou/project.json")
    actual_id = project.get("project_id")
    configured_id = env.get("TSUNAGOU_PROJECT_ID")
    if actual_id and configured_id and actual_id != configured_id:
        raise RuntimeError("project_context_conflict")
    project_id = actual_id or configured_id
    state = Path(env["TSUNAGOU_STATE_DIR"]).expanduser().resolve() if env.get("TSUNAGOU_STATE_DIR") else root / ".tsunagou/local"
    endpoint = read_object(state / "endpoint.json")
    if project_id and endpoint.get("project_id") not in {None, project_id}:
        raise RuntimeError("project_context_conflict")
    configured_url = env.get("TSUNAGOU_DAEMON_URL", "").rstrip("/")
    recorded_url = str(endpoint.get("url") or "").rstrip("/")
    if configured_url and recorded_url and configured_url != recorded_url:
        raise RuntimeError("daemon_context_conflict")
    integration = read_object(root / ".tsunagou/project-integration.json")
    source = integration.get("source", {}).get("install_path_hint")
    if not source:
        source = read_object(installation_path()).get("source_root")
    return RuntimeContext(root, state, project_id, endpoint, configured_url or recorded_url or None,
                          Path(source).expanduser().resolve() if source else None)
