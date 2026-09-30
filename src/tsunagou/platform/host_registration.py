"""Registering the bridge as an MCP server inside one host's own configuration.

The bridge is a **stdio** MCP server: the host is the one that spawns it. So
"adding an Agent" ends with an edit to the host's own configuration, and every host
spells that edit differently. That dialect is the only per-vendor thing in this
file — one row per host, and adding a vendor later means adding a row, not adding a
branch somewhere else.

A host with no row (or a row with ``commands=None``) is reported as
*unsupported* rather than quietly skipped: writing a config entry that cannot work
would fail much later, inside the host, where nobody can see why.

Nothing here is a secret. The host's config records the bridge command and the
*paths* its environment points at; the ticket's secret stays in its own private
file and is never part of a registration.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HostCommand:
    """One command to run, and whether a non-zero exit means the registration failed.

    Removing a previous entry is best-effort: hosts vary in how they answer
    "nothing to remove", and that answer never says anything about the entry we are
    about to add.
    """

    argv: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class Host:
    """One host product, and how to make it start our bridge.

    ``commands`` maps ``(executable, mcp_server_name, bridge_config)`` onto the
    commands to run in order; ``remove`` is how to take that entry back out again
    (used when a person cancels an enrollment they started). ``None`` means
    "no implementation yet" — the caller then reports ``unsupported`` and can show
    ``note`` verbatim to a person.
    """

    adapter: str
    label: str
    executable_names: tuple[str, ...] = ()
    executable_env: str | None = None
    windows_relative: tuple[str, ...] = ()
    commands: Callable[[str, str, Mapping[str, Any]], tuple[HostCommand, ...]] | None = None
    remove: Callable[[str, str], tuple[HostCommand, ...]] | None = None
    note: str = ""


def _codex_removal(executable: str, name: str) -> tuple[HostCommand, ...]:
    """Codex: drop one MCP entry by the name we generated for it.

    Best-effort on purpose: hosts differ in how they answer "nothing to remove", and
    that answer says nothing about the entry we are about to add. Used both before
    adding (re-enrollment is idempotent) and when an enrollment is cancelled.
    """

    return (HostCommand((executable, "mcp", "remove", name), required=False),)


def _codex_commands(executable: str, name: str, bridge: Mapping[str, Any]) -> tuple[HostCommand, ...]:
    """Codex: ``codex mcp remove`` (best effort) then ``codex mcp add`` with the env."""

    environment = bridge.get("env")
    values = environment if isinstance(environment, Mapping) else {}
    arguments = bridge.get("args")
    args = [str(item) for item in arguments] if isinstance(arguments, (list, tuple)) else []
    add = [executable, "mcp", "add", name]
    for key, value in sorted(values.items()):
        if value:
            add.extend(["--env", f"{key}={value}"])
    add.extend(["--", str(bridge.get("command") or ""), *args])
    return (*_codex_removal(executable, name), HostCommand(tuple(add)))


# One row per host product. ``adapter`` is also the bridge's own adapter name, so a
# row is the single place where "which vendor" and "which command" meet.
HOSTS: dict[str, Host] = {
    "codex": Host(
        adapter="codex",
        label="Codex",
        executable_names=("codex",),
        executable_env="CODEX_CLI_PATH",
        windows_relative=("OpenAI/Codex/bin/*/codex.exe",),
        commands=_codex_commands,
        remove=_codex_removal,
    ),
    "claudecode": Host(
        adapter="claudecode",
        label="Claude Code",
        executable_names=("claude",),
        executable_env="CLAUDE_CLI_PATH",
        note="Claude Code 的 MCP 注册还没实现（首版明确排除）。",
    ),
    "deepseek": Host(
        adapter="deepseek",
        label="DeepSeek Harness",
        note="这个宿主的 MCP 注册还没实现。",
    ),
    "opencode": Host(
        adapter="opencode",
        label="OpenCode",
        executable_names=("opencode",),
        executable_env="OPENCODE_CLI_PATH",
        note="OpenCode 的 MCP 注册还没实现。",
    ),
    "zcode": Host(
        adapter="zcode",
        label="ZCode",
        note="这个宿主的 MCP 注册还没实现。",
    ),
}

REGISTERED = "registered"
EXECUTABLE_MISSING = "executable_missing"
UNSUPPORTED = "unsupported"
FAILED = "failed"
UNREGISTERED = "unregistered"


@dataclass(frozen=True)
class Registration:
    """What happened when we tried to put the bridge into a host's configuration.

    ``commands`` are the commands themselves, not a summary of them: a person whose
    host we could not reach can run exactly that line by hand.
    """

    adapter: str
    label: str
    status: str
    name: str
    commands: tuple[tuple[str, ...], ...] = ()
    note: str = ""

    def public(self) -> dict[str, Any]:
        """The report a page may see: commands as text, never any environment value."""

        return {
            "adapter": self.adapter,
            "label": self.label,
            "status": self.status,
            "name": self.name,
            "commands": [_display(command) for command in self.commands],
            "note": self.note,
        }


@dataclass(frozen=True)
class Plan:
    """A decision plus everything needed to carry it out."""

    registration: Registration
    host: Host | None = None
    executable: str | None = None
    steps: tuple[HostCommand, ...] = ()


def _display(argv: tuple[str, ...]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in argv)


def host_for(adapter: str) -> Host | None:
    """The row for one adapter name; unknown names have no row on purpose."""

    return HOSTS.get((adapter or "").strip().lower())


def server_name(adapter: str, profile: str, project_root: Path) -> str:
    """The host-side name of one bridge: host, conversation profile, project.

    The project tag keeps two projects' bridges apart when the same host profile
    enrolls into both, and it is derived rather than random so a retry replaces the
    same entry instead of piling up new ones. A profile whose safe spelling is not the
    profile itself gets a digest, so "主 Agent" and "子 Agent" cannot become one entry.
    """

    text = (profile or "").strip()
    safe_profile = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")
    if text and safe_profile != text:
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        safe_profile = f"{safe_profile[:24]}-{digest}" if safe_profile else f"profile-{digest}"
    tag = hashlib.sha256(str(project_root).encode()).hexdigest()[:8]
    return f"tsunagou-{safe_profile or 'session'}-{tag}"


def find_executable(host: Host, *, environ: Mapping[str, str] | None = None) -> str | None:
    """Find the host's own CLI, tolerating a GUI that never exported its PATH.

    A host desktop app launches its helpers with a versioned executable under
    ``%LOCALAPPDATA%``; a process started by a person does not necessarily inherit
    that directory, so a plain ``which`` is not enough. The environment override
    wins when present, and the Windows fallback only accepts a real file.
    """

    environment: Mapping[str, str] = os.environ if environ is None else environ
    if host.executable_env:
        configured = (environment.get(host.executable_env) or "").strip().strip('"')
        if configured and Path(configured).expanduser().is_file():
            return str(Path(configured).expanduser())
    for name in host.executable_names:
        discovered = shutil.which(name)
        if discovered:
            return discovered
    if os.name == "nt" and host.windows_relative:
        local_app_data = (environment.get("LOCALAPPDATA") or "").strip()
        if local_app_data:
            found: list[Path] = []
            for pattern in host.windows_relative:
                found.extend(path for path in Path(local_app_data).glob(pattern) if path.is_file())
            if found:
                return str(sorted(found, reverse=True)[0])
    return None


def make_plan(adapter: str, *, profile: str, project_root: Path, bridge: Mapping[str, Any]) -> Plan:
    """Decide whether (and how) this host can be registered, without doing anything."""

    host = host_for(adapter)
    if host is None:
        return Plan(Registration(
            adapter=adapter, label=adapter, status=UNSUPPORTED, name="",
            note="不认识的宿主，没有对应的注册方式。",
        ))
    name = server_name(host.adapter, profile, project_root)
    if host.commands is None:
        return Plan(
            Registration(
                adapter=host.adapter, label=host.label, status=UNSUPPORTED, name=name,
                note=host.note or "这个宿主的 MCP 注册还没实现。",
            ),
            host=host,
        )
    executable = find_executable(host)
    if executable is None:
        return Plan(
            Registration(
                adapter=host.adapter, label=host.label, status=EXECUTABLE_MISSING, name=name,
                note=f"找不到 {host.label} 的命令行程序，无法把它写进宿主配置；"
                     f"装好后重试，或按返回的命令手工注册。",
            ),
            host=host,
        )
    steps = host.commands(executable, name, bridge)
    return Plan(
        Registration(
            adapter=host.adapter, label=host.label, status=REGISTERED, name=name,
            commands=tuple(step.argv for step in steps),
        ),
        host=host, executable=executable, steps=steps,
    )


def plan(adapter: str, *, profile: str, project_root: Path, bridge: Mapping[str, Any]) -> Registration:
    """The report a caller gets from planning alone — what a test asserts on."""

    return make_plan(adapter, profile=profile, project_root=project_root, bridge=bridge).registration


def register(
    adapter: str, *, profile: str, project_root: Path, bridge: Mapping[str, Any],
    run: Callable[[tuple[str, ...]], int] | None = None,
) -> Registration:
    """Put the bridge into the host's configuration, one host dialect at a time.

    The decision comes first, so "we cannot register this host" is answered before
    anything is executed; only a planned command is ever run.
    """

    prepared = make_plan(adapter, profile=profile, project_root=project_root, bridge=bridge)
    if prepared.registration.status != REGISTERED:
        return prepared.registration
    execute = run or _run
    failed = False
    for step in prepared.steps:
        if execute(step.argv) != 0 and step.required:
            failed = True
    if failed:
        return Registration(
            adapter=prepared.registration.adapter, label=prepared.registration.label,
            status=FAILED, name=prepared.registration.name,
            commands=tuple(step.argv for step in prepared.steps),
            note=f"{prepared.registration.label} 拒绝了注册命令，宿主配置可能没有改动。",
        )
    return prepared.registration


def _run(argv: tuple[str, ...]) -> int:
    result = subprocess.run(list(argv), capture_output=True, text=True, check=False)
    return int(result.returncode)


def unregister(
    adapter: str, *, profile: str, project_root: Path,
    run: Callable[[tuple[str, ...]], int] | None = None,
) -> Registration:
    """Take this conversation's bridge back out of the host's configuration.

    Used when a person cancels an enrollment they started: leaving a dead MCP entry
    behind would spawn a bridge that can never enroll, and they would have to clean it
    out by hand. Hosts without a removal command answer ``unsupported`` — the caller
    then says so instead of pretending the config is clean.
    """

    host = host_for(adapter)
    if host is None:
        return Registration(
            adapter=adapter, label=adapter, status=UNSUPPORTED, name="",
            note="不认识的宿主，没有对应的注销方式。",
        )
    name = server_name(host.adapter, profile, project_root)
    if host.remove is None:
        return Registration(
            adapter=host.adapter, label=host.label, status=UNSUPPORTED, name=name,
            note=host.note or "这个宿主还没有注销方式，它的配置里可能留着一条用不了的条目。",
        )
    executable = find_executable(host)
    if executable is None:
        return Registration(
            adapter=host.adapter, label=host.label, status=EXECUTABLE_MISSING, name=name,
            note=f"找不到 {host.label} 的命令行程序，无法从宿主配置里注销这次接入。",
        )
    steps = host.remove(executable, name)
    execute = run or _run
    for step in steps:
        execute(step.argv)
    return Registration(
        adapter=host.adapter, label=host.label, status=UNREGISTERED, name=name,
        commands=tuple(step.argv for step in steps),
    )
