"""One host, one dialect: how the bridge gets written into a host's own config.

The table is the whole point of this module — adding a vendor means adding a row, so
these tests pin the row's shape: what a plan says when the host exists, when it does
not, and when its command line is missing, plus that only planned commands are run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tsunagou.platform import host_registration
from tsunagou.platform.host_registration import (
    EXECUTABLE_MISSING,
    FAILED,
    HOSTS,
    REGISTERED,
    UNSUPPORTED,
    find_executable,
    host_for,
    make_plan,
    plan,
    register,
    server_name,
)

BRIDGE: dict[str, Any] = {
    "adapter": "codex",
    "mode": "attach",
    "command": "node",
    "args": ["/checkout/packages/bridge-server/dist/server.js"],
    "env": {
        "TSUNAGOU_HTTP_URL": "http://127.0.0.1:5000",
        "TSUNAGOU_TICKET_FILE": "/project/.tsunagou/bridges/codex-main/ticket.json",
        "TSUNAGOU_STATE_DIR": "/project/.tsunagou/bridges/codex-main",
        "TSUNAGOU_EMPTY": "",
    },
}


def _with_codex_at(monkeypatch: pytest.MonkeyPatch, executable: str | None) -> None:
    monkeypatch.setattr(host_registration, "find_executable", lambda host, **_: executable)


def test_the_report_is_the_command_as_text_so_a_person_can_run_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _with_codex_at(monkeypatch, "codex")
    prepared = plan("codex", profile="main", project_root=tmp_path, bridge=BRIDGE)

    report = prepared.public()

    assert report["status"] == REGISTERED
    assert report["commands"] and all(isinstance(item, str) for item in report["commands"])
    assert report["commands"][-1].startswith("codex mcp add ")
    assert "env" not in report, "the environment travels in the command, not as a separate field"


def test_codex_registration_replaces_then_adds_with_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _with_codex_at(monkeypatch, "C:/codex/codex.exe")
    prepared = make_plan("codex", profile="main", project_root=tmp_path, bridge=BRIDGE)

    assert prepared.registration.status == REGISTERED
    assert prepared.registration.name.startswith("tsunagou-main-")
    remove, add = prepared.steps
    assert remove.argv == ("C:/codex/codex.exe", "mcp", "remove", prepared.registration.name)
    assert remove.required is False, "nothing to remove is not a failure"
    assert add.required is True
    # The environment travels as --env pairs; empty values are dropped rather than
    # written as an empty variable the bridge would have to interpret.
    assert add.argv[:5] == ("C:/codex/codex.exe", "mcp", "add", prepared.registration.name, "--env")
    assert "TSUNAGOU_EMPTY=" not in " ".join(add.argv)
    assert "TSUNAGOU_TICKET_FILE=/project/.tsunagou/bridges/codex-main/ticket.json" in add.argv
    assert add.argv[-3:] == ("--", "node", "/checkout/packages/bridge-server/dist/server.js")


def test_a_host_without_a_command_is_unsupported_and_says_why() -> None:
    prepared = plan("claudecode", profile="main", project_root=Path("/p"), bridge=BRIDGE)

    assert prepared.status == UNSUPPORTED
    assert prepared.note, "an unsupported host must explain itself, not fail silently"
    assert prepared.commands == ()


def test_an_unknown_vendor_has_no_row_at_all() -> None:
    assert host_for("some-editor") is None
    assert plan("some-editor", profile="main", project_root=Path("/p"), bridge=BRIDGE).status == UNSUPPORTED


def test_a_host_whose_cli_is_missing_is_reported_not_attempted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _with_codex_at(monkeypatch, None)
    prepared = make_plan("codex", profile="main", project_root=tmp_path, bridge=BRIDGE)

    assert prepared.registration.status == EXECUTABLE_MISSING
    assert prepared.steps == ()


def test_only_planned_commands_are_run_and_a_required_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _with_codex_at(monkeypatch, "codex")
    ran: list[tuple[str, ...]] = []

    def failing(argv: tuple[str, ...], cwd: str | None = None) -> int:
        ran.append(argv)
        return 1

    result = register("codex", profile="main", project_root=tmp_path, bridge=BRIDGE, run=failing)

    assert result.status == FAILED
    assert len(ran) == 2, "the remove and the add both ran; only the add's failure counts"
    assert result.note


def test_a_best_effort_command_may_fail_without_failing_the_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _with_codex_at(monkeypatch, "codex")

    def only_remove_fails(argv: tuple[str, ...], cwd: str | None = None) -> int:
        return 1 if "remove" in argv else 0

    result = register("codex", profile="main", project_root=tmp_path, bridge=BRIDGE, run=only_remove_fails)

    assert result.status == REGISTERED


def test_the_server_name_is_stable_per_conversation_and_project(tmp_path: Path) -> None:
    here = server_name("codex", "main", tmp_path)
    assert here == server_name("codex", "main", tmp_path), "a retry must replace its own entry"
    assert here != server_name("codex", "worker", tmp_path)
    assert here != server_name("codex", "main", tmp_path / "other")
    chinese = server_name("codex", "主 Agent", tmp_path)
    assert chinese != server_name("codex", "子 Agent", tmp_path), (
        "two Chinese names must not become one entry"
    )
    assert chinese.startswith("tsunagou-Agent-")


def test_codex_finds_its_executable_the_way_the_host_hides_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    host = HOSTS["codex"]
    configured = tmp_path / "codex.exe"
    configured.write_text("", encoding="utf-8")

    assert find_executable(host, environ={"CODEX_CLI_PATH": str(configured)}) == str(configured)
    assert find_executable(host, environ={"CODEX_CLI_PATH": str(tmp_path / "gone.exe")}) is None


def test_taking_an_entry_back_out_uses_the_same_generated_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _with_codex_at(monkeypatch, "codex")
    ran: list[tuple[str, ...]] = []

    result = host_registration.unregister(
        "codex", profile="main", project_root=tmp_path,
        run=lambda argv, cwd=None: ran.append(argv) or 0,
    )

    assert result.status == host_registration.UNREGISTERED
    assert result.name == server_name("codex", "main", tmp_path)
    assert ran == [("codex", "mcp", "remove", result.name)]


def test_a_host_without_a_removal_command_says_the_config_may_stay_dirty(tmp_path: Path) -> None:
    result = host_registration.unregister("claudecode", profile="main", project_root=tmp_path)

    assert result.status == UNSUPPORTED
    assert result.note, "取不回来就要说清楚，不能让用户以为宿主配置干净了"


def test_removing_an_entry_without_the_host_cli_changes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _with_codex_at(monkeypatch, None)
    ran: list[tuple[str, ...]] = []

    result = host_registration.unregister(
        "codex", profile="main", project_root=tmp_path,
        run=lambda argv, cwd=None: ran.append(argv) or 0,
    )

    assert result.status == EXECUTABLE_MISSING
    assert ran == []


def test_the_report_is_the_command_as_text_for_a_person_to_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _with_codex_at(monkeypatch, "codex")
    prepared = plan("codex", profile="main", project_root=tmp_path, bridge=BRIDGE)

    report = prepared.public()

    assert report["status"] == REGISTERED
    assert report["commands"] and all(isinstance(item, str) for item in report["commands"])
    assert report["commands"][-1].startswith("codex mcp add ")
    assert "env" not in report, "the environment travels in the command, not as a separate field"
