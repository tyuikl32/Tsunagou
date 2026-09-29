"""Preparing one host conversation to become an Agent (the console's local half).

The daemon issues the ticket; the console writes the private ticket file, describes how
to launch the bridge, and registers that description inside the host. Two things must
hold whatever else changes:

* **the ticket's secret never reaches the caller** — it goes into a private file, and
  the answer carries paths and statuses;
* **a host we cannot register is refused before a ticket exists**, so a refusal never
  leaves a live credential behind.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tsunagou.console import enrollment
from tsunagou.console.agents import AgentRoster
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.errors import ConsoleError
from tsunagou.console.profile import load_profile
from tsunagou.console.projects import ProjectEntry
from tsunagou.console.proxy import ForwardResponse
from tsunagou.platform import host_registration
from tsunagou.platform.host_registration import REGISTERED, UNSUPPORTED

PROJECT_ID = "0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b44"
SECRET = "s3cret-ticket-value"


@pytest.fixture(autouse=True)
def _no_leftover_enrollments() -> Any:
    enrollment.forget_all()
    yield
    enrollment.forget_all()


def _config(tmp_path: Path) -> ConsoleConfig:
    return ConsoleConfig(
        projects_root=tmp_path / "projects", scan_roots=[tmp_path],
        index_path=tmp_path / "index.json", profile_path=tmp_path / "profile.json",
    )


def _discoverable(tmp_path: Path) -> Path:
    """A project the console can find on disk, without git and without a daemon."""

    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / ".tsunagou" / "local").mkdir(parents=True, exist_ok=True)
    (root / ".tsunagou" / "project.json").write_text(
        json.dumps({"project_id": PROJECT_ID, "name": "probe"}), encoding="utf-8",
    )
    (root / ".tsunagou" / "local" / "endpoint.json").write_text(
        json.dumps({"url": "http://127.0.0.1:59999", "pid": 1, "project_id": PROJECT_ID}),
        encoding="utf-8",
    )
    return root


def _entry(tmp_path: Path) -> ProjectEntry:
    root = _discoverable(tmp_path)
    return ProjectEntry(
        project_id=PROJECT_ID, path=root, name="probe",
        daemon={
            "url": "http://127.0.0.1:59999", "pid": 1, "project_id": PROJECT_ID,
            "state_dir": str(root / ".tsunagou" / "local"), "running": True,
        },
    )


class Rosters:
    """The console's roster memory, told what to answer."""

    def __init__(self, agent_ids: tuple[str, ...] = ()) -> None:
        self.agent_ids = agent_ids

    def roster(self, project_id: str, root: Path, endpoint: dict[str, Any] | None, *, force: bool = False) -> AgentRoster | None:
        return AgentRoster(
            project_id=project_id, main_agent_id=self.agent_ids[0] if self.agent_ids else None,
            agents=tuple(
                {"agent_id": agent_id, "status": "active", "role": "worker"}
                for agent_id in self.agent_ids
            ),
            fetched_at="2026-09-28T00:00:00.000Z",
        )


class Daemon:
    """Stands in for the project's daemon: answers the ticket call, records the rest."""

    def __init__(self, status: int = 200, result: dict[str, Any] | None = None) -> None:
        self.status = status
        self.result = result if result is not None else {"secret": SECRET, "delivery_ref": "ref-1"}
        self.calls: list[str] = []

    def __call__(self, **request: Any) -> ForwardResponse:
        self.calls.append(str(request.get("path")))
        if self.status != 200:
            body = json.dumps({"detail": {"code": "unknown_payload_field"}}).encode("utf-8")
            return ForwardResponse(status=self.status, body=body, content_type="application/json")
        return ForwardResponse(
            status=200, body=json.dumps({"result": self.result}).encode("utf-8"),
            content_type="application/json",
        )


def _registered(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Register without running a real host CLI, and record what would have run."""

    recorded: list[dict[str, Any]] = []

    def fake_register(adapter: str, *, profile: str, project_root: Path, bridge: dict[str, Any], **_: Any) -> Any:
        recorded.append({"adapter": adapter, "profile": profile, "bridge": bridge})
        return host_registration.Registration(
            adapter=adapter, label="Codex", status=REGISTERED, name=f"tsunagou-{profile}",
            commands=(("codex", "mcp", "add", f"tsunagou-{profile}"),),
        )

    monkeypatch.setattr(host_registration, "register", fake_register)
    return recorded


def test_the_secret_never_reaches_the_answer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    daemon = Daemon()
    monkeypatch.setattr(enrollment, "forward", daemon)
    recorded = _registered(monkeypatch)

    report = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="codex", role="worker", nickname="熊猫",
        directory=Rosters(),
    )

    assert SECRET not in json.dumps(report, ensure_ascii=False), (
        "a page that held the enrollment secret would be one extension away from an Agent identity"
    )
    ticket = Path(str(report["ticket_file"]))
    assert ticket.is_file()
    assert json.loads(ticket.read_text(encoding="utf-8"))["secret"] == SECRET
    assert report["nickname"] == "熊猫", "the person's name is remembered, not turned into a path"
    assert report["profile"].isalnum() and len(str(report["profile"])) == 12, (
        "profile is the machine's unique slot name, not the nickname"
    )
    assert report["installation_id"] == "codex:" + str(report["profile"])
    assert recorded and recorded[0]["adapter"] == "codex"
    assert recorded[0]["bridge"]["env"]["TSUNAGOU_TICKET_FILE"] == str(ticket)
    assert daemon.calls[1] == "/api/v1/credential-deliveries/ref-1/ack", "the delivery is acknowledged"


def test_two_enrollments_never_share_one_local_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)

    first = enrollment.prepare(entry, dict(entry.daemon or {}), vendor="codex", role="worker", nickname="agent", directory=Rosters())
    second = enrollment.prepare(entry, dict(entry.daemon or {}), vendor="codex", role="worker", nickname="agent", directory=Rosters())

    assert first["profile"] != second["profile"], "the same nickname twice is still two conversations"
    assert first["bridge_dir"] != second["bridge_dir"]


def test_the_launch_description_points_at_the_ticket_and_the_daemon(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)

    report = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="codex", role="worker", nickname="main",
        profile="main", directory=Rosters(),
    )

    config = json.loads(Path(str(report["bridge_config"])).read_text(encoding="utf-8"))
    assert config["adapter"] == "codex"
    assert config["env"]["TSUNAGOU_HTTP_URL"] == "http://127.0.0.1:59999"
    # 路径按平台比：配置里是原生写法（Node 要读它），报告里是 posix 写法（给人看）。
    assert Path(str(config["env"]["TSUNAGOU_TICKET_FILE"])) == Path(str(report["ticket_file"]))
    assert Path(str(config["env"]["TSUNAGOU_PROJECT_ROOT"])) == entry.path
    assert Path(str(report["bridge_dir"])) == entry.path / ".tsunagou" / "bridges" / "codex-main"


def test_an_unknown_vendor_is_refused_before_a_ticket_is_issued(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    daemon = Daemon()
    monkeypatch.setattr(enrollment, "forward", daemon)

    with pytest.raises(ConsoleError) as refusal:
        enrollment.prepare(entry, dict(entry.daemon or {}), vendor="some-editor", role="worker")

    assert refusal.value.code == "unknown_host_vendor"
    assert daemon.calls == [], "a refused vendor must not leave a live ticket behind"


def test_a_bad_role_is_refused_before_a_ticket_is_issued(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    daemon = Daemon()
    monkeypatch.setattr(enrollment, "forward", daemon)

    with pytest.raises(ConsoleError) as refusal:
        enrollment.prepare(entry, dict(entry.daemon or {}), vendor="codex", role="boss")

    assert refusal.value.code == "invalid_requested_role"
    assert daemon.calls == []


def test_an_unbuilt_bridge_is_refused_before_a_ticket_is_issued(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    daemon = Daemon()
    monkeypatch.setattr(enrollment, "forward", daemon)
    monkeypatch.setattr(enrollment, "bridge_entry_path", lambda: tmp_path / "not-built" / "server.js")

    with pytest.raises(ConsoleError) as refusal:
        enrollment.prepare(entry, dict(entry.daemon or {}), vendor="codex", role="worker")

    assert refusal.value.code == "bridge_not_built"
    assert refusal.value.detail["build"] == enrollment.BUILD_COMMAND
    assert daemon.calls == [], "registering a command that cannot start helps nobody"


def test_a_daemon_refusal_travels_back_with_its_own_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon(status=400))

    with pytest.raises(ConsoleError) as refusal:
        enrollment.prepare(entry, dict(entry.daemon or {}), vendor="codex", role="worker")

    assert refusal.value.code == "unknown_payload_field"
    assert refusal.value.status == 400


def test_a_ticket_without_a_secret_is_not_treated_as_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon(result={"delivery_ref": "ref-1"}))

    with pytest.raises(ConsoleError) as refusal:
        enrollment.prepare(entry, dict(entry.daemon or {}), vendor="codex", role="worker")

    assert refusal.value.code == "ticket_unavailable"


def test_a_name_that_is_not_a_path_still_gets_one_profile_per_conversation() -> None:
    """Only influences an explicitly named profile; the nickname never becomes a path."""

    assert enrollment.profile_name("054") == "054"
    chinese = enrollment.profile_name("主 Agent")
    assert chinese != enrollment.profile_name("子 Agent"), (
        "two conversations must not share one local slot"
    )
    assert chinese.isascii() and chinese.startswith("Agent-")
    assert enrollment.profile_name("main agent") != enrollment.profile_name("main-agent")
    assert enrollment.profile_name("") == "current", "no name is one conversation, not none"


def test_the_page_can_ask_which_hosts_this_console_can_register() -> None:
    hosts = {host["adapter"]: host for host in enrollment.known_hosts()}

    assert hosts["codex"]["supported"] is True
    assert hosts["claudecode"]["supported"] is False
    assert hosts["claudecode"]["note"], "an unsupported host says so, in words a person can read"
    assert {host["adapter"] for host in enrollment.known_hosts()} == set(host_registration.HOSTS)


def test_the_console_serves_the_prepare_route(tmp_path: Path) -> None:
    """The page fetches one path per action; a renamed route must fail loudly here."""

    from tsunagou.console.app import create_console_app

    config = ConsoleConfig(
        projects_root=tmp_path / "projects", scan_roots=[tmp_path],
        index_path=tmp_path / "index.json", profile_path=tmp_path / "profile.json",
    )
    routes = {
        getattr(route, "path", ""): getattr(route, "endpoint", None)
        for route in create_console_app(config).routes
    }

    assert "/api/v1/console/hosts" in routes
    assert "/api/v1/console/projects/{project_id}/agents:prepare" in routes
    assert "/api/v1/console/enrollments/{enrollment_id}" in routes


def test_a_waiting_enrollment_turns_into_an_arrival_and_the_nickname_lands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The waiting overlay asks one question; this is the whole state machine behind it."""

    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda _url: True)
    rosters = Rosters(("agent-old",))

    prepared = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="codex", role="worker", nickname="熊猫", directory=rosters,
    )
    config = _config(tmp_path)
    enrollment_id = str(prepared["enrollment_id"])

    waiting = enrollment.status(enrollment_id, settings=config, directory=rosters)
    assert waiting["status"] == "waiting"
    assert waiting["enrollment_id"] == enrollment_id

    rosters.agent_ids = ("agent-old", "agent-new")
    arrived = enrollment.status(enrollment_id, settings=config, directory=rosters)

    assert arrived["status"] == "arrived"
    assert arrived["agent_id"] == "agent-new", "the one that was not there when the ticket was issued"
    profile = load_profile(config.profile_path)
    assert profile["agents"]["agent-new"] == {"nickname": "熊猫", "vendor": "Codex"}
    assert enrollment.status(enrollment_id, settings=config, directory=rosters)["status"] == "arrived", (
        "asking again must not change the answer"
    )


def test_a_project_that_cannot_be_read_keeps_waiting_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda _url: True)

    class Silent:
        def roster(self, project_id: str, root: Path, endpoint: dict[str, Any] | None, *, force: bool = False) -> None:
            return None

    prepared = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="codex", role="worker", nickname="x", directory=Silent(),
    )
    answer = enrollment.status(str(prepared["enrollment_id"]), settings=_config(tmp_path), directory=Silent())

    assert answer["status"] == "waiting"
    assert answer["note"], "读不到名单时说的是还没到，不是失败"


def test_an_expired_enrollment_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)
    prepared = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="codex", role="worker", directory=Rosters(),
    )
    record = enrollment.pending(str(prepared["enrollment_id"]))
    record.expires_at = 0.0

    answer = enrollment.status(record.enrollment_id, settings=_config(tmp_path), directory=Rosters())

    assert answer["status"] == "expired"
    assert answer["note"]


def test_an_unknown_enrollment_is_not_guessed_at(tmp_path: Path) -> None:
    with pytest.raises(ConsoleError) as refusal:
        enrollment.status("nope", settings=_config(tmp_path), directory=Rosters())

    assert refusal.value.code == "enrollment_not_found"
    assert refusal.value.status == 404


def test_an_unsupported_host_is_reported_not_faked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The ticket and the launch description are still prepared; only the host step is missing."""

    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())

    report = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="claudecode", role="worker", nickname="cc",
        directory=Rosters(),
    )

    assert report["host_registration"]["status"] == UNSUPPORTED
    assert report["host_registration"]["note"]
    assert Path(str(report["ticket_file"])).is_file(), "the person can still register the host by hand"
    assert report["next"]


def test_cancelling_removes_the_ticket_and_takes_the_host_entry_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """取消接入 = 票删掉（读不到票就无法兑换）+ 宿主条目收回（有办法收回时）+ 这条登记作废。"""

    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)
    removed: list[dict[str, Any]] = []

    def fake_unregister(adapter: str, *, profile: str, project_root: Path, **_: Any) -> Any:
        removed.append({"adapter": adapter, "profile": profile, "project_root": project_root})
        return host_registration.Registration(
            adapter=adapter, label="Codex", status=host_registration.UNREGISTERED,
            name=f"tsunagou-{profile}", commands=(("codex", "mcp", "remove", f"tsunagou-{profile}"),),
        )

    monkeypatch.setattr(host_registration, "unregister", fake_unregister)
    config = _config(tmp_path)
    rosters = Rosters(("agent-old",))
    prepared = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="codex", role="worker", nickname="熊猫", directory=rosters,
    )
    ticket = Path(str(prepared["ticket_file"]))
    assert ticket.is_file()

    report = enrollment.cancel(str(prepared["enrollment_id"]), settings=config)

    assert report["status"] == "cancelled"
    assert report["ticket_removed"] is True
    assert not ticket.is_file(), "a bridge cannot redeem a ticket it cannot read"
    assert removed and removed[0]["profile"] == prepared["profile"]
    assert removed[0]["project_root"] == entry.path

    rosters.agent_ids = ("agent-old", "agent-new")
    assert enrollment.status(str(prepared["enrollment_id"]), settings=config, directory=rosters)["status"] == "cancelled"
    assert load_profile(config.profile_path)["agents"] == {}, "取消掉的那次不该再给谁起名字"


def test_cancelling_an_arrived_enrollment_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda _url: True)
    rosters = Rosters()
    prepared = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="codex", role="worker", directory=rosters,
    )
    rosters.agent_ids = ("agent-new",)
    enrollment.status(str(prepared["enrollment_id"]), settings=_config(tmp_path), directory=rosters)

    with pytest.raises(ConsoleError) as refusal:
        enrollment.cancel(str(prepared["enrollment_id"]), settings=_config(tmp_path))

    assert refusal.value.code == "enrollment_already_arrived"
    assert refusal.value.status == 409


def test_forgetting_a_project_drops_its_pending_enrollments_and_their_tickets(tmp_path: Path) -> None:
    """删掉一个项目时，它还没到齐的票不能留着：票活着，bridge 就能接进一个没人能看见的项目。"""

    enrollment.forget_all()
    theirs = tmp_path / "theirs.json"
    mine = tmp_path / "mine.json"
    theirs.write_text("{}", encoding="utf-8")
    mine.write_text("{}", encoding="utf-8")
    for record in (
        enrollment.Enrollment(
            enrollment_id="e-theirs", project_id="p-gone", adapter="codex", label="Codex",
            profile="a", nickname="甲", role="worker", known_agents=frozenset(),
            expires_at=0.0, ticket_file=theirs.as_posix(),
        ),
        enrollment.Enrollment(
            enrollment_id="e-mine", project_id="p-kept", adapter="codex", label="Codex",
            profile="b", nickname="乙", role="worker", known_agents=frozenset(),
            expires_at=0.0, ticket_file=mine.as_posix(),
        ),
    ):
        enrollment._remember(record)

    dropped = enrollment.forget_project("p-gone")

    assert dropped == ["e-theirs"]
    assert not theirs.exists(), "被忘掉的那张票要一起删"
    assert mine.exists(), "别的项目的票不能动"
    with pytest.raises(ConsoleError):
        enrollment.pending("e-theirs")
    assert enrollment.pending("e-mine").project_id == "p-kept"
    """取消 + 状态 + 删除项目三条路都要在路由表里（否则页面会打到一个 404）。"""

    from tsunagou.console.app import create_console_app

    routes = {
        getattr(route, "path", "")
        for route in create_console_app(_config(tmp_path)).routes
    }

    assert "/api/v1/console/enrollments/{enrollment_id}:cancel" in routes
    assert "/api/v1/console/projects/{project_id}:forget" in routes
    from tsunagou.console.app import create_console_app

    routes = {
        getattr(route, "path", ""): getattr(route, "endpoint", None)
        for route in create_console_app(_config(tmp_path)).routes
    }

    assert "/api/v1/console/enrollments/{enrollment_id}:cancel" in routes
    assert "/api/v1/console/enrollments/{enrollment_id}" in routes
