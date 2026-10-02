from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tsunagou.platform import runtime_context
from tsunagou.platform.runtime_context import resolve_runtime


def project(root: Path, identity: str = "project-a") -> Path:
    state = root / ".tsunagou/local"
    state.mkdir(parents=True)
    (state.parent / "project.json").write_text(json.dumps({"project_id": identity}), encoding="utf-8")
    (state / "endpoint.json").write_text(json.dumps({"project_id": identity, "url": "http://127.0.0.1:9999"}), encoding="utf-8")
    return state


def test_subdirectory_resolves_one_project_state_and_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    root = tmp_path / "business"
    state = project(root)
    nested = root / "src/sub"
    nested.mkdir(parents=True)
    runtime = resolve_runtime(cwd=nested, environ={})
    assert runtime.project_root == root and runtime.state_dir == state
    assert runtime.project_id == "project-a" and runtime.daemon_url == "http://127.0.0.1:9999"


def test_running_source_root_tolerates_shallow_system_python(monkeypatch):
    monkeypatch.setattr(runtime_context.sys, "executable", r"D:\python\python.exe")

    assert runtime_context.running_source_root() == Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("conflict", ["root", "id", "state", "url"])
def test_conflicting_project_inputs_never_choose_another_credential(tmp_path, conflict):
    root = tmp_path / "one"
    project(root)
    other_state = project(tmp_path / "two", "project-b")
    env = {
        "root": {"TSUNAGOU_PROJECT_ROOT": str(tmp_path / "two")},
        "id": {"TSUNAGOU_PROJECT_ID": "project-b"},
        "state": {"TSUNAGOU_STATE_DIR": str(other_state)},
        "url": {"TSUNAGOU_DAEMON_URL": "http://127.0.0.1:1111"},
    }[conflict]
    with pytest.raises(RuntimeError, match="context_conflict"):
        resolve_runtime(root, environ=env)


def test_cli_explicit_root_is_scoped_to_one_invocation(tmp_path, monkeypatch):
    cli = importlib.import_module("tsunagou.cli.app")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for name in ("TSUNAGOU_PROJECT_ROOT", "TSUNAGOU_STATE_DIR", "TSUNAGOU_DAEMON_URL", "TSUNAGOU_PROJECT_ID"):
        monkeypatch.delenv(name, raising=False)
    roots = [tmp_path / "one", tmp_path / "two"]
    for i, root in enumerate(roots):
        project(root, f"project-{i}")
    observed = []

    def request(*args, **kwargs):
        observed.append(cli._project_root())
        return {}

    monkeypatch.setattr(cli, "_daemon_request", request)
    for root in roots:
        result = CliRunner().invoke(cli.app, ["--project-root", str(root), "--json", "doctor"])
        assert result.exit_code == 0, result.output
    assert observed == [roots[0], roots[0], roots[1], roots[1]]
    assert cli._selected_project_root.get() is None
