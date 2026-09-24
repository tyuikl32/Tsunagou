from pathlib import Path

import pytest

from tsunagou.modules.projects import PathRule, ProjectRegistry, is_within


def test_project_init_persists_without_commit_and_hides_local_paths(tmp_path: Path) -> None:
    repo = tmp_path / "coordination"
    (repo / ".git").mkdir(parents=True)
    root = tmp_path / "source"
    (root / "src").mkdir(parents=True)
    registry = ProjectRegistry.initialize(repo, name="demo", objective="coordinate")
    root_id = registry.register_root("source", root)
    export = registry.shared_export()
    assert registry.project is not None
    assert registry.shared_path.exists()
    assert str(root) not in str(export)
    assert registry.path_allowed(PathRule(root_id, ("src",)), root / "src" / "main.py")
    assert not registry.path_allowed(PathRule(root_id, ("src",)), tmp_path / "escape.py")


def test_rule_intersection_and_link_escape_are_segment_aware(tmp_path: Path) -> None:
    assert PathRule("r", ("src",)).intersect(PathRule("r", ("src", "pkg"))) == PathRule(
        "r", ("src", "pkg")
    )
    assert PathRule("r", ("src",)).intersect(PathRule("other", ("src",))) is None
    root = tmp_path / "root"
    target = tmp_path / "target"
    root.mkdir()
    target.mkdir()
    link = root / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    assert not is_within(root, link / "file.txt")


def test_unbound_root_is_diagnostic_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    registry = ProjectRegistry.initialize(repo, name="demo", objective="x")
    root_id = registry.register_root("root", tmp_path / "root")
    registry.unbind_root(root_id)
    report = registry.diagnose()
    assert report["roots"][root_id]["status"] == "unbound"


def test_auto_wake_project_policy_is_explicit_and_persistent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    registry = ProjectRegistry.initialize(repo, name="demo", objective="x")
    assert registry.project is not None
    assert registry.project.settings == {}
    before = registry.project.policy_revision
    registry.configure(policy_patch={"auto_wake_multi_agent": True}, reason="enable coordination")
    assert registry.project.settings["auto_wake_multi_agent"] is True
    assert registry.project.policy_revision == before + 1
    reloaded = ProjectRegistry(repo)
    assert reloaded.project is not None
    assert reloaded.project.settings["auto_wake_multi_agent"] is True
    with pytest.raises(ValueError, match="unsupported_policy_patch"):
        reloaded.configure(policy_patch={"unknown": True}, reason="invalid")
