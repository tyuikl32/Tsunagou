"""The relay: the browser asks the console, the console asks the daemon.

A stub daemon stands in for the real one so the test can look at what actually
arrived, which is the only way to prove the control token is added on the server
side and that the daemon's own answer travels back untouched.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import Request

from tsunagou.console.app import create_console_app
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.errors import ConsoleError
from tsunagou.console.projects import ensure_daemon, find
from tsunagou.console.proxy import ensure_matching_project, forward, project_token
from tsunagou.modules.projects import ProjectRegistry

CONTROL_SENTINEL = "control-sentinel"


@dataclass(frozen=True)
class _Received:
    command: str
    path: str
    headers: dict[str, str]
    body: bytes


class _StubDaemon:
    """A daemon-shaped server: it records what it received and answers JSON."""

    def __init__(self) -> None:
        self.requests: list[_Received] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    @property
    def last_request(self) -> _Received:
        return self.requests[-1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 - http.server's naming
                stub._answer(self)

            def do_POST(self) -> None:  # noqa: N802 - http.server's naming
                stub._answer(self)

            def log_message(self, *args: object) -> None:
                pass

        return Handler

    def _answer(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length") or 0)
        body = handler.rfile.read(length) if length else b""
        self.requests.append(_Received(handler.command, handler.path, dict(handler.headers), body))
        path = urllib.parse.urlparse(handler.path).path
        if path.endswith("/boom"):
            status, payload = 400, {"detail": {"code": "boom"}}
        elif path.endswith("/cognition"):
            status, payload = 403, {"detail": {"code": "forbidden"}}
        elif path.endswith("/health"):
            status, payload = 200, {"status": "ok"}
        else:
            status, payload = 200, {"items": []}
        blob = json.dumps(payload).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(blob)))
        handler.end_headers()
        handler.wfile.write(blob)


@pytest.fixture
def stub() -> Iterator[_StubDaemon]:
    daemon = _StubDaemon()
    try:
        yield daemon
    finally:
        daemon.close()


def _config(tmp_path: Path) -> ConsoleConfig:
    return ConsoleConfig(
        projects_root=tmp_path / "projects",
        scan_roots=[tmp_path],
        index_path=tmp_path / "index.json",
        profile_path=tmp_path / "profile.json",
    )


def _project(tmp_path: Path, stub: _StubDaemon | None = None) -> tuple[Path, str]:
    """A real project, plus a daemon that claims to serve it when asked."""

    root = tmp_path / "project"
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    registry = ProjectRegistry.initialize(root, name="relay", objective="reach the daemon")
    assert registry.project is not None
    project_id = registry.project.project_id
    if stub is not None:
        state_dir = root / ".tsunagou" / "local"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "control.token").write_text(CONTROL_SENTINEL, encoding="utf-8")
        (state_dir / "endpoint.json").write_text(json.dumps({
            "url": stub.url, "pid": os.getpid(), "project_id": project_id, "state_dir": str(state_dir),
        }), encoding="utf-8")
    return root, project_id


def _request(method: str, *, query: str = "", headers: dict[str, str] | None = None, body: bytes = b"") -> Request:
    scope = {
        "type": "http", "method": method, "path": "/", "raw_path": b"/", "scheme": "http",
        "query_string": query.encode("utf-8"), "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 1),
        "headers": [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()],
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def _endpoint(app: Any, path: str, method: str | None = None) -> Any:
    """The handler for one route; a path can hold more than one (GET and PUT)."""

    for route in app.routes:
        if getattr(route, "path", "") != path:
            continue
        if method is None or method in (getattr(route, "methods", None) or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_the_console_owns_its_routes_before_the_two_relays(tmp_path: Path) -> None:
    paths = [getattr(route, "path", "") for route in create_console_app(_config(tmp_path)).routes]

    assert paths.index("/api/v1/projects") < paths.index("/api/v1/projects/{project_id}/{rest:path}")
    assert paths.index("/api/v1/projects/{project_id}/{rest:path}") < paths.index("/api/v1/{rest:path}")
    assert paths.index("/api/v1/console/profile") < paths.index("/api/v1/{rest:path}")


def test_the_token_is_read_from_the_state_dir_the_daemon_reported(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "control.token").write_text("from-endpoint", encoding="utf-8")
    assert project_token(root, {"state_dir": str(elsewhere)}) == "from-endpoint"
    assert project_token(root, None) is None

    local = root / ".tsunagou" / "local"
    local.mkdir(parents=True, exist_ok=True)
    (local / "control.token").write_text("from-project", encoding="utf-8")
    assert project_token(root, None) == "from-project"


def test_a_daemon_serving_another_project_is_refused() -> None:
    with pytest.raises(ConsoleError) as refusal:
        ensure_matching_project({"project_id": "other"}, "wanted")
    assert refusal.value.code == "daemon_project_mismatch"
    assert refusal.value.status == 409


def test_forwarding_adds_the_token_and_keeps_the_daemon_answer(tmp_path: Path, stub: _StubDaemon) -> None:
    root, project_id = _project(tmp_path, stub)
    app = create_console_app(_config(tmp_path))
    relay = _endpoint(app, "/api/v1/projects/{project_id}/{rest:path}")

    response = asyncio.run(relay(project_id, "tasks", _request("GET", query="limit=5")))

    assert response.status_code == 200
    assert json.loads(response.body) == {"items": []}
    assert stub.last_request.path == f"/api/v1/projects/{project_id}/tasks?limit=5"
    assert stub.last_request.headers["Authorization"] == f"Bearer {CONTROL_SENTINEL}"


def test_a_daemon_refusal_travels_back_verbatim(tmp_path: Path, stub: _StubDaemon) -> None:
    _, project_id = _project(tmp_path, stub)
    app = create_console_app(_config(tmp_path))
    relay = _endpoint(app, "/api/v1/projects/{project_id}/{rest:path}")

    response = asyncio.run(relay(project_id, "boom", _request("GET")))

    assert response.status_code == 400
    assert json.loads(response.body) == {"detail": {"code": "boom"}}


def test_a_command_needs_a_project_and_carries_its_body(tmp_path: Path, stub: _StubDaemon) -> None:
    _, project_id = _project(tmp_path, stub)
    app = create_console_app(_config(tmp_path))
    command = _endpoint(app, "/api/v1/commands/{command_kind}")

    response = asyncio.run(command(
        "task.ready", _request("POST", headers={"Tsunagou-Project": project_id}, body=b'{"task_id":"t"}'),
    ))

    assert response.status_code == 200
    assert stub.last_request.path == "/api/v1/commands/task.ready"
    assert stub.last_request.body == b'{"task_id":"t"}'
    assert stub.last_request.headers["Authorization"] == f"Bearer {CONTROL_SENTINEL}"

    with pytest.raises(ConsoleError) as refusal:
        asyncio.run(command("task.ready", _request("POST", body=b"{}")))
    assert refusal.value.code == "project_not_selected"


def test_a_project_without_a_daemon_says_so_instead_of_hanging(tmp_path: Path) -> None:
    root, project_id = _project(tmp_path)
    config = _config(tmp_path)
    entry = find(config, project_id)
    assert entry.available is True
    with pytest.raises(ConsoleError) as refusal:
        ensure_daemon(entry, autostart=False)
    assert refusal.value.code == "daemon_not_running"
    assert refusal.value.status == 503
    assert refusal.value.detail["path"] == root.resolve().as_posix()


def test_forwarding_an_unsupported_method_is_refused() -> None:
    with pytest.raises(ConsoleError) as refusal:
        forward(endpoint={"url": "http://127.0.0.1:1"}, method="TRACE", path="/api/v1/health")
    assert refusal.value.code == "method_not_allowed"


def test_a_view_gathers_several_exits_and_reports_the_one_that_refused(
    tmp_path: Path, stub: _StubDaemon,
) -> None:
    _, project_id = _project(tmp_path, stub)
    app = create_console_app(_config(tmp_path))
    view = _endpoint(app, "/api/v1/console/views/{view}")

    answer = asyncio.run(view("audit", _request("GET", headers={"Tsunagou-Project": project_id})))

    assert answer["view"] == "audit"
    assert sorted(answer["sources"]) == ["agents", "intents", "resources"]
    assert answer["missing"] == {}
    asked = [record.path for record in stub.requests if "/projects/" in record.path]
    assert asked == [
        f"/api/v1/projects/{project_id}/intents",
        f"/api/v1/projects/{project_id}/resources",
        f"/api/v1/projects/{project_id}/agents",
    ]

    # 租约冲突账本跟「冲突与协商」一屏走，不和审计一屏混在一起。
    collaboration = asyncio.run(view("collaboration", _request("GET", headers={"Tsunagou-Project": project_id})))
    assert sorted(collaboration["sources"]) == ["agents", "conflicts", "contracts", "messages"]
    assert collaboration["missing"]["cognition"] == {"status": 403, "code": "forbidden"}

    # 「任务区」一屏要凑齐开工条件（认知报告 / 契约 / 工作空间 / 租约）与改动范围，
    # 所以要拖七个出口；中间层只搬运，怎么对到任务上是页面的事。
    tasks = asyncio.run(view("tasks", _request("GET", headers={"Tsunagou-Project": project_id})))
    assert sorted(tasks["sources"]) == [
        "agents", "attempts", "contracts", "resources", "results", "tasks", "workspaces",
    ]
    assert tasks["missing"]["cognition"] == {"status": 403, "code": "forbidden"}

    # `decisions` 不挂项目（daemon 那边是 `/api/v1/decisions`），所以取法不能一律
    # 拼项目前缀 —— 拼错的后果不是 500，而是 404，看上去像"这个项目没有待决定的事"。
    before = len(stub.requests)
    acceptance = asyncio.run(view("acceptance", _request("GET", headers={"Tsunagou-Project": project_id})))
    assert sorted(acceptance["sources"]) == ["agents", "decisions", "overview", "results", "reviews", "tasks"]
    assert acceptance["missing"] == {}
    probed = [record.path for record in stub.requests[before:]]
    assert "/api/v1/decisions" in probed
    assert f"/api/v1/projects/{project_id}/decisions" not in probed

    # 主视图那一节（「待用户决定」）读的也是 decisions，所以它同样要带上。
    overview = asyncio.run(view("overview", _request("GET", headers={"Tsunagou-Project": project_id})))
    assert sorted(overview["sources"]) == [
        "agents", "checkpoints", "decisions", "overview", "tasks",
    ]
    assert overview["missing"]["cognition"] == {"status": 403, "code": "forbidden"}

    with pytest.raises(ConsoleError) as refusal:
        asyncio.run(view("nothing-like-this", _request("GET", headers={"Tsunagou-Project": project_id})))
    assert refusal.value.code == "console_view_unknown"
    assert refusal.value.status == 404


def test_the_console_reports_its_own_config_and_stores_the_profile(tmp_path: Path) -> None:
    config = _config(tmp_path)
    app = create_console_app(config)

    reported = _endpoint(app, "/api/v1/console/config")()
    assert reported["console"] is True
    # No demo switch survives: the page has exactly one source of data.
    assert "demo" not in reported
    assert "mode" not in reported
    assert _endpoint(app, "/api/v1/console/profile", "GET")()["agents"] == {}
    stored = _endpoint(app, "/api/v1/console/profile", "PUT")({
        "nickname": "我", "theme": "dark", "agents": {"a-1": {"nickname": "熊猫", "vendor": "codex"}},
    })
    assert stored["agents"]["a-1"] == {"nickname": "熊猫", "vendor": "codex"}
    # A later screen that only knows the theme must not erase the agent names.
    merged = _endpoint(app, "/api/v1/console/profile", "PUT")({"theme": "light"})
    assert merged["theme"] == "light"
    assert merged["agents"]["a-1"]["nickname"] == "熊猫"
