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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_REPOSITORY = "https://github.com/tyuikl32/Tsunagou.git"
SKILLS = ("tsunagou-agent-onboarding", "tsunagou-install")
KNOWN_USER_SKILL_DIRS = (
    ".agents/skills",
    ".codex/skills",
    ".claude/skills",
    ".cursor/skills",
    ".opencode/skills",
    ".gemini/skills",
    ".zcode/skills",
    ".factory/skills",
    ".kilocode/skills",
)


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


def resolve_destination(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    default = Path.home() / "Tsunagou"
    return default.resolve()


def ensure_clone(
    repository: str, destination: Path, ref: str | None, *, dry_run: bool, log: list[str]
) -> tuple[Path, str]:
    if destination.exists():
        if not destination.is_dir():
            raise InstallError(f"destination_not_directory:{destination}")
        if (destination / ".git").exists():
            if not ((destination / "pyproject.toml").is_file() and (destination / "packages" / "bridge-server").is_dir()):
                raise InstallError(f"existing_repository_not_tsunagou:{destination}")
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
        run([uv, "sync", "--locked"], cwd=repo, dry_run=dry_run, log=log)
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


def skill_roots(repo: Path, scope: str) -> list[Path]:
    roots = [repo / ".agents" / "skills"]
    if scope not in {"user", "all"}:
        return roots
    home = Path.home()
    codex_home = Path(os.environ["CODEX_HOME"]).expanduser() if os.environ.get("CODEX_HOME") else home / ".codex"
    roots.extend([codex_home / "skills", *(home / item for item in KNOWN_USER_SKILL_DIRS)])
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
    repo: Path, scope: str, *, force: bool, dry_run: bool, log: list[str]
) -> list[dict[str, str]]:
    source_root = repo / ".agents" / "skills"
    results: list[dict[str, str]] = []
    for root in skill_roots(repo, scope):
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
            run([uv, "run", "python", "-m", "tsunagou", "--version"], cwd=repo, dry_run=dry_run, log=log)
    else:
        python_bin = repo / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(python_bin), "-m", "tsunagou", "--version"], cwd=repo, dry_run=dry_run, log=log)
    if not skip_node:
        node = find_executable("node")
        entry = repo / "packages" / "bridge-server" / "dist" / "server.js"
        if node and entry.is_file():
            run([node, "--check", str(entry)], cwd=repo, dry_run=dry_run, log=log)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clone and install Tsunagou plus its Agent skills.")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--destination", help="Install directory; defaults to ~/Tsunagou")
    parser.add_argument("--ref", help="Git branch, tag or other clone ref")
    parser.add_argument("--skill-scope", choices=("project", "user", "all"), default="project")
    parser.add_argument("--force", action="store_true", help="Update conflicting existing Tsunagou skill directories")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-node", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logs: list[str] = []
    destination = resolve_destination(args.destination)
    try:
        repo, clone_status = ensure_clone(
            args.repository, destination, args.ref, dry_run=args.dry_run, log=logs
        )
        python_mode = install_python(repo, skip=args.skip_python, dry_run=args.dry_run, log=logs)
        node_mode = install_node(repo, skip=args.skip_node, dry_run=args.dry_run, log=logs)
        skills = install_skills(repo, args.skill_scope, force=args.force, dry_run=args.dry_run, log=logs)
        verify(repo, python_mode, skip_node=args.skip_node, dry_run=args.dry_run, log=logs)
        result: dict[str, Any] = {
            "status": "dry_run" if args.dry_run else "installed",
            "repository": args.repository,
            "destination": str(repo),
            "clone": clone_status,
            "python": python_mode,
            "node": node_mode,
            "bridge_entry": str(repo / "packages" / "bridge-server" / "dist" / "server.js"),
            "skills": skills,
            "commands": logs,
        }
    except InstallError as exc:
        result = {"status": "error", "error": str(exc), "destination": str(destination), "commands": logs}
        if args.json_output:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print(f"Tsunagou installation failed: {exc}", file=sys.stderr)
        return 1
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Tsunagou {result['status']}: {result['destination']}")
        print(f"Python: {result['python']}; Node: {result['node']}; skills: {len(skills)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
