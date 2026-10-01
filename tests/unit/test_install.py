"""Regression tests for the source installer/project hand-off contract."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools" / "install" / "install.py"


def _dry_run(*args: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(INSTALLER), "--skill-scope", "project", "--skip-node", "--dry-run", "--json", *args],
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


def test_the_installer_invents_no_objective_of_its_own(tmp_path: Path) -> None:
    """没让人指定目标时，安装器不要把一句话塞进去。

    目标由用户与主 Agent 谈定（见 docs/decisions/2026-10-01-objective-from-dialogue.md），
    所以这里什么都不传，让 `project init` 自己写占位 —— 措辞只有一处。
    """

    result = _dry_run(
        "--destination", str(tmp_path / "source"),
        "--project-root", str(tmp_path / "business"),
        "--project-name", "Business project",
        "--host", "codex",
    )

    commands = result["commands"]
    init_index = next(index for index, command in enumerate(commands) if "project init" in command)
    assert "--name" in commands[init_index]
    assert "--objective" not in commands[init_index]


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


def installer_module():
    spec = importlib.util.spec_from_file_location("source_installer", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_source_overrides_registered_checkout(tmp_path, monkeypatch):
    module = installer_module()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    old, selected = tmp_path / "old", tmp_path / "selected"
    for root in (old, selected):
        (root / "src/tsunagou").mkdir(parents=True)
        (root / "src/tsunagou/__init__.py").touch()
    registration = tmp_path / ".tsunagou/installation.json"
    registration.parent.mkdir()
    registration.write_text(json.dumps({"source_root": str(old)}), encoding="utf-8")
    assert module.resolve_destination(None) == old
    assert module.resolve_destination(None, str(selected)) == selected


def test_selected_host_skills_do_not_touch_unselected_hosts(tmp_path, monkeypatch):
    module = installer_module()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    roots = module.skill_roots(tmp_path / "source", "user", ["codex"])
    assert tmp_path / ".codex/skills" in roots
    assert tmp_path / ".agents/skills" in roots
    assert not any("opencode" in str(root) or "claude" in str(root) for root in roots)


def test_reused_runtime_install_preserves_extras_through_every_uv_step(tmp_path, monkeypatch):
    module = installer_module()
    commands = []
    repo = tmp_path / "existing-source"
    monkeypatch.setattr(module, "find_executable", lambda *names: "uv" if names == ("uv",) else None)

    def record_run(command, *, cwd, check):
        assert cwd == repo
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", record_run)
    log = []
    mode = module.install_python(repo, skip=False, dry_run=False, log=log)
    module.bootstrap_project(
        repo, tmp_path / "new-project", mode, ["codex"],
        project_name=None, project_objective=None, refresh=False, dry_run=False, log=log,
    )
    module.verify(repo, mode, skip_node=True, dry_run=False, log=log)

    # Installing the runtime must retain existing extras (pytest, mypy, etc.),
    # and init/bootstrap/verification must not silently sync them away later.
    assert commands[0] == ["uv", "sync", "--locked", "--inexact"]
    assert len(commands) == 4
    assert [command[6:8] for command in commands[1:]] == [
        ["project", "init"], ["project", "bootstrap"], ["--version"],
    ]
    assert all(command[:6] == ["uv", "run", "--no-sync", "python", "-m", "tsunagou"] for command in commands[1:])


def test_installation_timing_is_persisted_after_registration_with_monotonic_duration(tmp_path, monkeypatch):
    module = installer_module()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    repo = tmp_path / "source"
    python = repo / ".venv" / ("Scripts/python.exe" if module.os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    package = repo / "packages/bridge-server/package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"0.1.0"}', encoding="utf-8")
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, stdout="Python 3.13.13\n" if command[-1] == "--version" else "fixture-commit\n",
    ))
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 2_250_000_000)
    monkeypatch.setattr(module, "datetime", SimpleNamespace(now=lambda _: datetime(2026, 9, 28, 12, 0, 1, 250000, tzinfo=UTC)))
    if module.os.name == "nt":
        monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(
            HKEY_CURRENT_USER="test-hive", CreateKey=lambda *args: nullcontext("test-key"),
            QueryValueEx=lambda *args: (str(tmp_path / ".local/bin"), 2),
        ))

    # The wall clock moved backwards; elapsed installation duration must still
    # come from the monotonic clock, not subtraction of these UTC timestamps.
    record = module.register_installation(
        repo, dry_run=False, started_at="2026-09-28T12:00:02.000Z", started_ns=1_000_000_000,
    )
    assert record["install_started_at"] == "2026-09-28T12:00:02.000Z"
    assert record["install_finished_at"] == record["installed_at"] == "2026-09-28T12:00:01.250Z"
    assert record["duration_ms"] == 1250
    assert json.loads((tmp_path / ".tsunagou/installation.json").read_text(encoding="utf-8")) == record
    assert Path(record["launcher"]).is_file()


def test_failed_install_reports_actual_attempt_times_without_rewriting_prior_installation(tmp_path, monkeypatch, capsys):
    module = installer_module()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    prior = tmp_path / ".tsunagou/installation.json"
    prior.parent.mkdir()
    prior.write_text('{"source_root":"original-source"}', encoding="utf-8")
    before = prior.read_bytes(), prior.stat().st_mtime_ns
    monkeypatch.setattr(sys, "argv", [str(INSTALLER), "--source-root", str(tmp_path / "missing"), "--json"])
    clocks = iter([1_000_000_000, 1_075_000_000])
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: next(clocks))
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error"] == "source_root_not_tsunagou"
    assert result["install_started_at"].endswith("Z") and result["install_finished_at"].endswith("Z")
    assert result["duration_ms"] == 75
    assert (prior.read_bytes(), prior.stat().st_mtime_ns) == before
