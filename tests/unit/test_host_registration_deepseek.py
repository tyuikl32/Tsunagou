"""DeepSeek Harness registration is conversation-scoped, and must stay that way.

The defect these pin was found by independent acceptance: an entry written into a
*shared* Harness profile gave every conversation booting that profile the enrolled
Agent, Session and `ready` status, because the host tells an MCP child nothing about
which conversation is calling (no `_meta` on `tools/call`, and `DSH_SESSION_ID` is
composed per tool execution, so it only reaches shell subprocesses).

The tests assert that registration uses a private overlay, leaves shared profiles
untouched, and preserves other registrations and projects during removal. They do
not prove runtime caller identity: another conversation can still reuse an overlay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tsunagou.platform import host_registration
from tsunagou.platform.host_registration import (
    DEEPSEEK_MARKER,
    FAILED,
    NOT_OWNED,
    REGISTERED,
    UNREGISTERED,
    deepseek_legacy_patch_path,
    deepseek_overlay_path,
    deepseek_provider_state,
    dsh_app_profile,
    plan,
    register,
    unregister,
)

PROJECT = Path("/project")


def _bridge(state_dir: Path, project_root: Path = PROJECT, **extra: Any) -> dict[str, Any]:
    return {
        "adapter": "deepseek",
        "mode": "attach",
        "command": "node",
        "args": ["/checkout/packages/bridge-server/dist/server.js"],
        "env": {
            "TSUNAGOU_HTTP_URL": "http://127.0.0.1:5000",
            "TSUNAGOU_PROJECT_ROOT": str(project_root),
            "TSUNAGOU_STATE_DIR": str(state_dir),
            "TSUNAGOU_TICKET_FILE": str(state_dir / "ticket.json"),
            "TSUNAGOU_EMPTY": "",
            **extra,
        },
    }


@pytest.fixture(autouse=True)
def dsh_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A Harness home whose app profile can really load the identity provider.

    Registration for this adapter now refuses to write an overlay unless the provider is
    installed, because the overlay it writes carries per-call identity. So the fixture
    provides one; the refusal path has its own test, which removes it again.
    """

    home = tmp_path / "dsh-home"
    for name in ("headless", "main"):
        profile = home / "profiles" / name
        provider = profile / "node_modules" / "@tsunagou" / "dsh-host-identity"
        provider.mkdir(parents=True)
        (provider / "package.json").write_text('{"name": "@tsunagou/dsh-host-identity"}\n', encoding="utf-8")
        (profile / "package.json").write_text(f'{{"name": "dsh-profile-{name}", "private": true}}\n', encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(home))
    return home


def test_the_entry_lands_in_the_conversation_own_directory(tmp_path: Path) -> None:
    state = tmp_path / "project" / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)

    result = register("deepseek", profile="main", project_root=tmp_path / "project", bridge=_bridge(state))

    overlay = state / "dsh-overlay.yml"
    assert result.status == REGISTERED
    assert result.files == (str(overlay),), "the report names the file it wrote"
    assert overlay.is_file()


def test_nothing_is_written_into_a_shared_harness_profile(
    dsh_home: Path, tmp_path: Path
) -> None:
    """Registration must not add the enrolled identity to a shared profile."""

    state = tmp_path / "project" / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)

    register("deepseek", profile="worker", project_root=tmp_path / "project", bridge=_bridge(state))

    # The profile directory itself now exists because the identity provider is installed
    # there; what must never appear is an *entry*: a shared config line is exactly what let
    # a new conversation inherit the enrolled Agent.
    shared = dsh_home / "profiles"
    written = sorted(p.as_posix() for p in shared.glob("*/cordis*.yml")) if shared.is_dir() else []
    assert written == [], (
        "a shared profile entry is exactly what let a new conversation inherit the "
        "enrolled Agent; the overlay must live with the conversation instead"
    )


def test_registration_is_refused_when_the_identity_provider_is_missing(
    dsh_home: Path, tmp_path: Path
) -> None:
    """No provider means no overlay: the stock client would send no caller identity.

    The fallback used to be "keep the old client", which writes an overlay whose credential
    any conversation booting it can use. Refusing is the only safe answer.
    """

    import shutil

    for modules in dsh_home.glob("profiles/*/node_modules"):
        shutil.rmtree(modules)
    state = tmp_path / "project" / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)

    result = register("deepseek", profile="main", project_root=tmp_path / "project",
                      bridge=_bridge(state), run=lambda argv: 1)

    assert result.status == FAILED
    assert not (state / "dsh-overlay.yml").exists(), "a refused registration writes nothing"
    assert "provider" in result.note


def test_a_declared_provider_that_is_not_installed_is_not_ready(
    dsh_home: Path, tmp_path: Path
) -> None:
    """`dependencies` listing the package is not the same as the profile being able to load it."""

    import json
    import shutil

    manifest = dsh_home / "profiles" / "headless" / "package.json"
    manifest.write_text(json.dumps({
        "name": "dsh-profile-headless", "private": True,
        "dependencies": {"@tsunagou/dsh-host-identity": "link:somewhere"},
    }), encoding="utf-8")
    for modules in dsh_home.glob("profiles/*/node_modules"):
        shutil.rmtree(modules)

    ready, state = deepseek_provider_state("main")

    assert ready is False, "a declaration without a resolved package is not installed"
    assert state.startswith("provider_not_installed"), state


def test_the_entry_arrives_inside_an_insert_row(tmp_path: Path) -> None:
    state = tmp_path / "project" / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)
    register("deepseek", profile="main", project_root=tmp_path / "project", bridge=_bridge(state))

    text = (state / "dsh-overlay.yml").read_text(encoding="utf-8")

    assert text.splitlines()[0].startswith(DEEPSEEK_MARKER)
    assert "- insert:" in text, "a bare id row would override nothing and be skipped"
    assert "id: mcp-tsunagou" in text
    assert "serverName: tsunagou" in text


def test_the_bridge_paths_travel_but_no_secret_does(tmp_path: Path) -> None:
    state = tmp_path / "project" / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)
    register("deepseek", profile="main", project_root=tmp_path / "project", bridge=_bridge(state))

    text = (state / "dsh-overlay.yml").read_text(encoding="utf-8")

    assert f"TSUNAGOU_TICKET_FILE: '{state / 'ticket.json'}'" in text
    assert "TSUNAGOU_EMPTY" not in text, "an empty value is dropped, not written as an empty variable"
    assert "secret" not in text.lower(), "the ticket value stays in its own private file"


def test_the_overlay_is_written_where_the_launch_command_expects_it(tmp_path: Path) -> None:
    state = tmp_path / "project" / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)
    bridge = _bridge(state)

    assert deepseek_overlay_path(bridge) == state / "dsh-overlay.yml"
    result = register("deepseek", profile="main", project_root=tmp_path / "project", bridge=bridge)

    assert result.files == (str(deepseek_overlay_path(bridge)),)


def test_a_bridge_without_a_state_dir_is_refused_not_guessed(tmp_path: Path) -> None:
    prepared = plan("deepseek", profile="main", project_root=tmp_path,
                    bridge={"command": "node", "args": [], "env": {}})

    assert prepared.status == FAILED
    assert "TSUNAGOU_STATE_DIR" in prepared.note


def test_somebody_elses_overlay_is_left_alone(tmp_path: Path) -> None:
    state = tmp_path / "project" / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)
    overlay = state / "dsh-overlay.yml"
    mine = "# my own layer\n- id: something\n  disabled: true\n"
    overlay.write_text(mine, encoding="utf-8")

    result = register("deepseek", profile="main", project_root=tmp_path / "project", bridge=_bridge(state))

    assert result.status == FAILED
    assert overlay.read_text(encoding="utf-8") == mine


def test_repeated_connect_replaces_its_own_overlay_instead_of_stacking(tmp_path: Path) -> None:
    state = tmp_path / "project" / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)
    bridge = _bridge(state)

    register("deepseek", profile="main", project_root=tmp_path / "project", bridge=bridge)
    once = (state / "dsh-overlay.yml").read_text(encoding="utf-8")
    register("deepseek", profile="main", project_root=tmp_path / "project", bridge=bridge)

    assert (state / "dsh-overlay.yml").read_text(encoding="utf-8") == once
    assert once.count("id: mcp-tsunagou") == 1


def test_unregister_clears_this_projects_overlay(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = project / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)
    register("deepseek", profile="main", project_root=project, bridge=_bridge(state, project))

    result = unregister("deepseek", profile="main", project_root=project, bridge_dir=state)

    assert result.status == UNREGISTERED
    assert not (state / "dsh-overlay.yml").exists()


def test_cancelling_one_session_keeps_a_sibling_session_s_overlay(tmp_path: Path) -> None:
    """Second review P2: cancelling `worker` deleted the same project's `main` overlay.

    The Console cancels one enrollment, so exactly one conversation's launch
    configuration may disappear. Anything broader breaks a sibling conversation's next
    start, and the person never asked for that.
    """

    project = tmp_path / "project"
    main_state = project / ".tsunagou" / "bridges" / "deepseek-main"
    worker_state = project / ".tsunagou" / "bridges" / "deepseek-worker"
    main_state.mkdir(parents=True)
    worker_state.mkdir(parents=True)
    register("deepseek", profile="main", project_root=project, bridge=_bridge(main_state, project))
    register("deepseek", profile="worker", project_root=project, bridge=_bridge(worker_state, project))

    result = unregister("deepseek", profile="worker", project_root=project, bridge_dir=worker_state)

    assert result.status == UNREGISTERED
    assert not (worker_state / "dsh-overlay.yml").exists()
    assert (main_state / "dsh-overlay.yml").is_file(), "the sibling conversation still needs its entry"


def test_unregister_without_naming_a_registration_refuses_to_guess(tmp_path: Path) -> None:
    """Two registrations and no name: refusing beats deleting the wrong one."""

    project = tmp_path / "project"
    states = [project / ".tsunagou" / "bridges" / f"deepseek-{name}" for name in ("main", "worker")]
    for state in states:
        state.mkdir(parents=True)
        register("deepseek", profile=state.name.removeprefix("deepseek-"), project_root=project,
                 bridge=_bridge(state, project))

    result = unregister("deepseek", profile="worker", project_root=project)

    assert result.status == NOT_OWNED
    assert all((state / "dsh-overlay.yml").is_file() for state in states), "nothing may be guessed away"


def test_a_shared_entry_is_still_cleaned_when_an_overlay_was_removed(
    dsh_home: Path, tmp_path: Path
) -> None:
    """Second review P2: clearing the overlay returned early and left the shared entry live."""

    project = tmp_path / "project"
    state = project / ".tsunagou" / "bridges" / "deepseek-main"
    state.mkdir(parents=True)
    register("deepseek", profile="main", project_root=project, bridge=_bridge(state, project))
    legacy = deepseek_legacy_patch_path("main")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        DEEPSEEK_MARKER + "\n- insert:\n    - id: mcp-tsunagou\n      config:\n"
        f"        env:\n          TSUNAGOU_STATE_DIR: '{state}'\n",
        encoding="utf-8",
    )

    result = unregister("deepseek", profile="main", project_root=project, bridge_dir=state)

    assert result.status == UNREGISTERED
    assert not (state / "dsh-overlay.yml").exists()
    assert "- insert:" not in legacy.read_text(encoding="utf-8"), (
        "the shared entry hands out the old identity to whatever boots the profile"
    )


def test_a_shared_entry_another_conversation_still_needs_is_left_and_reported(
    dsh_home: Path, tmp_path: Path
) -> None:
    """Cleaning up must not strand a conversation that has no overlay of its own."""

    project = tmp_path / "project"
    mine = project / ".tsunagou" / "bridges" / "deepseek-main"
    other = project / ".tsunagou" / "bridges" / "deepseek-worker"
    mine.mkdir(parents=True)
    other.mkdir(parents=True)
    register("deepseek", profile="main", project_root=project, bridge=_bridge(mine, project))
    legacy = deepseek_legacy_patch_path("main")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        DEEPSEEK_MARKER + "\n- insert:\n    - id: mcp-tsunagou\n      config:\n"
        f"        env:\n          TSUNAGOU_STATE_DIR: '{other}'\n",
        encoding="utf-8",
    )

    result = unregister("deepseek", profile="main", project_root=project, bridge_dir=mine)

    assert result.status == UNREGISTERED
    assert "- insert:" in legacy.read_text(encoding="utf-8")
    assert "旧条目" in result.note, "the person has to be told what was deliberately left"


def test_a_shared_entry_is_retired_when_its_conversation_has_its_own_overlay(
    dsh_home: Path, tmp_path: Path
) -> None:
    """Nothing depends on the shared entry once its conversation has an overlay."""

    project = tmp_path / "project"
    mine = project / ".tsunagou" / "bridges" / "deepseek-main"
    other = project / ".tsunagou" / "bridges" / "deepseek-worker"
    mine.mkdir(parents=True)
    other.mkdir(parents=True)
    register("deepseek", profile="main", project_root=project, bridge=_bridge(mine, project))
    register("deepseek", profile="worker", project_root=project, bridge=_bridge(other, project))
    legacy = deepseek_legacy_patch_path("main")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        DEEPSEEK_MARKER + "\n- insert:\n    - id: mcp-tsunagou\n      config:\n"
        f"        env:\n          TSUNAGOU_STATE_DIR: '{other}'\n",
        encoding="utf-8",
    )

    unregister("deepseek", profile="main", project_root=project, bridge_dir=mine)

    assert (other / "dsh-overlay.yml").is_file(), "the sibling keeps its own entry"
    assert "- insert:" not in legacy.read_text(encoding="utf-8")


def test_one_projects_unregister_cannot_clear_another_projects_entry(
    dsh_home: Path, tmp_path: Path
) -> None:
    """R4: project B asking for a same-named profile must not touch project A."""

    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    state_a = project_a / ".tsunagou" / "bridges" / "deepseek-abc"
    state_a.mkdir(parents=True)
    project_b.mkdir()
    register("deepseek", profile="worker", project_root=project_a, bridge=_bridge(state_a, project_a))

    legacy = deepseek_legacy_patch_path("worker")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        DEEPSEEK_MARKER + "\n- insert:\n    - id: mcp-tsunagou\n      config:\n"
        f"        env:\n          TSUNAGOU_STATE_DIR: '{state_a}'\n",
        encoding="utf-8",
    )

    result = unregister("deepseek", profile="worker", project_root=project_b)

    assert result.status == NOT_OWNED, "refusing beats silently clearing somebody else's entry"
    assert DEEPSEEK_MARKER in legacy.read_text(encoding="utf-8")
    assert (state_a / "dsh-overlay.yml").is_file(), "project A's overlay is untouched"


def test_a_superseded_shared_entry_for_this_project_is_retired(
    dsh_home: Path, tmp_path: Path
) -> None:
    """The old shape is cleaned up, because it is the leak this row no longer makes."""

    project = tmp_path / "project"
    state = project / ".tsunagou" / "bridges" / "deepseek-abc"
    state.mkdir(parents=True)
    legacy = deepseek_legacy_patch_path("main")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        DEEPSEEK_MARKER + "\n- insert:\n    - id: mcp-tsunagou\n      config:\n"
        f"        env:\n          TSUNAGOU_STATE_DIR: '{state}'\n",
        encoding="utf-8",
    )

    result = register("deepseek", profile="main", project_root=project, bridge=_bridge(state, project))

    assert "旧的 profile 级条目" in result.note, "the caller must learn the old entry was retired"
    assert result.files == (str(state / "dsh-overlay.yml"),)
    text = legacy.read_text(encoding="utf-8")
    assert "- insert:" not in text, "the profile-wide entry must stop handing out the identity"
    assert text.strip().endswith("[]"), "a comments-only patch fails Harness boot"


def test_forgetting_a_project_removes_every_registration_and_the_shared_entry(
    dsh_home: Path, tmp_path: Path
) -> None:
    """Third review §4.1: a whole-project forget left every overlay and the shared entry."""

    project = tmp_path / "project"
    states = [project / ".tsunagou" / "bridges" / f"deepseek-{name}" for name in ("main", "worker")]
    for state in states:
        state.mkdir(parents=True)
        register("deepseek", profile=state.name.removeprefix("deepseek-"), project_root=project,
                 bridge=_bridge(state, project))
    legacy = deepseek_legacy_patch_path("main")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        DEEPSEEK_MARKER + "\n- insert:\n    - id: mcp-tsunagou\n      config:\n"
        f"        env:\n          TSUNAGOU_STATE_DIR: '{states[0]}'\n",
        encoding="utf-8",
    )

    result = unregister("deepseek", profile="main", project_root=project, all_registrations=True)

    assert result.status == UNREGISTERED
    assert all(not (state / "dsh-overlay.yml").exists() for state in states)
    assert "- insert:" not in legacy.read_text(encoding="utf-8"), "a forget must not leave the shared entry handing out an identity"


def test_the_single_candidate_default_still_retires_its_own_shared_entry(
    dsh_home: Path, tmp_path: Path
) -> None:
    """Third review §4.2: the chosen registration was forgotten, so its legacy was kept."""

    project = tmp_path / "project"
    state = project / ".tsunagou" / "bridges" / "deepseek-main"
    state.mkdir(parents=True)
    register("deepseek", profile="main", project_root=project, bridge=_bridge(state, project))
    legacy = deepseek_legacy_patch_path("main")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        DEEPSEEK_MARKER + "\n- insert:\n    - id: mcp-tsunagou\n      config:\n"
        f"        env:\n          TSUNAGOU_STATE_DIR: '{state}'\n",
        encoding="utf-8",
    )

    result = unregister("deepseek", profile="main", project_root=project)

    assert result.status == UNREGISTERED
    assert not (state / "dsh-overlay.yml").exists()
    assert "- insert:" not in legacy.read_text(encoding="utf-8"), (
        "the overlay that entry pointed at is gone, so nothing depends on it any more"
    )


def test_a_named_bridge_from_another_project_is_refused(tmp_path: Path) -> None:
    """Third review §4.3: ownership was checked on the marker, not on the project."""

    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    foreign = project_a / ".tsunagou" / "bridges" / "deepseek-main"
    foreign.mkdir(parents=True)
    project_b.mkdir()
    register("deepseek", profile="main", project_root=project_a, bridge=_bridge(foreign, project_a))

    result = unregister("deepseek", profile="main", project_root=project_b, bridge_dir=foreign)

    assert result.status == NOT_OWNED, "naming another project's bridge must not delete it"
    assert (foreign / "dsh-overlay.yml").is_file()


def test_a_profile_name_only_chooses_the_app_surface(dsh_home: Path, tmp_path: Path) -> None:
    """The Tsunagou profile name must never be handed to the launcher unchecked."""

    assert dsh_app_profile("current") == "headless"
    assert dsh_app_profile("") == "headless"
    assert dsh_app_profile("worker2") == "headless", (
        "a profile that does not exist on this machine makes `dsh --profile` refuse to boot"
    )
    (dsh_home / "profiles" / "tui").mkdir(parents=True)
    assert dsh_app_profile("tui") == "tui", "a profile that really exists is used as-is"
    assert dsh_app_profile("../escape") == "headless"
    assert host_registration.HOSTS["deepseek"].config_preview is not None
