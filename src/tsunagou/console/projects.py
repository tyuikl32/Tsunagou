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
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tsunagou.console.agents import AgentDirectory, attach
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.errors import ConsoleError
from tsunagou.console.history import HistoryStore
from tsunagou.platform import host_registration
from tsunagou.platform.bridge_files import bridge_identities
from tsunagou.platform.endpoints import connectable_url as _shared_connectable_url
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
    # 这个项目的协调中心该怎么起：绑哪张网卡、哪个端口、对外公布哪个地址（向导收的）。
    # 没记过就是 None，起的时候走 CLI 的默认（回环 + 2810）。
    daemon_settings: dict[str, Any] | None = None
    # Who works here, as last read from this project's daemon. ``None`` means
    # "this console cannot say" (no daemon, or nobody asked) — never "no agents".
    main_agent_id: str | None = None
    agents: list[dict[str, Any]] | None = None
    agents_fetched_at: str | None = None
    # Only a freshly *created* project carries this: the report of writing its
    # Agent-facing entry files. It stays out of the public shape when absent, so the
    # project list (which never creates anything) is not littered with a null per row.
    bootstrap: dict[str, Any] | None = None

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
            **({"daemon_settings": self.daemon_settings} if self.daemon_settings else {}),
            "main_agent_id": self.main_agent_id,
            "agents": self.agents,
            "agents_fetched_at": self.agents_fetched_at,
            **({"bootstrap": self.bootstrap} if self.bootstrap else {}),
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


#: 绑在所有网卡上的写法。daemon 自报时就是它，但它**不是一个能拨的地址** ——
#: 2026-10-05 实测：拨 0.0.0.0 报 WinError 10049，连本机自己都连不上。
_WILDCARD_URL_HOSTS = frozenset({"0.0.0.0", "::", "[::]", "*"})


def connectable_url(url: str) -> str:
    """Kept as this module's name for the shared rule (see platform.endpoints)."""

    return _shared_connectable_url(url)


def read_endpoint(root: Path) -> dict[str, Any] | None:
    """Read where this project's daemon says it is listening."""

    path = root / LOCAL_STATE / ENDPOINT_MANIFEST
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or not raw.get("url"):
        return None
    # 自报的 url 可能是通配地址（绑 0.0.0.0 时就是它）。探活与转发都得能拨，所以在这里
    # 换掉；`advertised_url` 一个字都不动 —— 那是写进邀请、给别人照着拨的。
    raw["url"] = connectable_url(str(raw["url"]))
    return raw


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
        # "别人该拨哪个号"：邀请走的就是它，没有就用本机这个 url（只有本机能连）。
        "advertised_url": endpoint.get("advertised_url") or "",
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
            daemon_settings=item.get("daemon_settings"),
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


def _project_root_for(
    config: ConsoleConfig, *, name: str, coordination_root: str | Path | None,
) -> Path:
    """这个协作的目录放哪：向导给了就用它，没给就按项目名在 projects_root 下找一个没用过的。

    给了目录时它是**新建**的语义：那里不该已经是一个协作（那该走"登记已有协作"那条路）。
    git 仓库是 ProjectRegistry 的硬要求，所以两个分支都要 git init —— 控制台进程的 PATH 里
    没有 git 时明确报缺失，不假装建好了。
    """

    if coordination_root:
        root = Path(str(coordination_root)).expanduser()
        if read_manifest(root) is not None:
            raise ConsoleError("project_already_exists_at_path", detail={"path": root.as_posix()})
        root.mkdir(parents=True, exist_ok=True)
    else:
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
    return root


#: 绑在所有网卡上的写法（与 CLI 的 `_WILDCARD_BIND_HOSTS` 是同一套判断）。
_WILDCARD_BIND_HOSTS = frozenset({"", "0.0.0.0", "::", "[::]", "*"})


#: daemon 没被指定端口时用的那个（与 CLI 的 DEFAULT_DAEMON_PORT 一致）。
_DEFAULT_DAEMON_PORT = 2810


def _advertised_origin(declared: str, port: int | None) -> str:
    """把用户写的对外地址补全成一个完整的 origin。

    用户只写 ``192.168.32.1`` 就够：缺协议补 ``http://``，缺端口沿用向导上面那一格
    （``port``；那一格没填就用默认端口）。**已经写了的原样尊重，不重复加** —— 自己写了
    ``https://`` 或带端口，就照用户写的来。补端口这一步同时在堵一个坑：origin 不带端口
    意味着远端去拨 80，那张邀请本来就是坏的（2026-10-05 实测碰到过一次）。
    """

    text = declared.strip()
    if not text:
        return ""
    candidate = text if "://" in text else "http://" + text
    parsed = urllib.parse.urlsplit(candidate)
    hostname = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ConsoleError("advertised_url_invalid", detail={"advertised_url": declared})
    if hostname in _WILDCARD_BIND_HOSTS:
        raise ConsoleError("advertised_url_is_wildcard", detail={"advertised_url": declared})
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ConsoleError("advertised_url_must_be_an_origin", detail={"advertised_url": declared})
    if parsed.port:
        return f"{parsed.scheme}://{hostname}:{parsed.port}"
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"{parsed.scheme}://{host}:{port or _DEFAULT_DAEMON_PORT}"

def _daemon_settings(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """把向导收的四项收拾成"起协调中心时真能用的参数"，收拾不干净就明确报错。

    只做**硬的那几条**：端口像不像端口、对外地址能不能拨。像"绑了回环却公布网卡地址"
    那类警告的权威判断在 CLI 的 `_advertised_url` 里，这里不复制第二份规则；
    但"对外地址是通配地址"必须在这里挡住 —— 那种邀请发给谁都没用（2026-10-05 实测过：
    拨 0.0.0.0 报 WinError 10049，连本机自己都连不上）。
    """

    data = {
        str(key): value for key, value in (payload or {}).items()
        if value is not None and str(value).strip() != ""
    }
    if not data:
        return None
    settings: dict[str, Any] = {}
    if "port" in data:
        try:
            number = int(str(data["port"]))
        except (TypeError, ValueError):
            raise ConsoleError("daemon_port_invalid", detail={"port": str(data["port"])}) from None
        if not 1 <= number <= 65535:
            raise ConsoleError("daemon_port_invalid", detail={"port": str(data["port"])})
        settings["port"] = number
    host = str(data.get("bind_host") or "").strip()
    if host:
        settings["bind_host"] = host
    advertised = str(data.get("advertised_url") or "").strip()
    if advertised:
        settings["advertised_url"] = _advertised_origin(advertised, settings.get("port"))
    return settings or None


def create(
    config: ConsoleConfig, *, name: str, objective: str = "",
    coordination_root: str | Path | None = None,
    daemon_settings: dict[str, Any] | None = None,
) -> ProjectEntry:
    """Create a project (at ``coordination_root`` when given) and register it.

    The project is created by the backend's own registry, not by a second copy of
    the file format here: the console decides *where*, the backend decides *what*.

    A caller that supplies no objective gets the placeholder, not the project's
    own name: the goal is agreed between the user and the main Agent after the
    project exists, and a name dressed up as a goal just reads as one.
    """

    from tsunagou.modules.projects import PENDING_OBJECTIVE, ProjectRegistry

    settings = _daemon_settings(daemon_settings)
    root = _project_root_for(config, name=name, coordination_root=coordination_root)
    registry = ProjectRegistry.initialize(root, name=name, objective=objective or PENDING_OBJECTIVE)
    project = registry.project
    if project is None:  # pragma: no cover - initialize always yields a project
        raise ConsoleError("project_initialization_failed", status=500)
    # The entry files go in before anyone is invited to join: this console's own
    # onboarding asks a host conversation to become this project's Agent next, and
    # what that Agent reads first is the project's own rules file.
    bootstrap = _materialize_project_entry(root)
    entry = ProjectEntry(
        project_id=project.project_id, path=root, name=project.name, objective=project.objective,
        lifecycle=project.lifecycle, policy_revision=project.policy_revision,
        current_lineage_id=project.current_lineage_id, runtime_epoch=project.runtime_epoch,
        sources=["console"], bootstrap=bootstrap,
        daemon_settings=settings,
    )
    record_project(
        project_id=entry.project_id, path=root, name=entry.name, objective=entry.objective,
        source="console", index=config.index_path,
        daemon_settings=settings,
    )
    return entry


def _log_tail(path: Path, limit: int = 800) -> str:
    """起 daemon 那段日志的尾巴 —— 起失败时它是唯一的解释。"""

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text.strip()[-limit:]


def ensure_daemon(entry: ProjectEntry, *, autostart: bool, wait_seconds: float = 10.0) -> dict[str, Any]:
    """Return the live daemon of a project, optionally waking it up first.

    Autostart is off by default: a console that silently starts servers is hard to
    reason about. When it is switched on, the console starts the daemon the same
    way a person would from the command line -- **including the address this
    project was set up with** (``daemon_settings``). Starting it with the bare
    defaults would bind loopback while the invitations already published a NIC
    address, which is exactly the combination no remote can reach.
    """

    state = daemon_state(entry.path, probe=True)
    if state is not None and state.get("running"):
        return state
    if not autostart:
        raise ConsoleError("daemon_not_running", status=503, detail={"path": entry.path.as_posix()})
    command = [
        sys.executable, "-m", "tsunagou", "daemon", "start",
        "--coordination-root", str(entry.path),
    ]
    settings = entry.daemon_settings or {}
    if settings.get("bind_host"):
        command += ["--host", str(settings["bind_host"])]
    if settings.get("port"):
        command += ["--port", str(settings["port"])]
    if settings.get("advertised_url"):
        command += ["--advertised-url", str(settings["advertised_url"])]
    # 子进程的输出要留下来：以前丢进 DEVNULL，起失败时界面上什么也看不到。
    log_path = entry.path / ".tsunagou" / "local" / "daemon-console-start.log"
    log_handle = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("a", encoding="utf-8")
    except OSError:
        log_handle = None
    process = subprocess.Popen(
        command,
        stdout=(log_handle or subprocess.DEVNULL), stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    if log_handle is not None:
        log_handle.close()
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        state = daemon_state(entry.path, probe=True)
        if state is not None and state.get("running"):
            return state
        if process.poll() is not None:
            break
        time.sleep(0.2)
    tail = _log_tail(log_path)
    raise ConsoleError(
        "daemon_start_failed", status=503,
        detail={
            "path": entry.path.as_posix(),
            "command": " ".join(command[1:]),
            **({"log": log_path.as_posix()} if log_handle is not None else {}),
            **({"output": tail} if tail else {}),
        },
    )


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


def _clear_readonly_and_retry(func: Callable[..., Any], path: str, _exc: BaseException) -> None:
    """Let ``rmtree`` get past a read-only file — and only past a read-only file.

    On Windows git marks everything under ``.git/objects`` read-only, so a plain
    ``rmtree`` gives up on the very first object. That used to leave a project
    half-forgotten: ``forget`` had already stopped its daemon and withdrawn its
    registrations, but every file stayed on disk while the caller got a raw
    ``PermissionError``. Clearing the write bit and retrying is what the folder needs.

    A file that is *locked* rather than read-only still raises out of the retry, so a
    folder that genuinely cannot be removed is reported as a failure instead of being
    silently counted as deleted.
    """

    os.chmod(path, stat.S_IWRITE)
    func(path)


def forget(
    config: ConsoleConfig, project_id: str, *, delete_files: bool = False,
    run: Callable[[tuple[str, ...], str | None], int] | None = None,
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
    # 控制台自己那份记录跟着项目一起消失：项目行都没了，记录就没有归属。**无条件**删
    # （哪怕调用方要求保留目录文件）—— 留下它只会在下次同名项目出现时对不上号。
    history_removed = HistoryStore.beside_index(config.index_path).forget(entry.project_id)
    in_own_root = _is_inside(root, config.projects_root)
    files: dict[str, Any] = {"path": root.as_posix(), "deleted": False}
    if not delete_files:
        files["reason"] = "caller asked to keep the files"
    elif not in_own_root:
        files["reason"] = "registered project outside the console's projects_root"
    elif not root.exists():
        files["reason"] = "the folder was already gone"
    else:
        shutil.rmtree(root, onexc=_clear_readonly_and_retry)
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
        "history_removed": history_removed,
        "index": index,
        "files": files,
    }


def rename(config: ConsoleConfig, project_id: str, name: str) -> dict[str, Any]:
    """改写一个协作的显示名。

    名字只是给人看的标签，不是项目的身份：**项目号与目录都不动**，清单里其它字段原样保留。
    项目清单是权威，索引只是便利（它缓存着名字），所以两边一起写 —— 否则左栏还会显示旧名字。
    """

    wanted = str(name or "").strip()
    if not wanted:
        raise ConsoleError("project_name_required", detail={"note": "名字不能是空的。"})
    if len(wanted) > 120:
        raise ConsoleError("project_name_too_long", detail={"note": "名字太长了（最多 120 个字）。"})
    entry = find(config, project_id)
    manifest = read_manifest(entry.path)
    if manifest is None:
        raise ConsoleError(
            "project_manifest_unreadable",
            detail={"path": (entry.path / PROJECT_MANIFEST).as_posix(),
                    "note": "读不到这个项目的清单，不敢改它的名字。"},
        )
    manifest["name"] = wanted
    manifest_path = entry.path / PROJECT_MANIFEST
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    record_project(
        project_id=entry.project_id, path=entry.path, name=wanted,
        source="console", index=config.index_path,
    )
    return {
        "status": "renamed", "project_id": entry.project_id, "name": wanted,
        "path": entry.path.as_posix(),
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


def _materialize_project_entry(root: Path) -> dict[str, Any]:
    """Write the files an Agent reads to find out which project it was put into.

    A project made here is used by this console's own onboarding immediately: the
    wizard's next step asks a host conversation to join it. That Agent's first
    instruction is to read ``.tsunagou/agent-context.md`` and the managed
    ``AGENTS.md`` block *when present* -- so a project without them tells the Agent
    nothing about which project it belongs to and which conversation was prepared
    for it. It does not error out; it simply has no clue, and then follows its own
    "install and initialize a project" guidance somewhere else. That is how a second,
    unintended project gets created next to the one the person just made.

    This is the same bootstrap the CLI runs, asked for the host-neutral entry only:
    the console registers the bridge into the host's *own* configuration while
    preparing an enrollment, so asking bootstrap for a host here would register the
    same conversation twice.

    Failures are reported instead of raised: the project exists and is usable either
    way, and the caller's report should say what could not be written rather than
    pretend it was. ``register`` deliberately does not do this -- a project that
    already exists belongs to whoever put it there, files included.
    """

    from tsunagou.application.project_integration import ProjectIntegration, ProjectIntegrationError

    try:
        result = ProjectIntegration(root).bootstrap(hosts=["generic"])
    except (ProjectIntegrationError, OSError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": str(result.get("status")), "files": result.get("files")}


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
