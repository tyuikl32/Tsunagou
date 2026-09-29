from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _cli(*args: str, cwd: Path, env: dict[str, str] | None = None) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-m", "tsunagou", "--json", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout)


def test_project_bootstrap_cli_creates_and_reuses_project_entries(tmp_path: Path) -> None:
    repo = tmp_path / "business-project"
    (repo / ".git").mkdir(parents=True)
    source = Path(__file__).resolve().parents[2]
    index = tmp_path / "projects.json"
    initialized = _cli(
        "project", "init", "--coordination-root", str(repo),
        "--name", "CLI smoke", "--objective", "project-local onboarding",
        cwd=source, env={"TSUNAGOU_PROJECT_INDEX": str(index)},
    )
    assert initialized["status"] == "active"
    first = _cli(
        "project", "bootstrap", "--coordination-root", str(repo),
        "--source-root", str(source), "--host", "codex",
        cwd=source, env={"TSUNAGOU_PROJECT_INDEX": str(index)},
    )
    second = _cli(
        "project", "bootstrap", "--coordination-root", str(repo),
        "--source-root", str(source), "--host", "codex",
        cwd=source, env={"TSUNAGOU_PROJECT_INDEX": str(index)},
    )
    assert first["secrets_written"] is False
    assert all(item["status"] == "created" for item in first["files"])
    assert all(item["status"] == "unchanged" for item in second["files"])
    assert (repo / "AGENTS.md").is_file()
    assert (repo / ".agents/skills/tsunagou-project/SKILL.md").is_file()

    # Creating a project also registers it for readers that stand outside any one
    # project: the console has to list projects without crawling the disk.
    (registered,) = json.loads(index.read_text(encoding="utf-8"))["projects"]
    assert registered["project_id"] == initialized["project_id"]
    assert registered["name"] == "CLI smoke"
    assert registered["path"] == repo.resolve().as_posix()
    assert registered["sources"] == ["cli"]
