"""The one question no daemon can answer: who works *where*.

A daemon serves a single project, so "every agent on this machine, and the project
each one works in" is assembled by the console. Two things matter here: an agent that
works in two projects must appear twice (the row is a pairing, not an identity), and
the "what is it doing now" column costs extra daemon calls, so it is read on demand
and left empty — never guessed — when it cannot be read.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from tsunagou.console.agents import AgentDirectory, AgentRoster, current_tasks, gather
from tsunagou.console.app import create_console_app
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.projects import ProjectEntry

PROJECT_A = "0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b44"
PROJECT_B = "0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b55"


def _entry(tmp_path: Path, name: str, project_id: str, agent_ids: tuple[str, ...]) -> ProjectEntry:
    root = tmp_path / name
    (root / ".tsunagou" / "local").mkdir(parents=True, exist_ok=True)
    (root / ".tsunagou" / "local" / "state.sqlite3").write_bytes(b"SQLite format 3\x00")
    return ProjectEntry(
        project_id=project_id, path=root, name=name,
        daemon={
            "url": "http://127.0.0.1:59999", "pid": 1, "project_id": project_id,
            "state_dir": str(root / ".tsunagou" / "local"), "running": True,
        },
    )


def _roster(project_id: str, agent_ids: tuple[str, ...]) -> AgentRoster:
    return AgentRoster(
        project_id=project_id, main_agent_id=agent_ids[0],
        agents=tuple(
            {"agent_id": agent_id, "status": "active", "role": "main" if index == 0 else "worker"}
            for index, agent_id in enumerate(agent_ids)
        ),
        fetched_at="2026-09-28T00:00:00.000Z",
    )


class Directory(AgentDirectory):
    """A roster memory that answers from a table instead of from daemons."""

    def __init__(self, table: dict[str, AgentRoster | None]) -> None:
        super().__init__(reader=lambda root, endpoint: None)
        self.table = table

    def roster(
        self, project_id: str, root: Path, endpoint: dict[str, Any] | None, *, force: bool = False,
    ) -> AgentRoster | None:
        return self.table.get(project_id)


def test_every_agent_appears_once_per_project_it_works_in(tmp_path: Path) -> None:
    shared = "agent-scout"
    entries = [
        _entry(tmp_path, "alpha", PROJECT_A, (shared, "agent-a1")),
        _entry(tmp_path, "beta", PROJECT_B, (shared,)),
    ]
    directory = Directory({
        PROJECT_A: _roster(PROJECT_A, (shared, "agent-a1")),
        PROJECT_B: _roster(PROJECT_B, (shared,)),
    })

    rows = gather(entries, directory)["items"]

    by_project = {(row["project_id"], row["agent_id"]): row for row in rows}
    assert len(rows) == 3
    assert set(by_project) == {
        (PROJECT_A, shared), (PROJECT_A, "agent-a1"), (PROJECT_B, shared),
    }, "one row per pairing: the same agent in two projects is two rows"
    assert by_project[(PROJECT_A, shared)]["project_name"] == "alpha"
    assert by_project[(PROJECT_B, shared)]["project_name"] == "beta"
    assert by_project[(PROJECT_A, shared)]["role"] == "main"
    assert by_project[(PROJECT_A, "agent-a1")]["role"] == "worker"


def test_a_project_whose_daemon_did_not_answer_is_named_not_hidden(tmp_path: Path) -> None:
    entries = [
        _entry(tmp_path, "alpha", PROJECT_A, ("agent-a1",)),
        _entry(tmp_path, "beta", PROJECT_B, ("agent-b1",)),
    ]
    directory = Directory({PROJECT_A: _roster(PROJECT_A, ("agent-a1",)), PROJECT_B: None})

    answer = gather(entries, directory)

    assert [row["project_id"] for row in answer["items"]] == [PROJECT_A]
    assert answer["unreadable"] == [PROJECT_B]


def test_a_project_without_a_daemon_is_not_called_unreadable(tmp_path: Path) -> None:
    entry = _entry(tmp_path, "alpha", PROJECT_A, ("agent-a1",))
    entry.daemon = None

    answer = gather([entry], Directory({}))

    assert answer["items"] == []
    assert answer["unreadable"] == [], "no daemon is 'not running', not 'failed to answer'"


def test_the_job_column_is_filled_from_an_attempt_only_when_it_is_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "alpha"
    endpoint: dict[str, Any] = {"url": "http://127.0.0.1:59999", "project_id": PROJECT_A, "running": True}
    answers = {
        f"/api/v1/projects/{PROJECT_A}/attempts": {
            "items": [
                {"attempt_id": "t1", "task_id": "task-open", "owner_agent_id": "agent-a1", "status": "running"},
                {"attempt_id": "t2", "task_id": "task-done", "owner_agent_id": "agent-a2", "status": "completed"},
                {"attempt_id": "t3", "task_id": "task-blocked", "owner_agent_id": "agent-a1", "status": "blocked"},
                {"attempt_id": "t4", "task_id": "task-missing", "owner_agent_id": "agent-a3", "status": "claimed"},
            ],
        },
        f"/api/v1/projects/{PROJECT_A}/tasks": {
            "items": [
                {"task_id": "task-open", "title": "打开的任务"},
                {"task_id": "task-done", "title": "已完成的任务"},
                {"task_id": "task-blocked", "title": "受阻的任务"},
            ],
        },
    }
    asked: list[str] = []

    class Answer(io.BytesIO):
        status = 200

        def __enter__(self) -> Answer:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None) -> Answer:
        path = urllib.parse.urlsplit(request.full_url).path
        asked.append(path)
        return Answer(json.dumps(answers.get(path, {})).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    assert current_tasks(root, endpoint) == {"agent-a1": "打开的任务"}, (
        "a finished attempt is not 'what it is doing now', and the first open one wins"
    )
    assert asked == [
        f"/api/v1/projects/{PROJECT_A}/attempts",
        f"/api/v1/projects/{PROJECT_A}/tasks",
    ]


def test_an_unreadable_task_exit_leaves_the_column_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    endpoint = {"url": "http://127.0.0.1:59999", "project_id": PROJECT_A, "running": True}

    def exploding_urlopen(request: urllib.request.Request, timeout: float | None = None) -> Any:
        raise urllib.error.URLError("no answer")

    monkeypatch.setattr(urllib.request, "urlopen", exploding_urlopen)

    assert current_tasks(tmp_path, endpoint) == {}, "unknown is empty, never a guess"
    assert current_tasks(tmp_path, None) == {}
    assert current_tasks(tmp_path, {**endpoint, "running": False}) == {}


def test_the_console_serves_the_agent_window_from_one_route(tmp_path: Path) -> None:
    """The window fetches one path; if this route disappears the list silently empties."""

    config = ConsoleConfig(
        projects_root=tmp_path / "projects",
        scan_roots=[tmp_path],
        index_path=tmp_path / "index.json",
        profile_path=tmp_path / "profile.json",
    )
    routes = {
        getattr(route, "path", ""): getattr(route, "endpoint", None)
        for route in create_console_app(config).routes
    }

    answer = routes["/api/v1/console/agents"]()

    assert answer["items"] == []
    assert answer["unreadable"] == []
    assert answer["fetched_at"], "the page says when the list was read"
