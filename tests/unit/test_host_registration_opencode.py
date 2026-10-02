"""OpenCode's entry lives in the project's own config, and the host's CLI writes it.

Two measured host facts fix this row's shape (OpenCode v2.0.21):

* ``opencode mcp add`` exists and re-adding the same name replaces that entry — so a
  retry is idempotent and no removal has to run first;
* there is no ``mcp remove``, so taking a cancelled enrollment out is a file edit; and
  ``add`` writes the ``opencode.json`` of the *current directory*, so the command has to
  run inside the project (a bridge written into the wrong file is never launched).

The tests pin both halves: the planned command (including its working directory), and
that the file edit touches only the entry named after this conversation and launching
our bridge — everything else in the person's file survives, and a file we cannot parse
is left alone whole.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tsunagou.platform.bridge_files import bridge_entry_path
from tsunagou.platform.host_registration import (
    EXECUTABLE_MISSING,
    FAILED,
    REGISTERED,
    UNREGISTERED,
    host_for,
    make_plan,
    opencode_config_path,
    plan,
    register,
    server_name,
    unregister,
)

PROJECT = Path("/project")


def _bridge(project_root: Path = PROJECT, **extra: Any) -> dict[str, Any]:
    state = project_root / ".tsunagou" / "bridges" / "opencode-main"
    return {
        "adapter": "opencode",
        "mode": "attach",
        "command": "node",
        "args": [str(bridge_entry_path())],
        "env": {
            "TSUNAGOU_HTTP_URL": "http://127.0.0.1:5000",
            "TSUNAGOU_PROJECT_ROOT": str(project_root),
            "TSUNAGOU_STATE_DIR": str(state),
            "TSUNAGOU_TICKET_FILE": str(state / "ticket.json"),
            "TSUNAGOU_HOST_META_KEY": "ai.opencode/sessionID",
            "TSUNAGOU_EMPTY": "",
            **extra,
        },
    }


def _ours() -> dict[str, Any]:
    """An entry that is ours by the bridge it launches."""

    return {"type": "local", "command": ["node", str(bridge_entry_path())],
            "environment": {"TSUNAGOU_HTTP_URL": "http://127.0.0.1:5000"}}


def _theirs() -> dict[str, Any]:
    """Someone's own MCP server, under a name we would never pick."""

    return {"type": "local", "command": ["node", "/somewhere/else/server.js"],
            "environment": {"THEIR_TOKEN": "x"}}


def _write_config(root: Path, servers: dict[str, Any], **rest: Any) -> Path:
    path = opencode_config_path(root)
    path.write_text(json.dumps({"model": "keep-me", "mcp": {"servers": servers}, **rest},
                               indent=2) + "\n", encoding="utf-8")
    return path


def test_opencode_is_no_longer_an_unsupported_row() -> None:
    host = host_for("opencode")

    assert host is not None
    assert host.commands is not None, "the host's own CLI does the adding"
    assert host.config_preview is not None, "ownership is decided before anything runs"
    assert host.config_remove is not None, "the CLI cannot remove, so the file edit does"
    assert host.note == "", "a supported host has nothing to apologise for"


def test_the_plan_adds_one_entry_inside_the_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("tsunagou.platform.host_registration.find_executable", lambda host, **_: "opencode")
    prepared = make_plan("opencode", profile="main", project_root=tmp_path, bridge=_bridge(tmp_path))

    assert prepared.registration.status == REGISTERED
    assert prepared.registration.name == server_name("opencode", "main", tmp_path)
    (step,) = prepared.steps
    assert step.argv[:4] == ("opencode", "mcp", "add", prepared.registration.name)
    assert step.argv[-2:] == ("node", str(bridge_entry_path()))
    assert step.cwd == str(tmp_path), "add writes the current directory's file, not the repository's"
    assert "--env" in step.argv and "TSUNAGOU_EMPTY=" not in " ".join(step.argv)
    assert "TSUNAGOU_HOST_META_KEY=ai.opencode/sessionID" in step.argv
    assert len(prepared.steps) == 1, "re-adding replaces the entry, so nothing is removed first"


def test_registration_runs_the_host_cli_in_the_project_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr("tsunagou.platform.host_registration.find_executable",
                        lambda host, **_: "opencode")
    ran: list[tuple[tuple[str, ...], str | None]] = []

    result = register("opencode", profile="main", project_root=tmp_path, bridge=_bridge(tmp_path),
                      run=lambda argv, cwd=None: ran.append((argv, cwd)) or 0)

    assert result.status == REGISTERED
    assert len(ran) == 1
    assert ran[0][1] == str(tmp_path)


def test_a_missing_cli_is_reported_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr("tsunagou.platform.host_registration.find_executable", lambda host, **_: None)
    ran: list[tuple[str, ...]] = []

    result = register("opencode", profile="main", project_root=tmp_path, bridge=_bridge(tmp_path),
                      run=lambda argv, cwd=None: ran.append(argv) or 0)

    assert result.status == EXECUTABLE_MISSING
    assert ran == []
    assert not opencode_config_path(tmp_path).exists()


def test_a_same_named_entry_we_did_not_write_is_never_replaced(tmp_path: Path) -> None:
    """The person may have their own MCP server under a name that looks like ours."""

    name = server_name("opencode", "main", tmp_path)
    path = _write_config(tmp_path, {name: _theirs()})
    before = path.read_text(encoding="utf-8")

    decision = plan("opencode", profile="main", project_root=tmp_path, bridge=_bridge(tmp_path))

    assert decision.status == FAILED
    assert "不是 Tsunagou 写的" in decision.note
    assert path.read_text(encoding="utf-8") == before, "a refused registration writes nothing"


def test_our_own_entry_from_an_earlier_attempt_may_be_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr("tsunagou.platform.host_registration.find_executable", lambda host, **_: "opencode")
    name = server_name("opencode", "main", tmp_path)
    _write_config(tmp_path, {name: _ours(), "their-server": _theirs()})

    prepared = make_plan("opencode", profile="main", project_root=tmp_path, bridge=_bridge(tmp_path))

    assert prepared.registration.status == REGISTERED
    assert len(prepared.steps) == 1


def test_removing_takes_only_our_entry_out(tmp_path: Path) -> None:
    name = server_name("opencode", "main", tmp_path)
    path = _write_config(tmp_path, {name: _ours(), "their-server": _theirs()})

    result = unregister("opencode", profile="main", project_root=tmp_path)

    assert result.status == UNREGISTERED
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert name not in stored["mcp"]["servers"]
    assert stored["mcp"]["servers"]["their-server"] == _theirs(), "their entry is untouched"
    assert stored["model"] == "keep-me", "keys we know nothing about survive the rewrite"


def test_removing_refuses_a_same_named_entry_that_is_not_ours(tmp_path: Path) -> None:
    name = server_name("opencode", "main", tmp_path)
    path = _write_config(tmp_path, {name: _theirs()})
    before = path.read_text(encoding="utf-8")

    result = unregister("opencode", profile="main", project_root=tmp_path)

    assert result.status == UNREGISTERED
    assert "同名条目" in result.note, "it says what it deliberately left behind"
    assert path.read_text(encoding="utf-8") == before, "nothing was rewritten"


def test_a_config_file_that_does_not_parse_is_left_alone_whole(tmp_path: Path) -> None:
    path = opencode_config_path(tmp_path)
    path.write_text("{ this is not json", encoding="utf-8")

    result = unregister("opencode", profile="main", project_root=tmp_path)

    assert "一个字都没改" in result.note
    assert path.read_text(encoding="utf-8") == "{ this is not json"


def test_no_config_file_is_not_an_error(tmp_path: Path) -> None:
    result = unregister("opencode", profile="main", project_root=tmp_path)

    assert result.status == UNREGISTERED
    assert not opencode_config_path(tmp_path).exists(), "removal does not create the file"


def test_forgetting_the_project_removes_every_entry_of_ours(tmp_path: Path) -> None:
    main = server_name("opencode", "main", tmp_path)
    worker = server_name("opencode", "Agent-abc", tmp_path)
    path = _write_config(tmp_path, {main: _ours(), worker: _ours(), "their-server": _theirs()})

    result = unregister("opencode", profile="main", project_root=tmp_path, all_registrations=True)

    assert result.status == UNREGISTERED
    servers = json.loads(path.read_text(encoding="utf-8"))["mcp"]["servers"]
    assert set(servers) == {"their-server"}
