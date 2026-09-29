"""Who works on each project, as the console remembers it.

A daemon answers ``/agents`` for its own project only, while the console is the one
component that sees every project at once. Asking each daemon on every poll would
turn one rail request into N daemon calls, so the console keeps the answer and
refreshes it on the two occasions the roster can actually change:

* **when a project is opened** — the first time its roster is needed, there is
  nothing cached to trust, so the console asks;
* **when the daemon's state changed since the cached answer.**

The second signal is the daemon's own database file, not a notification. Agents
join through the bridge straight into the daemon: nothing on that path goes through
the console, so there is nobody to notify it. Trusting the file also means the
console never has to guess which command counts as a join — any write moves the
file, and an unchanged file means the cached names are still the truth.

``state.sqlite3`` runs in WAL mode, so the writes land in ``-wal`` first: all three
files are fingerprinted, and a missing one counts as "unknown", never as "empty".
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.time import format_timestamp, now_ms

LOCAL_STATE = Path(".tsunagou") / "local"
DATABASE_FILES = ("state.sqlite3", "state.sqlite3-wal", "state.sqlite3-shm")
ROSTER_TIMEOUT = 1.5

# A fingerprint is small enough to compare and cheap enough to take on every read:
# (daemon pid, ((file, mtime_ns, size), ...)).
Fingerprint = tuple[Any, ...]


@dataclass(frozen=True)
class AgentRoster:
    """The agents a project's daemon knows about, and when the console last asked."""

    project_id: str
    main_agent_id: str | None
    agents: tuple[dict[str, Any], ...]
    fetched_at: str

    def public(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "main_agent_id": self.main_agent_id,
            "agents": [dict(agent) for agent in self.agents],
            "fetched_at": self.fetched_at,
        }


def state_directory(root: Path, endpoint: dict[str, Any] | None) -> Path:
    """Where this project keeps its private runtime files."""

    declared = (endpoint or {}).get("state_dir")
    if isinstance(declared, str) and declared:
        return Path(declared)
    return root / LOCAL_STATE


def fingerprint(root: Path, endpoint: dict[str, Any] | None) -> Fingerprint | None:
    """What the daemon's storage looked like the last time we asked.

    Returns ``None`` when the files cannot be read, which callers must treat as
    "cannot tell" rather than "nothing changed": an unreadable fingerprint must not
    be allowed to keep a stale roster alive forever.
    """

    if not isinstance(endpoint, dict):
        return None
    directory = state_directory(root, endpoint)
    rows: list[tuple[str, int, int]] = []
    for name in DATABASE_FILES:
        path = directory / name
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append((name, stat.st_mtime_ns, stat.st_size))
    if not rows:
        return None
    return (endpoint.get("pid"), endpoint.get("url"), tuple(rows))


def _get_json(url: str, path: str) -> Any:
    """GET one JSON document from a daemon; ``None`` when the answer did not arrive."""

    request = urllib.request.Request(
        url.rstrip("/") + path, headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=ROSTER_TIMEOUT) as response:
            if response.status != 200:
                return None
            return json.loads(response.read() or b"null")
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def _read_roster(root: Path, endpoint: dict[str, Any]) -> AgentRoster | None:
    """Ask one daemon who its agents are. ``None`` means the answer did not arrive."""

    project_id = str(endpoint.get("project_id") or "")
    url = str(endpoint.get("url") or "")
    if not url:
        return None
    payload = _get_json(url, f"/api/v1/projects/{project_id}/agents")
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    agents = tuple(
        {
            "agent_id": str(item.get("agent_id") or ""),
            "status": str(item.get("status") or ""),
            "role": str(item.get("role") or ""),
        }
        for item in items
        if isinstance(item, dict) and item.get("agent_id")
    )
    main = payload.get("main_agent_id")
    return AgentRoster(
        project_id=project_id or str(root),
        main_agent_id=str(main) if main else None,
        agents=agents,
        fetched_at=str(format_timestamp(now_ms()) or ""),
    )


def current_tasks(root: Path, endpoint: dict[str, Any] | None) -> dict[str, str]:
    """agent_id -> the title of the task that agent is working on right now.

    Two exits make this join: an attempt names its owner, a task names its current
    attempt. Read on demand only — the agent-list window is opened by a person, while
    "who works here" is asked on every rail poll, so the two must not cost the same.
    Anything unreadable simply leaves the field out; a wrong task title is worse than
    an empty one.
    """

    if not isinstance(endpoint, dict) or not endpoint.get("running"):
        return {}
    project_id = str(endpoint.get("project_id") or "")
    url = str(endpoint.get("url") or "")
    if not url:
        return {}
    attempts = _get_json(url, f"/api/v1/projects/{project_id}/attempts")
    tasks = _get_json(url, f"/api/v1/projects/{project_id}/tasks")
    if not isinstance(attempts, dict) or not isinstance(tasks, dict):
        return {}
    titles = {
        str(task.get("task_id")): str(task.get("title") or "")
        for task in tasks.get("items") or []
        if isinstance(task, dict) and task.get("task_id")
    }
    open_status = {"claimed", "running", "blocked", "submitted"}
    current: dict[str, str] = {}
    for attempt in attempts.get("items") or []:
        if not isinstance(attempt, dict):
            continue
        owner = str(attempt.get("owner_agent_id") or "")
        title = titles.get(str(attempt.get("task_id") or ""))
        if owner and title and str(attempt.get("status")) in open_status and owner not in current:
            current[owner] = title
    return current


class AgentDirectory:
    """The console's memory of each project's roster, keyed by storage fingerprint."""

    def __init__(self, reader: Callable[[Path, dict[str, Any]], AgentRoster | None] = _read_roster) -> None:
        self._reader = reader
        # A cached roster travels with the fingerprint it was read at; ``None`` means
        # the storage could not be read then, so the entry is never reused.
        self._cache: dict[str, tuple[Fingerprint | None, AgentRoster]] = {}
        self._lock = threading.Lock()

    def forget(self, project_id: str) -> None:
        with self._lock:
            self._cache.pop(project_id, None)

    def roster(
        self, project_id: str, root: Path, endpoint: dict[str, Any] | None, *, force: bool = False,
    ) -> AgentRoster | None:
        """The roster for one project, or ``None`` when there is nothing to show.

        ``None`` has one meaning on purpose: *this console cannot say who works here*.
        It covers "no daemon", "a daemon that did not answer" and "no roster was ever
        read" — none of which may be rendered as "this project has no agents".
        """

        if not isinstance(endpoint, dict) or not endpoint.get("running"):
            return None
        current = fingerprint(root, endpoint)
        with self._lock:
            cached = self._cache.get(project_id)
        # Only an *unreadable* fingerprint forces a fetch every time: reusing a cached
        # roster requires positive evidence that the daemon has not written since.
        if not force and current is not None and cached is not None and cached[0] == current:
            return cached[1]
        fresh = self._reader(root, endpoint)
        if fresh is None:
            # The daemon answered nothing. Keep what we have (its files are unchanged
            # or unreadable) rather than blanking names that were true a moment ago.
            return cached[1] if cached is not None else None
        with self._lock:
            self._cache[project_id] = (current, fresh)
        return fresh


def attach(entry: Any, directory: AgentDirectory) -> None:
    """Fill a discovered project with its roster, leaving it unset when unknown."""

    endpoint = entry.daemon
    lineup = directory.roster(entry.project_id, entry.path, endpoint)
    if lineup is None:
        return
    entry.main_agent_id = lineup.main_agent_id
    entry.agents = [dict(agent) for agent in lineup.agents]
    entry.agents_fetched_at = lineup.fetched_at


def gather(entries: list[Any], directory: AgentDirectory) -> dict[str, Any]:
    """Every agent on this machine, each row saying which project it works in.

    This is the one question no daemon can answer — a daemon serves a single project —
    so it is the console's job: one row per (project, agent), which is why an agent
    that works in two projects appears twice.

    Two ways of not knowing are kept apart. A project whose daemon never started has no
    endpoint at all and is simply absent, which is not a fault (the rail already shows
    that project as 未启动). A daemon that *is* up but answers nothing is a fault, so
    those projects are named in ``unreadable`` rather than quietly shrinking the list.
    """

    items: list[dict[str, Any]] = []
    unreadable: list[str] = []
    for entry in entries:
        lineup = directory.roster(entry.project_id, entry.path, entry.daemon)
        if lineup is None:
            if entry.daemon is not None:
                unreadable.append(entry.project_id)
            continue
        if not lineup.agents:
            continue
        # Only asked once there is somebody to ask about: a project without agents
        # needs no task exit at all.
        working = current_tasks(entry.path, entry.daemon)
        for agent in lineup.agents:
            items.append({
                "agent_id": agent["agent_id"],
                "role": agent.get("role", ""),
                "status": agent.get("status", ""),
                "project_id": entry.project_id,
                "project_name": entry.name,
                "task": working.get(agent["agent_id"], ""),
            })
    return {
        "items": items,
        "unreadable": unreadable,
        "fetched_at": str(format_timestamp(now_ms()) or ""),
    }
