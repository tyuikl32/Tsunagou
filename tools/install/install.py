"""Install Tsunagou from GitHub and make its project skills discoverable.

This installer is intentionally host-neutral.  A host-specific Agent skill can
clone the repository, invoke this script, and then continue with the local
onboarding skill.  It never prints tokens and it refuses to overwrite a
non-Tsunagou skill directory unless --force is supplied.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_REPOSITORY = "https://github.com/tyuikl32/Tsunagou.git"
SKILLS = ("tsunagou-agent-onboarding", "tsunagou-install")
HOST_SKILL_DIRS = {name: f".{name}/skills" for name in ("codex", "claude", "cursor", "opencode", "gemini", "zcode")}


class InstallError(RuntimeError):
    """An expected installation precondition or command failed."""


def command_text(command: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def run(command: list[str], *, cwd: Path | None, dry_run: bool, log: list[str]) -> None:
    log.append(command_text(command))
    if dry_run:
        return
    try:
        completed = subprocess.run(command, cwd=cwd, check=False)
    except OSError as exc:
        raise InstallError(f"command_unavailable:{command[0]}") from exc
    if completed.returncode != 0:
        raise InstallError(f"command_failed:{command_text(command)}:{completed.returncode}")


def find_executable(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def resolve_destination(value: str | None, source_root: str | None = None) -> Path:
    if source_root:
        source = Path(source_root).expanduser().resolve()
        if value and source != Path(value).expanduser().resolve():
            raise InstallError("source_destination_conflict")
        if not (source / "src/tsunagou/__init__.py").is_file():
            raise InstallError("source_root_not_tsunagou")
        return source
    if value:
        return Path(value).expanduser().resolve()
    registration = Path.home() / ".tsunagou/installation.json"
    if registration.is_file():
        try:
            source = Path(json.loads(registration.read_text(encoding="utf-8"))["source_root"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise InstallError("installation_registration_invalid") from exc
        if not (source / "src/tsunagou/__init__.py").is_file():
            raise InstallError("registered_source_missing:use_explicit_source_root")
        return source.resolve()
    current = Path(__file__).resolve().parents[2]
    if (current / "src/tsunagou/__init__.py").is_file():
        return current
    return (Path.home() / "Tsunagou").resolve()


def ensure_clone(
    repository: str, destination: Path, ref: str | None, *, dry_run: bool, log: list[str]
) -> tuple[Path, str]:
    if destination.exists():
        if not destination.is_dir():
            raise InstallError(f"destination_not_directory:{destination}")
        if (destination / ".git").exists():
            if not ((destination / "pyproject.toml").is_file() and (destination / "packages" / "bridge-server").is_dir()):
                raise InstallError(f"existing_repository_not_tsunagou:{destination}")
            if ref:
                requested = subprocess.run(["git", "-C", str(destination), "rev-parse", ref], capture_output=True, text=True)
                head = subprocess.run(["git", "-C", str(destination), "rev-parse", "HEAD"], capture_output=True, text=True)
                if requested.returncode or head.returncode or requested.stdout != head.stdout:
                    raise InstallError("existing_checkout_ref_mismatch")
            return destination, "reused_existing_git_repository"
        if any(destination.iterdir()):
            raise InstallError(f"destination_not_empty:{destination}")

    command = ["git", "clone"]
    if ref:
        command.extend(["--branch", ref])
    command.extend([repository, str(destination)])
    run(command, cwd=None, dry_run=dry_run, log=log)
    if not dry_run:
        if not (destination / ".git").exists():
            raise InstallError(f"clone_did_not_create_git_repository:{destination}")
    return destination, "cloned"


def install_python(repo: Path, *, skip: bool, dry_run: bool, log: list[str]) -> str:
    if skip:
        return "skipped"
    uv = find_executable("uv")
    if uv:
        run([uv, "sync", "--locked", "--inexact"], cwd=repo, dry_run=dry_run, log=log)
        return "uv"

    python = find_executable("python", "python3") or sys.executable
    venv_dir = repo / ".venv"
    run([python, "-m", "venv", str(venv_dir)], cwd=repo, dry_run=dry_run, log=log)
    python_bin = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([str(python_bin), "-m", "pip", "install", "."], cwd=repo, dry_run=dry_run, log=log)
    return "venv"


def install_node(repo: Path, *, skip: bool, dry_run: bool, log: list[str]) -> str:
    if skip:
        return "skipped"
    corepack = find_executable("corepack")
    pnpm = find_executable("pnpm")
    if corepack:
        package_command = [corepack, "pnpm"]
    elif pnpm:
        package_command = [pnpm]
    else:
        raise InstallError("node_package_manager_unavailable:corepack_or_pnpm")
    run([*package_command, "install", "--frozen-lockfile"], cwd=repo, dry_run=dry_run, log=log)
    run(
        [*package_command, "--filter", "@tsunagou/bridge-server", "run", "build"],
        cwd=repo,
        dry_run=dry_run,
        log=log,
    )
    return "corepack-pnpm" if corepack else "pnpm"


def skill_roots(repo: Path, scope: str, hosts: list[str] | None = None) -> list[Path]:
    roots = [repo / ".agents" / "skills"]
    if scope not in {"user", "all"}:
        return roots
    home = Path.home()
    codex_home = Path(os.environ["CODEX_HOME"]).expanduser() if os.environ.get("CODEX_HOME") else home / ".codex"
    roots.append(home / ".agents/skills")
    for host in hosts or []:
        if host == "generic":
            continue
        if host not in HOST_SKILL_DIRS:
            raise InstallError("unsupported_skill_host")
        roots.append(codex_home / "skills" if host == "codex" else home / HOST_SKILL_DIRS[host])
    unique: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def same_tree(source: Path, destination: Path) -> bool:
    if not destination.is_dir():
        return False
    source_files = sorted(path.relative_to(source) for path in source.rglob("*") if path.is_file())
    destination_files = sorted(path.relative_to(destination) for path in destination.rglob("*") if path.is_file())
    if source_files != destination_files:
        return False
    return all((source / relative).read_bytes() == (destination / relative).read_bytes() for relative in source_files)


def install_skills(
    repo: Path, scope: str, *, force: bool, dry_run: bool, log: list[str], hosts: list[str] | None = None,
) -> list[dict[str, str]]:
    source_root = repo / ".agents" / "skills"
    results: list[dict[str, str]] = []
    for root in skill_roots(repo, scope, hosts):
        for skill in SKILLS:
            source = source_root / skill
            destination = root / skill
            if not source.is_dir():
                if dry_run:
                    results.append({"skill": skill, "destination": str(destination), "status": "planned"})
                    continue
                raise InstallError(f"skill_source_missing:{source}")
            if destination.resolve() == source.resolve():
                results.append({"skill": skill, "destination": str(destination), "status": "source"})
                continue
            if destination.exists() and same_tree(source, destination):
                results.append({"skill": skill, "destination": str(destination), "status": "unchanged"})
                continue
            if destination.exists() and not force:
                results.append({"skill": skill, "destination": str(destination), "status": "conflict"})
                continue
            if not dry_run:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                log.append(f"copy {source} -> {destination}")
            results.append({"skill": skill, "destination": str(destination), "status": "installed"})
    conflicts = [item for item in results if item["status"] == "conflict"]
    if conflicts:
        locations = ", ".join(item["destination"] for item in conflicts)
        raise InstallError(f"skill_destination_conflict:{locations}")
    return results


def verify(repo: Path, python_mode: str, *, skip_node: bool, dry_run: bool, log: list[str]) -> None:
    if python_mode == "skipped" or dry_run:
        return
    if python_mode == "uv":
        uv = find_executable("uv")
        if uv:
            run([uv, "run", "--no-sync", "python", "-m", "tsunagou", "--version"], cwd=repo, dry_run=dry_run, log=log)
    else:
        python_bin = repo / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(python_bin), "-m", "tsunagou", "--version"], cwd=repo, dry_run=dry_run, log=log)
    if not skip_node:
        node = find_executable("node")
        entry = repo / "packages" / "bridge-server" / "dist" / "server.js"
        if node and entry.is_file():
            run([node, "--check", str(entry)], cwd=repo, dry_run=dry_run, log=log)


def bootstrap_project(
    repo: Path,
    project_root: Path,
    python_mode: str,
    hosts: list[str],
    *,
    project_name: str | None,
    project_objective: str | None,
    refresh: bool,
    dry_run: bool,
    log: list[str],
) -> str:
    """Initialize and materialize project-local rules after explicit selection."""
    if python_mode == "skipped":
        raise InstallError("project_bootstrap_requires_python_runtime")
    if python_mode == "uv":
        uv = find_executable("uv")
        if not uv:
            raise InstallError("project_bootstrap_uv_unavailable")
        command = [uv, "run", "--no-sync", "python", "-m", "tsunagou"]
    else:
        python_bin = repo / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command = [str(python_bin), "-m", "tsunagou"]

    project_manifest = project_root / ".tsunagou" / "project.json"
    initialized = project_manifest.is_file()
    if not initialized:
        resolved_name = project_name or project_root.name or "Tsunagou project"
        resolved_objective = project_objective or f"Coordinate local agents in {resolved_name}"
        run(
            [
                *command,
                "project",
                "init",
                "--coordination-root",
                str(project_root),
                "--name",
                resolved_name,
                "--objective",
                resolved_objective,
            ],
            cwd=repo,
            dry_run=dry_run,
            log=log,
        )
        initialization_status = "planned" if dry_run else "initialized"
    else:
        initialization_status = "existing"

    command.extend([
        "project", "bootstrap", "--coordination-root", str(project_root),
        "--source-root", str(repo),
    ])
    for host in hosts or ["generic"]:
        command.extend(["--host", host])
    if refresh:
        command.append("--refresh")
    run(command, cwd=repo, dry_run=dry_run, log=log)
    return initialization_status


def _installation_timing(started_at: str, started_ns: int) -> dict[str, Any]:
    return {
        "install_started_at": started_at,
        "install_finished_at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "duration_ms": (time.monotonic_ns() - started_ns) // 1_000_000,
    }


def _write_install_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".install-", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    os.replace(temporary, path)


def register_installation(repo: Path, *, dry_run: bool, started_at: str, started_ns: int) -> dict[str, Any]:
    """Bind the user command to this runtime; do not copy source into projects."""
    python = repo / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    entry = Path.home() / ".local/bin" / ("tsunagou.cmd" if os.name == "nt" else "tsunagou")
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
    registration: dict[str, Any] = {
        "source_root": str(repo), "python": str(python), "launcher": str(entry),
        "bridge_entry": str(repo / "packages/bridge-server/dist/server.js"),
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "installed_at": None,
        "install_started_at": None, "install_finished_at": None, "duration_ms": None,
        "python_version": None, "bridge_version": None, "source_dirty": None,
    }
    if dry_run:
        return registration
    if not python.is_file():
        raise InstallError("installation_python_missing")
    version = subprocess.run([str(python), "--version"], capture_output=True, text=True, check=True)
    registration["python_version"] = version.stdout.strip()
    bridge_package = repo / "packages/bridge-server/package.json"
    if bridge_package.is_file():
        registration["bridge_version"] = json.loads(bridge_package.read_text(encoding="utf-8"))["version"]
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True)
    registration["source_dirty"] = bool(dirty.stdout.strip()) if dirty.returncode == 0 else None
    content = (f'@echo off\r\n"{str(python).replace("%", "%%")}" -m tsunagou %*\r\n'
               if os.name == "nt" else f'#!/bin/sh\nexec {shlex.quote(str(python))} -m tsunagou "$@"\n')
    _write_install_file(entry, content)
    if os.name == "nt":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                old_path = winreg.QueryValueEx(key, "Path")[0]
            except FileNotFoundError:
                old_path = ""
            if str(entry.parent).casefold() not in {item.casefold() for item in old_path.split(";")}:
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, old_path.rstrip(";") + ";" + str(entry.parent))
    else:
        entry.chmod(0o755)
    registration.update(_installation_timing(started_at, started_ns))
    registration["installed_at"] = registration["install_finished_at"]
    _write_install_file(Path.home() / ".tsunagou/installation.json", json.dumps(registration, indent=2) + "\n")
    return registration


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clone and install Tsunagou plus its Agent skills.")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--destination", help="Explicit clone/install directory")
    parser.add_argument("--source-root", help="Explicit existing Tsunagou checkout; overrides saved installation")
    parser.add_argument("--ref", help="Git branch, tag or other clone ref")
    parser.add_argument("--skill-scope", choices=("project", "user", "all"), default="user")
    parser.add_argument("--force", action="store_true", help="Update conflicting existing Tsunagou skill directories")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-node", action="store_true")
    parser.add_argument(
        "--project-root",
        help="Explicit business project root; initialize it when project.json is absent, then bootstrap entries",
    )
    parser.add_argument("--project-name", help="Name used when --project-root needs project initialization")
    parser.add_argument("--project-objective", help="Objective used when --project-root needs project initialization")
    parser.add_argument("--host", action="append", default=[], dest="hosts")
    parser.add_argument("--refresh-project", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logs: list[str] = []
    destination: Path | None = None
    started_ns = time.monotonic_ns()
    started_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        destination = resolve_destination(args.destination, args.source_root)
        repo, clone_status = ensure_clone(
            args.repository, destination, args.ref, dry_run=args.dry_run, log=logs
        )
        python_mode = install_python(repo, skip=args.skip_python, dry_run=args.dry_run, log=logs)
        node_mode = install_node(repo, skip=args.skip_node, dry_run=args.dry_run, log=logs)
        skills = install_skills(repo, args.skill_scope, force=args.force, dry_run=args.dry_run, log=logs, hosts=args.hosts)
        project_initialization = "not_requested"
        if args.project_root:
            project_initialization = bootstrap_project(
                repo,
                Path(args.project_root).expanduser().resolve(),
                python_mode,
                args.hosts,
                project_name=args.project_name,
                project_objective=args.project_objective,
                refresh=args.refresh_project,
                dry_run=args.dry_run,
                log=logs,
            )
        verify(repo, python_mode, skip_node=args.skip_node, dry_run=args.dry_run, log=logs)
        installation = (register_installation(repo, dry_run=args.dry_run, started_at=started_at, started_ns=started_ns)
                        if python_mode != "skipped" else None)
        timing = _installation_timing(started_at, started_ns)
        if installation and not args.dry_run:
            timing = {key: installation[key] for key in timing}
        result: dict[str, Any] = {
            "status": "dry_run" if args.dry_run else "installed",
            "repository": args.repository,
            "destination": str(repo),
            "clone": clone_status,
            "python": python_mode,
            "node": node_mode,
            "bridge_entry": str(repo / "packages" / "bridge-server" / "dist" / "server.js"),
            "project_root": str(Path(args.project_root).expanduser().resolve()) if args.project_root else None,
            "project_bootstrap": "requested" if args.project_root else "not_requested",
            "project_initialization": project_initialization,
            "skills": skills,
            "commands": logs,
            "installation": installation,
            "started_at": started_at,
            "finished_at": timing["install_finished_at"],
            **timing,
        }
        if args.dry_run:
            # A preview has its own measured runtime, but is not an installation.
            result["install_started_at"] = result["install_finished_at"] = None
    except (InstallError, OSError, ValueError, subprocess.SubprocessError) as exc:
        timing = _installation_timing(started_at, started_ns)
        result = {"status": "error", "error": str(exc) if isinstance(exc, InstallError) else "installation_failed",
                  "destination": str(destination), "commands": logs,
                  "started_at": started_at, "finished_at": timing["install_finished_at"], **timing}
        if args.json_output:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print(f"Tsunagou installation failed: {result['error']}", file=sys.stderr)
            print(json.dumps(timing, sort_keys=True), file=sys.stderr)
        return 1
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Tsunagou {result['status']}: {result['destination']}")
        print(f"Python: {result['python']}; Node: {result['node']}; skills: {len(skills)} entries")
        print(json.dumps({key: result[key] for key in timing}, sort_keys=True))
        if installation:
            print(f"CLI: {installation['launcher']} (use this full path in an already-open terminal)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
