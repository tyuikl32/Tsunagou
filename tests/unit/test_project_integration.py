from __future__ import annotations

import json
import tempfile
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tsunagou.application.project_integration import ProjectIntegration, ProjectIntegrationError
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.digests import canonical_digest


def _project(root: Path) -> str:
    (root / ".git").mkdir(parents=True)
    registry = ProjectRegistry.initialize(root, name="demo", objective="coordinate")
    assert registry.project is not None
    return registry.project.project_id


def test_bootstrap_materializes_non_secret_project_entries(tmp_path: Path) -> None:
    root = tmp_path / "project"
    project_id = _project(root)
    source = tmp_path / "tsunagou"
    (source / ".git").mkdir(parents=True)
    result = ProjectIntegration(root).bootstrap(source_root=source, hosts=["codex"])

    assert result["project_id"] == project_id
    assert {item["status"] for item in result["files"]} == {"created"}
    assert (root / "AGENTS.md").is_file()
    assert (root / ".agents/skills/tsunagou-project/SKILL.md").is_file()
    manifest = json.loads((root / ".tsunagou/project-integration.json").read_text(encoding="utf-8"))
    schema = json.loads(
        files("tsunagou.protocol_data").joinpath("schemas/project/project-integration.schema.json").read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(manifest)) == []
    assert manifest["project_id"] == project_id
    assert manifest["source"]["install_path_hint"] == str(source.resolve())
    for path in root.rglob("*"):
        if path.is_file() and path.name not in {"project-integration.json", "agent-context.md", "AGENTS.md", "SKILL.md", ".gitignore"}:
            continue
        if path.is_file():
            assert "control.token" not in path.read_text(encoding="utf-8")
    assert "TSUNAGOU:START" in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert ".tsunagou/local/" in (root / ".gitignore").read_text(encoding="utf-8")


def test_bootstrap_is_idempotent_and_preserves_user_agents_content(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _project(root)
    (root / "AGENTS.md").write_text("# User rules\nkeep this line\n", encoding="utf-8")
    (root / ".gitignore").write_text("dist/\n", encoding="utf-8")
    integration = ProjectIntegration(root)
    first = integration.bootstrap()
    second = integration.bootstrap()

    assert first["files"][-2]["status"] == "updated"
    assert first["files"][-1]["status"] == "updated"
    assert all(item["status"] == "unchanged" for item in second["files"])
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# User rules\nkeep this line\n")
    assert agents.count("TSUNAGOU:START") == 1
    assert (root / ".gitignore").read_text(encoding="utf-8").startswith("dist/\n")


def test_bootstrap_project_lock_filename_is_windows_safe_and_root_specific(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    _project(root)
    lock_temp = tmp_path / "lock-temp"
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(lock_temp))

    ProjectIntegration(root).bootstrap()

    lock_files = list((lock_temp / "tsunagou-project-locks").iterdir())
    assert len(lock_files) == 1
    expected = canonical_digest({"coordination_root": str(root.resolve())}).replace(":", "-", 1) + ".lock"
    assert lock_files[0].name == expected
    assert ":" not in lock_files[0].name


def test_bootstrap_requires_explicit_refresh_for_managed_changes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _project(root)
    integration = ProjectIntegration(root)
    integration.bootstrap()
    context = root / ".tsunagou/agent-context.md"
    context.write_text(context.read_text(encoding="utf-8") + "user edit\n", encoding="utf-8")

    with pytest.raises(ProjectIntegrationError, match="managed_file_conflict"):
        integration.bootstrap()
    manifest_before = (root / ".tsunagou/project-integration.json").read_text(encoding="utf-8")
    refreshed = integration.bootstrap(refresh=True)
    assert any(item["status"] == "updated" for item in refreshed["files"])
    assert (root / ".tsunagou/project-integration.json").read_text(encoding="utf-8") == manifest_before


def test_refresh_does_not_overwrite_unmanaged_exact_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _project(root)
    context = root / ".tsunagou/agent-context.md"
    context.parent.mkdir(parents=True, exist_ok=True)
    context.write_text("user-owned context\n", encoding="utf-8")

    with pytest.raises(ProjectIntegrationError, match="managed_file_conflict"):
        ProjectIntegration(root).bootstrap(refresh=True)
    assert context.read_text(encoding="utf-8") == "user-owned context\n"


def test_two_projects_keep_project_entries_and_ids_isolated(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_id = _project(first_root)
    second_id = _project(second_root)
    assert first_id != second_id

    ProjectIntegration(first_root).bootstrap()
    ProjectIntegration(second_root).bootstrap()

    first_manifest = json.loads((first_root / ".tsunagou/project-integration.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second_root / ".tsunagou/project-integration.json").read_text(encoding="utf-8"))
    assert first_manifest["project_id"] == first_id
    assert second_manifest["project_id"] == second_id
    assert first_manifest["project_id"] not in (second_root / ".tsunagou/agent-context.md").read_text(encoding="utf-8")
    assert second_manifest["project_id"] not in (first_root / ".tsunagou/agent-context.md").read_text(encoding="utf-8")


def test_refresh_source_hint_does_not_change_project_id(tmp_path: Path) -> None:
    root = tmp_path / "project"
    project_id = _project(root)
    old_source = tmp_path / "old-tsunagou"
    new_source = tmp_path / "new-tsunagou"
    old_source.mkdir()
    new_source.mkdir()
    integration = ProjectIntegration(root)
    integration.bootstrap(source_root=old_source)
    refreshed = integration.bootstrap(source_root=new_source, refresh=True)
    manifest = json.loads((root / ".tsunagou/project-integration.json").read_text(encoding="utf-8"))
    assert refreshed["project_id"] == project_id
    assert manifest["project_id"] == project_id
    assert manifest["source"]["install_path_hint"] == str(new_source.resolve())
