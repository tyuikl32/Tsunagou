"""The console's memory of who works on each project.

The daemons are the authority; this module is about *when* the console bothers them,
because the rail asks for every project at once and agents join without ever passing
through the console.
"""

from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from tsunagou.console.agents import AgentDirectory, AgentRoster, attach, fingerprint, reconcile_vendors
from tsunagou.console.profile import load_profile, update_profile
from tsunagou.console.projects import ProjectEntry
from tsunagou.shared_kernel.digests import canonical_digest

PROJECT_ID = "0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b44"


def _project(tmp_path: Path, *, with_storage: bool = True) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "proj"
    state = root / ".tsunagou" / "local"
    state.mkdir(parents=True, exist_ok=True)
    if with_storage:
        (state / "state.sqlite3").write_bytes(b"SQLite format 3\x00")
    endpoint = {
        "url": "http://127.0.0.1:59999", "pid": 4321, "state_dir": str(state),
        "project_id": PROJECT_ID, "running": True,
    }
    return root, endpoint


class Reader:
    """Stands in for the daemon: counts asks, and can be told to stay silent."""

    def __init__(self, roster: AgentRoster | None) -> None:
        self.roster = roster
        self.calls = 0

    def __call__(self, root: Path, endpoint: dict[str, Any]) -> AgentRoster | None:
        self.calls += 1
        return self.roster


def _roster(main: str | None = "agent-main") -> AgentRoster:
    return AgentRoster(
        project_id=PROJECT_ID, main_agent_id=main,
        agents=({"agent_id": "agent-main", "status": "active", "role": "main"},
                {"agent_id": "agent-worker", "status": "active", "role": "worker"}),
        fetched_at="2026-09-28T00:00:00.000Z",
    )


def test_opening_a_project_reads_the_roster_once_and_reuses_it(tmp_path: Path) -> None:
    root, endpoint = _project(tmp_path)
    reader = Reader(_roster())
    directory = AgentDirectory(reader=reader)

    first = directory.roster(PROJECT_ID, root, endpoint)
    second = directory.roster(PROJECT_ID, root, endpoint)

    assert reader.calls == 1, "an unchanged daemon must not be asked again"
    assert first is not None and second is not None
    assert second.main_agent_id == "agent-main"
    assert [agent["agent_id"] for agent in second.agents] == ["agent-main", "agent-worker"]


def test_a_daemon_that_wrote_something_is_asked_again(tmp_path: Path) -> None:
    root, endpoint = _project(tmp_path)
    reader = Reader(_roster())
    directory = AgentDirectory(reader=reader)

    directory.roster(PROJECT_ID, root, endpoint)
    # An agent joining writes through the daemon's own storage: that is the signal,
    # because the join never talks to the console.
    with (root / ".tsunagou" / "local" / "state.sqlite3").open("ab") as handle:
        handle.write(b"\x00more pages")
    directory.roster(PROJECT_ID, root, endpoint)

    assert reader.calls == 2


def test_force_reads_again_without_any_change(tmp_path: Path) -> None:
    root, endpoint = _project(tmp_path)
    reader = Reader(_roster())
    directory = AgentDirectory(reader=reader)

    directory.roster(PROJECT_ID, root, endpoint)
    directory.roster(PROJECT_ID, root, endpoint, force=True)

    assert reader.calls == 2


def test_a_silent_daemon_keeps_the_names_it_answered_before(tmp_path: Path) -> None:
    root, endpoint = _project(tmp_path)
    reader = Reader(_roster())
    directory = AgentDirectory(reader=reader)
    directory.roster(PROJECT_ID, root, endpoint)

    reader.roster = None
    with (root / ".tsunagou" / "local" / "state.sqlite3").open("ab") as handle:
        handle.write(b"\x00")
    again = directory.roster(PROJECT_ID, root, endpoint)

    assert again is not None, "a failed re-read is not evidence that nobody works here"
    assert again.main_agent_id == "agent-main"


def test_a_daemon_that_never_answered_reports_unknown_not_empty(tmp_path: Path) -> None:
    root, endpoint = _project(tmp_path)
    directory = AgentDirectory(reader=Reader(None))

    assert directory.roster(PROJECT_ID, root, endpoint) is None


def test_unreadable_storage_never_pins_a_roster(tmp_path: Path) -> None:
    root, endpoint = _project(tmp_path, with_storage=False)
    reader = Reader(_roster())
    directory = AgentDirectory(reader=reader)

    assert fingerprint(root, endpoint) is None
    directory.roster(PROJECT_ID, root, endpoint)
    directory.roster(PROJECT_ID, root, endpoint)

    assert reader.calls == 2, "without a fingerprint every read has to be a fresh ask"


def test_a_project_without_a_running_daemon_is_not_asked(tmp_path: Path) -> None:
    root, endpoint = _project(tmp_path)
    reader = Reader(_roster())
    directory = AgentDirectory(reader=reader)

    assert directory.roster(PROJECT_ID, root, None) is None
    assert directory.roster(PROJECT_ID, root, {**endpoint, "running": False}) is None
    assert reader.calls == 0


def test_attach_leaves_the_fields_unset_when_the_roster_is_unknown(tmp_path: Path) -> None:
    root, endpoint = _project(tmp_path)
    entry = ProjectEntry(project_id=PROJECT_ID, path=root, daemon=endpoint)

    attach(entry, AgentDirectory(reader=Reader(None)))
    assert entry.agents is None, "'cannot say' must not travel as 'no agents'"
    assert entry.public()["agents"] is None

    attach(entry, AgentDirectory(reader=Reader(_roster())))
    assert entry.public()["main_agent_id"] == "agent-main"
    assert len(entry.public()["agents"] or []) == 2


def test_reading_a_daemon_parses_its_answer_without_a_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, endpoint = _project(tmp_path)
    seen: dict[str, Any] = {}

    class Answer(io.BytesIO):
        status = 200

        def __enter__(self) -> Answer:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None) -> Answer:
        seen["url"] = request.full_url
        seen["authorization"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        body = json.dumps({
            "items": [
                {"agent_id": "agent-main", "status": "active", "role": "main", "conversation_digest": "sha256:x"},
                {"agent_id": "agent-worker", "status": "provisioning", "role": "worker"},
                "not-an-object",
                {"status": "active"},
            ],
            "main_agent_id": "agent-main",
            "authority_epoch": 3,
        }).encode("utf-8")
        return Answer(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    roster = AgentDirectory().roster(PROJECT_ID, root, endpoint)

    assert roster is not None
    assert seen["url"] == f"http://127.0.0.1:59999/api/v1/projects/{PROJECT_ID}/agents"
    assert seen["authorization"] is None, "the agents exit needs no control token"
    assert roster.main_agent_id == "agent-main"
    assert roster.agents == (
        {"agent_id": "agent-main", "status": "active", "role": "main", "conversation_digest": "sha256:x"},
        {"agent_id": "agent-worker", "status": "provisioning", "role": "worker", "conversation_digest": ""},
    )


def _bridge(root: Path, name: str, files: dict[str, dict[str, Any]]) -> Path:
    """A bridge folder as the command line would have left it behind."""

    directory = root / ".tsunagou" / "bridges" / name
    directory.mkdir(parents=True, exist_ok=True)
    for file_name, payload in files.items():
        (directory / file_name).write_text(json.dumps(payload), encoding="utf-8")
    return directory


def test_vendor_of_a_cli_enrolled_agent_is_filled_from_its_bridge_folder(tmp_path: Path) -> None:
    """``agent connect`` never writes the profile; the proof is the folder it left."""

    root, _ = _project(tmp_path)
    _bridge(root, "codex-1a2b3c", {"connection.json": {
        "adapter": "codex", "profile": "1a2b3c", "agent_id": "agent-main",
    }})
    profile_path = tmp_path / "console-profile.json"

    filled = reconcile_vendors(
        root, ({"agent_id": "agent-main"}, {"agent_id": "agent-worker"}), profile_path=profile_path,
    )

    assert filled == 1
    assert load_profile(profile_path)["agents"] == {"agent-main": {"vendor": "Codex"}}, \
        "only the vendor is recorded — a nickname keeps falling back to the Agent code"


def test_a_bridge_without_a_connection_is_matched_by_its_conversation_digest(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    conversation = "tsunagou:deepseek:main:0f0f0f"
    _bridge(root, "deepseek-0f0f0f", {"host-identity.json": {
        "adapter": "deepseek", "profile": "main", "conversation_id": conversation,
    }})
    profile_path = tmp_path / "console-profile.json"
    agents = ({"agent_id": "agent-worker", "conversation_digest": canonical_digest(
        {"conversation_id": conversation},
    )},)

    assert reconcile_vendors(root, agents, profile_path=profile_path) == 1
    assert load_profile(profile_path)["agents"] == {"agent-worker": {"vendor": "DeepSeek Harness"}}


def test_a_vendor_somebody_already_set_is_never_rewritten(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    _bridge(root, "codex-1a2b3c", {"connection.json": {"adapter": "codex", "agent_id": "agent-main"}})
    profile_path = tmp_path / "console-profile.json"
    update_profile(profile_path, {"agents": {"agent-main": {"nickname": "熊猫", "vendor": "OpenCode"}}})

    assert reconcile_vendors(root, ({"agent_id": "agent-main"},), profile_path=profile_path) == 0
    assert load_profile(profile_path)["agents"]["agent-main"] == {"nickname": "熊猫", "vendor": "OpenCode"}


def test_a_conversation_we_cannot_identify_is_left_alone(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    _bridge(root, "mystery-1a2b3c", {"bridge-config.json": {"command": "node"}})
    profile_path = tmp_path / "console-profile.json"

    assert reconcile_vendors(root, ({"agent_id": "agent-main"},), profile_path=profile_path) == 0
    assert not profile_path.exists(), "nothing provable means no write at all"


def test_reading_a_roster_fills_vendors_when_a_profile_path_is_given(tmp_path: Path) -> None:
    """The fill-in hangs off the read path, because the bridge folder appears later."""

    root, endpoint = _project(tmp_path)
    _bridge(root, "codex-1a2b3c", {"connection.json": {"adapter": "codex", "agent_id": "agent-main"}})
    profile_path = tmp_path / "console-profile.json"
    directory = AgentDirectory(reader=Reader(_roster()), profile_path=profile_path)

    assert directory.roster(PROJECT_ID, root, endpoint) is not None

    assert load_profile(profile_path)["agents"] == {"agent-main": {"vendor": "Codex"}}
    # 第二次读（此时名册已在缓存里）不再改档案：值已经有了。
    before = profile_path.read_text(encoding="utf-8")
    assert directory.roster(PROJECT_ID, root, endpoint) is not None
    assert profile_path.read_text(encoding="utf-8") == before
