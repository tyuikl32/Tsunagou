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
from dataclasses import dataclass, replace
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
class ConfigChange:
    """A registration that is a file we own, not a command we run.

    Some hosts configure MCP servers in a configuration *file* rather than through
    their CLI. For those, ``status`` is the decision and ``files`` is what the
    decision would touch, both computed before anything is written — so "we will
    not overwrite your file" is answered just as early as "your CLI is missing".
    """

    status: str
    files: tuple[Path, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Host:
    """One host product, and how to make it start our bridge.

    ``commands`` maps ``(executable, mcp_server_name, bridge_config)`` onto the
    commands to run in order; ``remove`` is how to take that entry back out again
    (used when a person cancels an enrollment they started). ``None`` means
    "no implementation yet" — the caller then reports ``unsupported`` and can show
    ``note`` verbatim to a person.

    A host that is configured by editing a file of its own uses ``config_preview``
    / ``config_write`` / ``config_remove`` instead: preview decides and names the
    file, write performs the edit, remove takes the entry back out. Only one of the
    two shapes is ever set for a row.
    """

    adapter: str
    label: str
    executable_names: tuple[str, ...] = ()
    executable_env: str | None = None
    windows_relative: tuple[str, ...] = ()
    commands: Callable[[str, str, Mapping[str, Any]], tuple[HostCommand, ...]] | None = None
    remove: Callable[[str, str], tuple[HostCommand, ...]] | None = None
    config_preview: Callable[[str, Mapping[str, Any]], ConfigChange] | None = None
    config_write: Callable[[str, Mapping[str, Any]], str] | None = None
    config_remove: Callable[[str, Mapping[str, Any]], str] | None = None
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


# ---------------------------------------------------------------------------
# DeepSeek Harness: a conversation-scoped overlay, never a shared profile entry
# ---------------------------------------------------------------------------
#
# Harness is a profile/plugin host: `dsh [--profile] <name>` composes a bundle stack
# plus that profile's `cordis.patch.yml` and any `--patch` overlays. External MCP
# servers are not on by default; `@deepseek-ai/dsh-mcp-client` adds them, one entry
# per server, and the model sees the tools as `mcp__<serverName>__<rawName>`.
#
# Why this row does not write into a profile
# ------------------------------------------
# A Harness MCP child is started once, when a profile loads, and it is told nothing
# about the conversation that will call it. `tools/call` carries a name and arguments
# only — no `_meta`, no session id — and the child environment is a scrubbed copy of
# the harness process environment, which never holds a session id either:
# 0.2.0-rc.2 composes `DSH_SESSION_ID` per *tool execution* (`dsh-shell-env`, from
# `execution.agent.session.header.id`), so it reaches shell tool subprocesses and
# nothing else. An entry written into a shared profile therefore cannot tell two
# conversations apart, and a new conversation booting that profile would silently
# receive the enrolled Agent, Session and `ready` status. That is not a tuning
# problem; it is the wrong place to bind an identity.
#
# What this row does instead
# --------------------------
# `agent connect` writes a private overlay *inside this conversation's own bridge
# directory* and hands back the one command that launches that conversation with
# `--patch <overlay>`. A conversation started without its own overlay gets no
# Tsunagou tools at all — the only refusal this host surface can express — and
# nothing shared between conversations exists to leak.
#
# Residual limit, stated rather than hidden: because Harness supplies no per-call
# session identity, an operator who deliberately launches a *different* conversation
# with another conversation's overlay file is indistinguishable from resuming the
# bound one. Closing that needs a plugin running inside the harness process, where
# `execution.agent.session.header.id` is available.

DEEPSEEK_MARKER = "# TSUNAGOU:MANAGED"

# The stock `@deepseek-ai/dsh-mcp-client` calls `client.callTool({name, arguments})` with no
# `_meta`, so the bridge cannot tell which conversation is calling and a conversation that
# borrows another conversation's overlay reaches Tsunagou as that other conversation. The
# provider below is the same plugin shape over the same stdio MCP server and adds the one
# missing thing: every `tools/call` carries the live session id from the runtime's own
# execution context. The bridge already requires and digests that value once
# `TSUNAGOU_HOST_META_KEY` is declared, routing each conversation to its own private
# credential file by that digest. Both lines are therefore inseparable from the install:
# the name without the package fails to load, and the key without the provider turns every
# call into `conversation_metadata_required`.
DEEPSEEK_PROVIDER_PACKAGE = "@tsunagou/dsh-host-identity"
DEEPSEEK_DEFAULT_PACKAGE = "@deepseek-ai/dsh-mcp-client"
DEEPSEEK_HOST_META_KEY = "tsunagou.hostSessionId"
DEEPSEEK_PROVIDER_DIRECTORY = "packages/adapter-deepseek-host"
# Set by the caller once the provider is really installed; never guessed here.
DEEPSEEK_HOST_IDENTITY_FLAG = "_deepseek_host_identity_ready"
DEEPSEEK_ENTRY_ID = "mcp-tsunagou"
DEEPSEEK_SERVER_NAME = "tsunagou"
DEEPSEEK_OVERLAY_NAME = "dsh-overlay.yml"
DEEPSEEK_DEFAULT_APP_PROFILE = "headless"
DEEPSEEK_LEGACY_PROFILE = "tsunagou"
BRIDGE_STATE_ENV = "TSUNAGOU_STATE_DIR"
BRIDGE_PROJECT_ENV = "TSUNAGOU_PROJECT_ROOT"


def _yaml_scalar(value: object) -> str:
    """One YAML scalar, single-quoted, so a Windows path can never change meaning."""

    return "'" + str(value).replace("'", "''") + "'"


def find_dsh_home(environ: Mapping[str, str] | None = None) -> Path:
    """The Harness config root, the way the harness launcher itself resolves it."""

    environment: Mapping[str, str] = os.environ if environ is None else environ
    configured = (environment.get("DSH_HOME") or "").strip().strip('"')
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".dsh"


def dsh_app_profile(profile: str, environ: Mapping[str, str] | None = None) -> str:
    """Which Harness profile the launch command should boot.

    The caller's profile name is Tsunagou's own bookkeeping and says nothing about
    Harness. It is only used when it really names a profile on this machine — a shipped
    template or one the person created — and otherwise the command falls back to the
    shipped ``headless`` profile. Naming a profile that does not exist makes the
    launcher refuse to boot at all, which is how this was found.
    """

    text = (profile or "").strip()
    if text and text != "current":
        candidate = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-.")
        if candidate and (find_dsh_home(environ) / "profiles" / candidate).is_dir():
            return candidate
    return DEEPSEEK_DEFAULT_APP_PROFILE


def deepseek_legacy_patch_path(profile: str, environ: Mapping[str, str] | None = None) -> Path:
    """Where the superseded shared-profile entry lived. Cleanup only."""

    text = (profile or "").strip()
    if not text or text == "current":
        text = DEEPSEEK_LEGACY_PROFILE
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-") or DEEPSEEK_LEGACY_PROFILE
    return find_dsh_home(environ) / "profiles" / name / "cordis.patch.yml"


def bridge_env(bridge: Mapping[str, Any], key: str) -> str:
    """One value out of a bridge configuration's own environment block."""

    environment = bridge.get("env")
    values = environment if isinstance(environment, Mapping) else {}
    return str(values.get(key) or "").strip()


def bridge_state_dir(bridge: Mapping[str, Any]) -> Path | None:
    """This conversation's private bridge directory, from its own configuration."""

    raw = bridge_env(bridge, BRIDGE_STATE_ENV)
    return Path(raw) if raw else None


def bridge_project_root(bridge: Mapping[str, Any]) -> Path | None:
    """The coordination project a bridge configuration belongs to."""

    raw = bridge_env(bridge, BRIDGE_PROJECT_ENV)
    return Path(raw) if raw else None


def deepseek_overlay_path(bridge: Mapping[str, Any]) -> Path:
    """The overlay only this conversation's own launch command will pass."""

    state = bridge_state_dir(bridge)
    if state is None:
        raise ValueError("deepseek_bridge_state_dir_missing")
    return state / DEEPSEEK_OVERLAY_NAME


def deepseek_overlay_text(bridge: Mapping[str, Any]) -> str:
    """The overlay body: one `insert` row carrying this conversation's bridge.

    A patch list is positional: a bare `id:` row is an *override* of an entry that
    does not exist yet and is skipped with a warning, so the entry has to arrive
    inside `insert`. Values are the *paths* the bridge needs; the ticket secret stays
    in its own private file, so no secret is written into host configuration.
    """

    environment = bridge.get("env")
    values = dict(environment) if isinstance(environment, Mapping) else {}
    # Declaring the key is what makes the bridge require per-call identity; the provider is
    # what supplies it. `register` refuses this adapter when the provider is not loadable,
    # so there is no stock-client variant of this overlay to fall back to.
    values["TSUNAGOU_HOST_META_KEY"] = DEEPSEEK_HOST_META_KEY
    arguments = bridge.get("args")
    args = [str(item) for item in arguments] if isinstance(arguments, (list, tuple)) else []
    lines = [
        DEEPSEEK_MARKER + " - this conversation only; launch with `--patch <this file>`.",
        "# Written by `tsunagou agent connect --adapter deepseek`; safe to delete.",
        "- insert:",
        f"    - id: {DEEPSEEK_ENTRY_ID}",
        f"      name: {_yaml_scalar(DEEPSEEK_PROVIDER_PACKAGE)}",
        "      config:",
        f"        serverName: {DEEPSEEK_SERVER_NAME}",
        "        transport: stdio",
        f"        command: {_yaml_scalar(bridge.get('command') or '')}",
    ]
    if args:
        lines.append("        args:")
        lines.extend(f"          - {_yaml_scalar(item)}" for item in args)
    written = [(key, value) for key, value in sorted(values.items()) if value]
    if written:
        lines.append("        env:")
        lines.extend(f"          {key}: {_yaml_scalar(value)}" for key, value in written)
    return "\n".join(lines) + "\n"


def deepseek_profiles(environ: Mapping[str, str] | None = None) -> list[str]:
    """Every app profile this Harness home can boot.

    A conversation's overlay travels on its launch command, and the app profile is chosen
    then - the same conversation can be launched under headless, web or tui. So the
    provider has to be loadable by all of them, not only by whichever profile a particular
    enrolment happened to resolve.
    """

    root = find_dsh_home(environ) / "profiles"
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if (entry / "package.json").is_file())


def _provider_installed(app_profile: str, environ: Mapping[str, str] | None = None) -> bool:
    directory = find_dsh_home(environ) / "profiles" / app_profile
    return (directory / "node_modules" / DEEPSEEK_PROVIDER_PACKAGE / "package.json").is_file()


def deepseek_provider_state(profile: str, *, environ: Mapping[str, str] | None = None) -> tuple[bool, str]:
    """Whether the identity provider can be loaded by every profile that might boot.

    A declared dependency is not an installed one: the manifest can list the package while
    the profile's ``node_modules`` has nothing to resolve, and a profile the provider was
    never installed into fails exactly that way. Only resolved directories count, and one
    missing profile is enough to make the overlay unsafe to write.
    """

    profiles = deepseek_profiles(environ)
    if not profiles:
        return False, f"no_profile:{dsh_app_profile(profile, environ)}"
    missing = [name for name in profiles if not _provider_installed(name, environ)]
    if missing:
        return False, "provider_not_installed:" + ",".join(missing)
    return True, "ready"


def ensure_deepseek_provider(profile: str, *, environ: Mapping[str, str] | None = None,
                             run: Callable[[tuple[str, ...]], int] | None = None) -> str:
    """Make the host-identity provider loadable by every profile that might boot.

    The answer decides whether this adapter may register at all: without the provider the
    overlay cannot prove its caller, and there is no silent fallback - a provider that
    cannot be installed everywhere is reported, and the caller refuses the registration.
    """

    ready, state = deepseek_provider_state(profile, environ=environ)
    if ready:
        return "already_installed"
    if not state.startswith("provider_not_installed"):
        return state
    package = _provider_directory()
    if package is None:
        return "provider_package_missing"
    execute = run or _run
    for app_profile in state.split(":", 1)[1].split(","):
        install = ["plugin", "--profile", app_profile, "add", str(package)]
        # On Windows the launcher is a `.cmd`, which CreateProcess cannot start directly;
        # the shell resolves it through PATHEXT. Without this the install silently looked
        # like a failure while the same command worked by hand.
        argv = ("cmd", "/c", "dsh", *install) if os.name == "nt" else ("dsh", *install)
        try:
            execute(argv)
        except OSError:
            # A launcher that cannot be started at all is an install that did not happen;
            # the re-check below decides, and the caller refuses rather than writing an
            # overlay it cannot verify.
            continue
    ready, state = deepseek_provider_state(profile, environ=environ)
    return "installed" if ready else f"install_unverified:{state}"


def _provider_directory() -> Path | None:
    """The provider package shipped beside the bridge, when running from a checkout."""

    candidate = Path(__file__).resolve().parents[3] / DEEPSEEK_PROVIDER_DIRECTORY
    return candidate if (candidate / "package.json").is_file() else None


def _managed_bridge_state(path: Path) -> str | None:
    """The bridge state directory a managed patch points at, if it is ours."""

    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if DEEPSEEK_MARKER not in content:
        return None
    match = re.search(r"(?m)^\s+TSUNAGOU_STATE_DIR:\s*'((?:[^']|'')*)'\s*$", content)
    return match.group(1).replace("''", "'") if match else ""


def _inside(path: Path, root: Path) -> bool:
    """Whether a recorded path really lives under the project that is asking."""

    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except (OSError, ValueError):
        return False


def preview_deepseek_overlay(profile: str, bridge: Mapping[str, Any]) -> ConfigChange:
    """Decide where this conversation's overlay goes, before writing anything.

    The target is inside the conversation's own private bridge directory, so there is
    no other project's configuration to collide with; the only refusal left is a file
    at that path that Tsunagou did not write.
    """

    try:
        overlay = deepseek_overlay_path(bridge)
    except ValueError:
        return ConfigChange(
            status=FAILED,
            note=f"bridge 配置里没有 {BRIDGE_STATE_ENV}，无法定位这个会话的私有目录。",
        )
    if overlay.exists() and _managed_bridge_state(overlay) is None:
        return ConfigChange(
            status=FAILED, files=(overlay,),
            note=f"{overlay} 已存在且不是 Tsunagou 写的，不能覆盖；请自行处理该文件。",
        )
    return ConfigChange(status=REGISTERED, files=(overlay,))


def write_deepseek_overlay(profile: str, bridge: Mapping[str, Any]) -> str:
    """Write this conversation's overlay, and retire the superseded shared entry."""

    decision = preview_deepseek_overlay(profile, bridge)
    if decision.status != REGISTERED:
        return f"deepseek_{decision.status}:{decision.note}"
    overlay = deepseek_overlay_path(bridge)
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_text(deepseek_overlay_text(bridge), encoding="utf-8", newline="\n")
    retired = retire_legacy_deepseek_entry(profile, bridge_project_root(bridge))
    return f"registered:{overlay}" + (f"|legacy_retired:{retired}" if retired else "")


def retire_legacy_deepseek_entry(profile: str, project_root: Path | None) -> str | None:
    """Blank a shared-profile entry left behind by the superseded design.

    That entry is the leak this row no longer creates: it hands the enrolled identity
    to whatever conversation boots the profile. Only a managed patch whose recorded
    bridge lives inside *this* project is touched, so one project's connect can never
    clear another project's configuration.
    """

    if project_root is None:
        return None
    patch = deepseek_legacy_patch_path(profile)
    recorded = _managed_bridge_state(patch)
    if not recorded:
        return None
    if not _inside(Path(recorded), project_root):
        return None
    patch.write_text(
        DEEPSEEK_MARKER + " - retired: a profile-wide entry gave every conversation the\n"
        "# same enrolled identity. This conversation now uses its own --patch overlay.\n[]\n",
        encoding="utf-8", newline="\n",
    )
    return str(patch)


def remove_deepseek_overlay(profile: str, scope: Mapping[str, Any]) -> str:
    """Remove the DeepSeek registration this request names — and nothing else.

    A project holds several conversations, each with its own overlay under its own
    bridge directory, so "everything under the project" is not the same set as "the
    registration being cancelled". Removal is therefore keyed by the bridge directory
    the caller names. With no name to go on, a single registration is unambiguous and
    is removed; two or more are refused, because guessing silently breaks a sibling
    conversation's next launch, which is a worse outcome than saying so.

    The shared-profile entry left by the superseded design is **always** evaluated,
    including when an overlay was just removed: that entry is the original leak, and
    returning early because something else was deleted leaves the leak in place.

    Outcomes: ``unregistered:<paths>``, ``not_owned``, ``ambiguous:<count>``,
    ``unchanged``, each optionally followed by ``|``-separated notes (``foreign_entry``
    for another project's shared entry, ``left_shared_entry`` for a same-project entry
    another conversation still depends on).
    """

    raw_root = scope.get("project_root")
    if raw_root is None:
        return "unchanged|no_project_root"
    root = Path(raw_root).resolve()
    named = scope.get("bridge_dir")
    bridge_dir = Path(str(named)).resolve() if named else None
    remove_all = bool(scope.get("all"))

    if bridge_dir is not None and not _inside(bridge_dir, root):
        # A named bridge that is not this project's must never be deleted from here, even
        # if the file looks like one of ours: ownership is the project, not the marker.
        return "not_owned"

    removed: list[str] = []
    bridges = root / ".tsunagou" / "bridges"
    if remove_all:
        # Removing a whole project's registrations is a different request from cancelling
        # one enrollment, and it is the only one that may touch every overlay.
        for path in (sorted(bridges.glob(f"*/{DEEPSEEK_OVERLAY_NAME}")) if bridges.is_dir() else []):
            if _managed_bridge_state(path) is not None:
                path.unlink()
                removed.append(str(path))
    elif bridge_dir is not None:
        overlay = bridge_dir / DEEPSEEK_OVERLAY_NAME
        if overlay.is_file() and _managed_bridge_state(overlay) is not None:
            overlay.unlink()
            removed.append(str(overlay))
    else:
        candidates = [path for path in sorted(bridges.glob(f"*/{DEEPSEEK_OVERLAY_NAME}"))
                      if _managed_bridge_state(path) is not None] if bridges.is_dir() else []
        if len(candidates) > 1:
            return f"ambiguous:{len(candidates)}"
        if candidates:
            candidates[0].unlink()
            removed.append(str(candidates[0]))
            # Remember which registration was just removed. Without this the legacy check
            # below cannot tell that the shared entry pointed at the overlay we deleted,
            # sees the file gone, and reports the entry as still depended upon.
            bridge_dir = candidates[0].parent

    notes: list[str] = []
    legacy = deepseek_legacy_patch_path(profile)
    recorded = _managed_bridge_state(legacy)
    if recorded:
        recorded_bridge = Path(recorded)
        ours = bridge_dir is not None and _same_path(recorded_bridge, bridge_dir)
        keeps_its_own = (recorded_bridge / DEEPSEEK_OVERLAY_NAME).is_file()
        if not _inside(recorded_bridge, root):
            notes.append(f"foreign_entry:{legacy}")
        elif remove_all or ours or keeps_its_own:
            # Either this whole project is going away, or it is this very registration, or
            # the conversation it names has an overlay of its own and no longer depends on
            # the shared entry.
            if retire_legacy_deepseek_entry(profile, root):
                removed.append(str(legacy))
        else:
            notes.append(f"left_shared_entry:{legacy}")

    if removed:
        body = "unregistered:" + ";".join(removed)
        return f"{body}|{'|'.join(notes)}" if notes else body
    if notes and all(note.startswith("foreign_entry") for note in notes):
        return "not_owned"
    if notes:
        return "unchanged|" + "|".join(notes)
    return "unchanged"


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
        executable_names=("dsh",),
        config_preview=preview_deepseek_overlay,
        config_write=write_deepseek_overlay,
        config_remove=remove_deepseek_overlay,
        note="写不进 DeepSeek Harness 的会话覆盖层；请检查项目的 .tsunagou/bridges 是否可写。",
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
# An entry exists but belongs to another project: refused rather than silently
# clearing configuration the caller has no claim on.
NOT_OWNED = "not_owned"


@dataclass(frozen=True)
class Registration:
    """What happened when we tried to put the bridge into a host's configuration.

    ``commands`` are the commands themselves, not a summary of them: a person whose
    host we could not reach can run exactly that line by hand. ``files`` is the same
    idea for a host configured by editing a file, and the two are never both set.
    """

    adapter: str
    label: str
    status: str
    name: str
    commands: tuple[tuple[str, ...], ...] = ()
    files: tuple[str, ...] = ()
    note: str = ""

    def public(self) -> dict[str, Any]:
        """The report a page may see: commands as text, never any environment value."""

        return {
            "adapter": self.adapter,
            "label": self.label,
            "status": self.status,
            "name": self.name,
            "commands": [_display(command) for command in self.commands],
            "files": list(self.files),
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
    if host.config_preview is not None:
        decision = host.config_preview(profile, bridge)
        return Plan(
            Registration(
                adapter=host.adapter, label=host.label, status=decision.status, name=name,
                files=tuple(str(path) for path in decision.files), note=decision.note,
            ),
            host=host,
        )
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
    if adapter == "deepseek":
        # The overlay this adapter writes carries per-call identity, which only the
        # provider can supply. Registering without it would write an overlay whose
        # credential any conversation booting it could use, so an unavailable provider is
        # a refusal here - for every caller, including the console - and never a fallback
        # to the stock client.
        provider = ensure_deepseek_provider(profile, run=run)
        if provider not in {"installed", "already_installed"}:
            return replace(
                prepared.registration, status=FAILED,
                note=(f"宿主身份 provider 不可用（{provider}）：{DEEPSEEK_PROVIDER_PACKAGE} 未安装到该 profile，"
                      "写入的 overlay 将无法证明调用者身份。请先安装该包后重试。"),
            )
    if prepared.host is not None and prepared.host.config_write is not None:
        # The decision already refused an unowned file, so the write only ever runs
        # on a file this row owns or is about to create.
        outcome = prepared.host.config_write(profile, bridge)
        if outcome.startswith("registered:"):
            _, _, detail = outcome.partition("|legacy_retired:")
            if detail:
                return replace(prepared.registration, note=f"已停用旧的 profile 级条目：{detail}")
            return prepared.registration
        return replace(
            prepared.registration, status=FAILED,
            note=outcome.split(":", 1)[1] if ":" in outcome else outcome,
        )
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
    # Host tools answer in UTF-8; decoding with the system locale raises on a non-UTF-8
    # console (a GBK Windows turns the plugin manager's output into a UnicodeDecodeError
    # inside the reader thread, which looked like a failed install).
    result = subprocess.run(list(argv), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    return int(result.returncode)


def _removal_note(notes: str) -> str:
    """Say what the removal deliberately left behind, instead of implying it was total."""

    parts: list[str] = []
    if "foreign_entry:" in notes:
        parts.append("另一项目在共享 profile 里还留着一条旧条目，未改动。")
    if "left_shared_entry:" in notes:
        parts.append("共享 profile 里那条旧条目指向的会话仍依赖它，暂时保留；它会让启动该 profile 的会话拿到旧身份。")
    if "no_project_root" in notes:
        parts.append("没有项目根目录，未改动任何配置。")
    return "".join(parts)


def unregister(
    adapter: str, *, profile: str, project_root: Path, bridge_dir: Path | None = None,
    all_registrations: bool = False,
    run: Callable[[tuple[str, ...]], int] | None = None,
) -> Registration:
    """Take one conversation's bridge back out of the host's configuration.

    Used when a person cancels an enrollment they started: leaving a dead MCP entry
    behind would spawn a bridge that can never enroll, and they would have to clean it
    out by hand. Hosts without a removal command answer ``unsupported`` — the caller
    then says so instead of pretending the config is clean.

    ``bridge_dir`` names the registration being cancelled. It is not optional in spirit:
    without it, a project with more than one enrolled conversation answers
    ``ambiguous`` rather than guessing, because deleting a sibling's entry would break
    that conversation's next launch. ``all_registrations`` is the other request a caller
    can make — "this project is going away" — and it is the only one that removes every
    overlay, including the shared entry that would otherwise be left handing out an
    identity.
    """

    host = host_for(adapter)
    if host is None:
        return Registration(
            adapter=adapter, label=adapter, status=UNSUPPORTED, name="",
            note="不认识的宿主，没有对应的注销方式。",
        )
    name = server_name(host.adapter, profile, project_root)
    if host.config_remove is not None:
        outcome = host.config_remove(profile, {"project_root": project_root, "bridge_dir": bridge_dir,
                                               "all": all_registrations})
        body, _, notes = outcome.partition("|")
        if body.startswith("unregistered:"):
            return Registration(
                adapter=host.adapter, label=host.label, status=UNREGISTERED, name=name,
                files=tuple(body.split(":", 1)[1].split(";")),
                note=_removal_note(notes),
            )
        if body.startswith("ambiguous:"):
            return Registration(
                adapter=host.adapter, label=host.label, status=NOT_OWNED, name=name,
                note=(
                    f"这个项目里有 {body.split(':', 1)[1]} 份接入记录，无从判断要注销哪一份；"
                    "请指定是哪次接入，避免删掉别的会话下次启动要用的配置。"
                ),
            )
        if body == "not_owned":
            return Registration(
                adapter=host.adapter, label=host.label, status=NOT_OWNED, name=name,
                note="那条 Harness 配置属于另一个项目，未改动；请从它自己的项目里注销。",
            )
        return Registration(
            adapter=host.adapter, label=host.label, status=UNREGISTERED, name=name,
            note=("没有 Tsunagou 自己写的 Harness 配置，宿主配置未改动。"
                  if body == "unchanged" else
                  "这个 Harness 文件不是 Tsunagou 写的，保持原样，请自行处理。")
                 + _removal_note(notes),
        )
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
