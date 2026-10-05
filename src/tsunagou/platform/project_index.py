"""A machine-level index of the projects that live on this computer.

Coordination always happens inside exactly one project, so the core never needs to
know that other projects exist. A person does: the console has to answer "which
project am I opening?" without crawling the disk. This module keeps that short
list in one file under the user's home directory.

The index is a convenience, never a source of truth. Each project's own
``.tsunagou/project.json`` stays authoritative, entries are merged by
``project_id`` so repeated runs cannot duplicate a project, and a reader is
expected to re-check the recorded path before trusting a line.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.time import format_timestamp, now_ms

INDEX_VERSION = 1
_ENVIRONMENT_OVERRIDE = "TSUNAGOU_PROJECT_INDEX"


def index_path(home: Path | None = None) -> Path:
    """Return the index location; ``TSUNAGOU_PROJECT_INDEX`` overrides it."""

    override = os.environ.get(_ENVIRONMENT_OVERRIDE)
    if override:
        return Path(override).expanduser()
    return (home or Path.home()) / ".tsunagou" / "projects.json"


def load_index(path: Path | None = None) -> dict[str, Any]:
    """Read the index, tolerating a missing or damaged file.

    A missing index means "nothing registered yet", which is a normal state for a
    machine that has only ever used one project.
    """

    target = path or index_path()
    projects: list[dict[str, Any]] = []
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            data = {}
        raw = data.get("projects") if isinstance(data, dict) else None
        if isinstance(raw, list):
            projects = [
                item for item in raw
                if isinstance(item, dict) and isinstance(item.get("project_id"), str) and item["project_id"]
            ]
    return {"version": INDEX_VERSION, "path": str(target), "projects": projects}


def record_project(
    *,
    project_id: str,
    path: str | Path,
    name: str | None = None,
    objective: str | None = None,
    source: str = "cli",
    index: Path | None = None,
    now: int | None = None,
    daemon_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add or refresh one project, returning the entry that is now stored.

    ``source`` records who registered the project (``cli`` when the backend
    created or started it, ``console`` when the middle layer did) so a reader can
    tell where a line came from. A caller that only knows the path does not erase
    a name or objective an earlier caller did know.

    ``daemon_settings`` is how this project's coordination centre should be
    started (bind address, port, advertised address) when the console collects it
    from the new-project wizard. A caller that does not know them leaves whatever
    an earlier caller recorded in place — restarting the console must not quietly
    forget that this project is reachable from another machine.
    """

    target = index or index_path()
    stamp = format_timestamp(now if now is not None else now_ms())
    root = Path(path).expanduser().resolve()
    projects = load_index(target)["projects"]
    current = next((item for item in projects if item.get("project_id") == project_id), None)
    sources = {str(item) for item in (current or {}).get("sources") or []}
    sources.add(source)
    settings = daemon_settings or (current or {}).get("daemon_settings")
    entry: dict[str, Any] = {
        "project_id": project_id,
        "name": name or (current or {}).get("name"),
        "objective": objective or (current or {}).get("objective"),
        "path": root.as_posix(),
        "state_dir": (root / ".tsunagou").as_posix(),
        "sources": sorted(sources),
        "created_at": (current or {}).get("created_at") or stamp,
        "updated_at": stamp,
        **({"daemon_settings": settings} if settings else {}),
    }
    remaining = [item for item in projects if item.get("project_id") != project_id]
    remaining.append(entry)
    remaining.sort(key=lambda item: str(item.get("project_id")))
    _write(target, {"version": INDEX_VERSION, "projects": remaining})
    return entry


def forget_project(*, project_id: str, index: Path | None = None) -> bool:
    """Remove one line from the index, and say whether there was one to remove.

    This only forgets what the *index* said. Discovery also scans the configured
    roots, so a folder that still holds ``.tsunagou/project.json`` will show up
    again — deleting the files is the caller's separate decision.
    """

    target = index or index_path()
    projects = load_index(target)["projects"]
    remaining = [item for item in projects if str(item.get("project_id")) != project_id]
    if len(remaining) == len(projects):
        return False
    _write(target, {"version": INDEX_VERSION, "projects": remaining})
    return True


def _write(target: Path, payload: dict[str, Any]) -> None:
    """Replace the index in one step so a concurrent reader never sees half a file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)
