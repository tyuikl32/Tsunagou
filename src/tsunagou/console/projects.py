"""Which projects exist on this machine, and which daemon serves each one.

Two sources, one authority. The machine-level index (``~/.tsunagou/projects.json``)
is a convenience: it lets the console answer "what did I create?" without walking
the disk. The project's own ``.tsunagou/project.json`` is the authority, so a scan
of the configured roots always overrides an index line, and a line whose folder no
longer holds a project is reported as unavailable instead of quietly vanishing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tsunagou.console.agents import AgentDirectory, attach
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.errors import ConsoleError
from tsunagou.platform import host_registration
from tsunagou.platform.bridge_files import bridge_identities
from tsunagou.platform.project_index import forget_project as forget_index_entry
from tsunagou.platform.project_index import load_index, record_project

PROJECT_MANIFEST = Path(".tsunagou") / "project.json"
LOCAL_STATE = Path(".tsunagou") / "local"
ENDPOINT_MANIFEST = "endpoint.json"
SCAN_DEPTH = 2
HEALTH_TIMEOUT = 0.5


@dataclass
class ProjectEntry:
    """One project as the console can describe it today."""

    project_id: str
    path: Path
    name: str | None = None
    objective: str | None = None
    lifecycle: str | None = None
    policy_revision: int | None = None
    current_lineage_id: str | None = None
    runtime_epoch: str | None = None
    sources: list[str] = field(default_factory=list)
    available: bool = True
    daemon: dict[str, Any] | None = None
    # Who works here, as last read from this project's daemon. ``None`` means
    # "this console cannot say" (no daemon, or nobody asked) — never "no agents".
    main_agent_id: str | None = None
    agents: list[dict[str, Any]] | None = None
    agents_fetched_at: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "objective": self.objective,
            "lifecycle": self.lifecycle,
            "policy_revision": self.policy_revision,
            "current_lineage_id": self.current_lineage_id,
            "runtime_epoch": self.runtime_epoch,
            "sources": list(self.sources),
            "available": self.available,
            "path": self.path.as_posix(),
            "daemon": self.daemon,
            "main_agent_id": self.main_agent_id,
            "agents": self.agents,
            "agents_fetched_at": self.agents_fetched_at,
        }


def read_manifest(root: Path) -> dict[str, Any] | None:
    """Read a project's shared facts, or nothing when there is no project there."""

    path = root / PROJECT_MANIFEST
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) and raw.get("project_id") else None


def read_endpoint(root: Path) -> dict[str, Any] | None:
    """Read where this project's daemon says it is listening."""

    path = root / LOCAL_STATE / ENDPOINT_MANIFEST
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) and raw.get("url") else None


def daemon_alive(url: str) -> bool:
    """Ask the daemon itself. A leftover endpoint file is not evidence of life."""

    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/v1/health", timeout=HEALTH_TIMEOUT):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def daemon_state(root: Path, *, probe: bool = True) -> dict[str, Any] | None:
    endpoint = read_endpoint(root)
    if endpoint is None:
        return None
    state = {
        "url": endpoint.get("url"),
        "pid": endpoint.get("pid"),
        "started_at": endpoint.get("started_at"),
        "state_dir": endpoint.get("state_dir"),
        "project_id": endpoint.get("project_id"),
    }
    if probe:
        state["running"] = daemon_alive(str(endpoint["url"]))
    return state


def discover(
    config: ConsoleConfig, *, probe: bool = True, agents: AgentDirectory | None = None,
) -> list[ProjectEntry]:
    """Every project the index knows plus every project the scan roots hold.

    ``agents`` is the console's roster memory. Passing it asks each running daemon
    who works there (mostly from that memory — see :mod:`tsunagou.console.agents`);
    leaving it out keeps discovery to plain files, which is what ``find()`` wants,
    because every relayed browser request goes through it.
    """

    entries: dict[str, ProjectEntry] = {}
    for item in load_index(config.index_path)["projects"]:
        path = Path(str(item.get("path") or "")).expanduser()
        project_id = str(item["project_id"])
        entries[project_id] = ProjectEntry(
            project_id=project_id, path=path,
            name=item.get("name"), objective=item.get("objective"),
            sources=[str(source) for source in item.get("sources") or []],
            available=False,
        )
    for root in config.resolved_scan_roots():
        for manifest_path in _candidate_manifests(root):
            project_root = manifest_path.parent.parent
            manifest = read_manifest(project_root)
            if manifest is None:
                continue
            project_id = str(manifest["project_id"])
            previous = entries.get(project_id)
            entries[project_id] = ProjectEntry(
                project_id=project_id,
                path=project_root.resolve(),
                name=manifest.get("name"), objective=manifest.get("objective"),
                lifecycle=manifest.get("lifecycle"), policy_revision=manifest.get("policy_revision"),
                current_lineage_id=manifest.get("current_lineage_id"),
                runtime_epoch=manifest.get("runtime_epoch"),
                sources=sorted({*(previous.sources if previous else []), "scan"}),
                available=True,
            )
    for entry in entries.values():
        if not entry.available:
            manifest = read_manifest(entry.path)
            if manifest is None:
                continue
            entry.name = entry.name or manifest.get("name")
            entry.objective = entry.objective or manifest.get("objective")
            entry.lifecycle = entry.lifecycle or manifest.get("lifecycle")
            entry.policy_revision = entry.policy_revision or manifest.get("policy_revision")
            entry.current_lineage_id = entry.current_lineage_id or manifest.get("current_lineage_id")
            entry.runtime_epoch = entry.runtime_epoch or manifest.get("runtime_epoch")
            entry.available = True
        entry.daemon = daemon_state(entry.path, probe=probe)
        if agents is not None:
            attach(entry, agents)
    return sorted(entries.values(), key=lambda item: (item.lifecycle == "archived", str(item.name or "")))


def find(config: ConsoleConfig, project_id: str) -> ProjectEntry:
    for entry in discover(config, probe=False):
        if entry.project_id == project_id:
            return entry
    raise ConsoleError("project_not_found", status=404, detail={"project_id": project_id})


def register(
    config: ConsoleConfig, *, path: str | Path, name: str | None = None, objective: str | None = None,
) -> ProjectEntry:
    """Register a project that already exists on this machine."""

    root = Path(path).expanduser().resolve()
    manifest = read_manifest(root)
    if manifest is None:
        raise ConsoleError("project_not_found_at_path", detail={"path": root.as_posix()})
    entry = ProjectEntry(
        project_id=str(manifest["project_id"]), path=root,
        name=name or manifest.get("name"), objective=objective or manifest.get("objective"),
        lifecycle=manifest.get("lifecycle"), policy_revision=manifest.get("policy_revision"),
        current_lineage_id=manifest.get("current_lineage_id"), runtime_epoch=manifest.get("runtime_epoch"),
    )
    record_project(
        project_id=entry.project_id, path=root, name=entry.name, objective=entry.objective,
        source="console", index=config.index_path,
    )
    entry.sources = ["console"]
    entry.daemon = daemon_state(root)
    return entry


def create(config: ConsoleConfig, *, name: str, objective: str = "") -> ProjectEntry:
    """Create a project under ``projects_root`` and register it.

    The project is created by the backend's own registry, not by a second copy of
    the file format here: the console decides *where*, the backend decides *what*.
    """

    from tsunagou.modules.projects import ProjectRegistry

    root = _unused_directory(config.projects_root, name)
    root.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            ["git", "init", "--quiet", str(root)], capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        # 控制台进程的 PATH 里没有 git:项目本来是要成为 git 仓库的
        # （ProjectRegistry.initialize 也要求如此），所以这是一个明确的前置条件缺失。
        raise ConsoleError(
            "git_not_available", status=503,
            detail={"path": root.as_posix(), "hint": "把 git 放进控制台进程的 PATH（例如先 . E:\\AKW\\tools\\env.ps1）再重试"},
        ) from None
    if completed.returncode != 0:
        raise ConsoleError(
            "git_initialization_failed", status=500,
            detail={"path": root.as_posix(), "stderr": (completed.stderr or "").strip()[:500]},
        )
    registry = ProjectRegistry.initialize(root, name=name, objective=objective or name)
    project = registry.project
    if project is None:  # pragma: no cover - initialize always yields a project
        raise ConsoleError("project_initialization_failed", status=500)
    entry = ProjectEntry(
        project_id=project.project_id, path=root, name=project.name, objective=project.objective,
        lifecycle=project.lifecycle, policy_revision=project.policy_revision,
        current_lineage_id=project.current_lineage_id, runtime_epoch=project.runtime_epoch,
        sources=["console"],
    )
    record_project(
        project_id=entry.project_id, path=root, name=entry.name, objective=entry.objective,
        source="console", index=config.index_path,
    )
    return entry


def ensure_daemon(entry: ProjectEntry, *, autostart: bool, wait_seconds: float = 10.0) -> dict[str, Any]:
    """Return the live daemon of a project, optionally waking it up first.

    Autostart is off by default: a console that silently starts servers is hard to
    reason about. When it is switched on, the console starts the daemon the same
    way a person would from the command line.
    """

    state = daemon_state(entry.path, probe=True)
    if state is not None and state.get("running"):
        return state
    if not autostart:
        raise ConsoleError("daemon_not_running", status=503, detail={"path": entry.path.as_posix()})
    process = subprocess.Popen(
        [sys.executable, "-m", "tsunagou", "daemon", "start", "--coordination-root", str(entry.path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        state = daemon_state(entry.path, probe=True)
        if state is not None and state.get("running"):
            return state
        if process.poll() is not None:
            break
        time.sleep(0.2)
    raise ConsoleError("daemon_start_failed", status=503, detail={"path": entry.path.as_posix()})


def stop_daemon(root: Path, *, kill: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Stop this project's daemon, if one is running.

    A leftover endpoint file is not evidence of life, so the daemon is asked first.
    Nothing here is fatal: a project whose daemon refuses to die is still a project
    the user asked to be rid of, and the report says what happened rather than
    pretending the stop succeeded.
    """

    endpoint = read_endpoint(root)
    if endpoint is None:
        return {"status": "not_running"}
    url = str(endpoint.get("url") or "")
    pid = endpoint.get("pid")
    if url and not daemon_alive(url):
        return {"status": "not_running", "url": url, "pid": pid}
    if not isinstance(pid, int):
        return {"status": "unknown", "url": url, "detail": "endpoint file has no pid"}
    try:
        (kill or _terminate)(pid)
    except OSError as exc:
        return {"status": "failed", "url": url, "pid": pid, "detail": str(exc)}
    return {"status": "stopped", "url": url, "pid": pid}


def _terminate(pid: int) -> None:
    """Kill a process tree the same way ``tsunagou daemon stop`` does."""

    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        os.kill(pid, 15)


def bridge_profiles(root: Path) -> list[tuple[str, str]]:
    """``(adapter, profile)`` for every bridge this project has prepared.

    One entry per conversation we ever wrote a bridge config for. Reading the
    adapter out of the config (rather than splitting the folder name) keeps the
    profile intact even when a nickname contains a dash.
    """

    return [(item["adapter"], item["profile"]) for item in bridge_identities(root)]


def forget(
    config: ConsoleConfig, project_id: str, *, delete_files: bool = False,
    run: Callable[[tuple[str, ...]], int] | None = None,
) -> dict[str, Any]:
    """Delete one whole project: its daemon, its host registrations, its line, its files.

    There is deliberately no step-by-step undo in this console, so this is the
    single "get rid of it" action. The order matters — stop the daemon first (it owns
    the state directory), take the bridge registrations back out next (a live
    registration would keep pointing at a project nobody can see), then forget the
    pending enrollments and the index line, and only then (optionally) remove files.

    Files are only removed when the project sits **inside** the console's own
    ``projects_root``: a project that was merely registered from somewhere else on this
    machine belongs to whoever put it there, and the report says the folder was kept.
    """

    entry = find(config, project_id)
    root = entry.path
    # Imported here, not at module scope: enrollment imports this module.
    from tsunagou.console import enrollment

    daemon = stop_daemon(root)
    registrations: list[dict[str, Any]] = []
    for adapter, profile in bridge_profiles(root):
        # Forgetting a project removes every registration it holds, which is a different
        # request from cancelling one enrollment: without this the call carries no
        # bridge_dir, a project with two conversations answers ambiguous, and every
        # overlay plus the shared entry survive a forget that reported success.
        outcome = host_registration.unregister(adapter, profile=profile, project_root=root,
                                              all_registrations=True, run=run)
        registrations.append({"adapter": adapter, "profile": profile, **outcome.public()})
    dropped = enrollment.forget_project(entry.project_id)
    in_own_root = _is_inside(root, config.projects_root)
    files: dict[str, Any] = {"path": root.as_posix(), "deleted": False}
    if not delete_files:
        files["reason"] = "caller asked to keep the files"
    elif not in_own_root:
        files["reason"] = "registered project outside the console's projects_root"
    elif not root.exists():
        files["reason"] = "the folder was already gone"
    else:
        shutil.rmtree(root, ignore_errors=False)
        files["deleted"] = True
    index = {"removed": forget_index_entry(project_id=entry.project_id, index=config.index_path)}
    return {
        "status": "forgotten",
        "project_id": entry.project_id,
        "name": entry.name,
        "path": root.as_posix(),
        "daemon": daemon,
        "host_registrations": registrations,
        "enrollments_dropped": dropped,
        "index": index,
        "files": files,
    }


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
        base = parent.expanduser().resolve()
    except OSError:  # pragma: no cover - unresolvable path is not inside anything
        return False
    return resolved == base or base in resolved.parents


def _candidate_manifests(root: Path) -> list[Path]:

    found: list[Path] = []
    base = root / PROJECT_MANIFEST
    if base.is_file():
        found.append(base)
    for depth in range(1, SCAN_DEPTH + 1):
        pattern = "/".join(["*"] * depth) + "/.tsunagou/project.json"
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                found.append(path)
    return found


def _unused_directory(parent: Path, name: str) -> Path:
    """A readable folder name for a new project, never an existing one."""

    slug = _slug(name) or "project"
    candidate = parent / slug
    suffix = 2
    while candidate.exists():
        candidate = parent / f"{slug}-{suffix}"
        suffix += 1
    return candidate


def _slug(name: str) -> str:
    """Keep letters and digits (including CJK), fold everything else to a dash."""

    folded = [character.lower() if character.isalnum() else "-" for character in str(name).strip()]
    slug = "".join(folded).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug
