"""Regression tests for the source installer/project hand-off contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools" / "install" / "install.py"


def _dry_run(*args: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(INSTALLER), "--skip-node", "--dry-run", "--json", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_source_only_install_does_not_guess_project_root(tmp_path: Path) -> None:
    result = _dry_run("--destination", str(tmp_path / "source"))

    assert result["project_root"] is None
    assert result["project_bootstrap"] == "not_requested"
    assert result["project_initialization"] == "not_requested"
    assert not any("project" in command for command in result["commands"])


def test_explicit_project_root_initializes_then_bootstraps(tmp_path: Path) -> None:
    result = _dry_run(
        "--destination", str(tmp_path / "source"),
        "--project-root", str(tmp_path / "business"),
        "--project-name", "Business project",
        "--project-objective", "Coordinate local agents",
        "--host", "codex",
    )

    assert result["project_bootstrap"] == "requested"
    assert result["project_initialization"] == "planned"
    commands = result["commands"]
    init_index = next(index for index, command in enumerate(commands) if "project init" in command)
    bootstrap_index = next(index for index, command in enumerate(commands) if "project bootstrap" in command)
    assert init_index < bootstrap_index
    assert "--name" in commands[init_index]
    assert "--objective" in commands[init_index]


def test_existing_project_manifest_skips_reinitialization(tmp_path: Path) -> None:
    project_root = tmp_path / "business"
    (project_root / ".tsunagou").mkdir(parents=True)
    (project_root / ".tsunagou" / "project.json").write_text("{}\n", encoding="utf-8")

    result = _dry_run(
        "--destination", str(tmp_path / "source"),
        "--project-root", str(project_root),
        "--host", "codex",
    )

    assert result["project_initialization"] == "existing"
    assert not any("project init" in command for command in result["commands"])
    assert any("project bootstrap" in command for command in result["commands"])
