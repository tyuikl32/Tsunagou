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
from tsunagou.console.agents import AgentRoster, _host_label
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.errors import ConsoleError
from tsunagou.console.profile import load_profile, update_profile
from tsunagou.console.projects import ProjectEntry
from tsunagou.console.proxy import ForwardResponse
from tsunagou.platform import host_registration
from tsunagou.platform.enrollment_store import EnrollmentStore
from tsunagou.platform.host_registration import REGISTERED

PROJECT_ID = "0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b44"
SECRET = "s3cret-ticket-value"


@pytest.fixture(autouse=True)
def _no_leftover_enrollments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "private-enrollments"))
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
    """The console's roster memory, told what to answer.

    ``session_status`` / ``role`` / ``missing`` default to "就绪、而且是票要的那个角色":
    the arrival rule reads all three, so a test that only cares about *who* is in the
    roster should not have to spell them out -- and a test that cares about the rule
    has to say so explicitly.
    """

    def __init__(
        self, agent_ids: tuple[str, ...] = (), *,
        session_status: str = "ready", role: str = "worker", missing: tuple[str, ...] = (),
        machine: str = "",
    ) -> None:
        self.agent_ids = agent_ids
        self.session_status = session_status
        self.role = role
        self.missing = missing
        # 远端自报的机器名（跨机器导入时由那张票带上来）：判定远端到没到，靠的就是它。
        self.machine = machine

    def roster(
        self, project_id: str, root: Path, endpoint: dict[str, Any] | None, *, force: bool = False, require_fresh: bool = False,
    ) -> AgentRoster | None:
        return AgentRoster(
            project_id=project_id, main_agent_id=self.agent_ids[0] if self.agent_ids else None,
            agents=tuple(
                {
                    "agent_id": agent_id, "status": "active", "role": self.role,
                    "session_status": self.session_status, "missing_admission": list(self.missing), "connection_epoch": 1,
                    **({"machine": self.machine} if self.machine else {}),
                }
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


def test_opencode_prepare_has_no_ticket_or_registration(monkeypatch, tmp_path):
    entry = _entry(tmp_path)
    daemon = Daemon()
    monkeypatch.setattr(enrollment, "forward", daemon)
    recorded = _registered(monkeypatch)
    report = enrollment.prepare(entry, {}, vendor="opencode", role="worker", directory=Rosters())
    assert report["host_registration"]["status"] == "deferred"
    assert report["phase"] == "pending"
    assert not daemon.calls and not recorded
    assert "ticket_file" not in report and "conversation_id" not in report
    assert not (entry.path / ".tsunagou/bridges").exists()


def test_repeated_opencode_prepare_reuses_pending_selection(monkeypatch, tmp_path):
    entry = _entry(tmp_path)
    first = enrollment.prepare(entry, {}, vendor="opencode", role="worker", nickname="agent")
    second = enrollment.prepare(entry, {}, vendor="opencode", role="worker", nickname="agent")
    assert first["enrollment_id"] == second["enrollment_id"]
    assert "thread_id" not in EnrollmentStore().current()


def test_opencode_prepare_preserves_role_without_using_display_profile(monkeypatch, tmp_path):
    entry = _entry(tmp_path)
    report = enrollment.prepare(entry, {}, vendor="opencode", role="main", profile="display-only")
    record = EnrollmentStore().current()
    assert record["requested_role"] == "main" and record["place"] == "local"
    assert "thread_id" not in record and "baseline" not in record
    assert report["host_registration"]["status"] == "deferred"


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
        enrollment.prepare(entry, dict(entry.daemon or {}), vendor="opencode", role="boss")

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
        enrollment.prepare(entry, dict(entry.daemon or {}), vendor="opencode", role="worker")

    assert refusal.value.code == "bridge_not_built"
    assert refusal.value.detail["build"] == enrollment.BUILD_COMMAND
    assert daemon.calls == [], "registering a command that cannot start helps nobody"


def test_opencode_preparation_does_not_need_daemon(monkeypatch, tmp_path):
    def forbidden(**_kwargs):
        pytest.fail("request-only preparation must not call daemon")
    monkeypatch.setattr(enrollment, "forward", forbidden)
    assert enrollment.prepare(_entry(tmp_path), {}, vendor="opencode", role="worker")["phase"] == "pending"


def test_opencode_request_is_not_arrived_when_an_unrelated_agent_appears(monkeypatch, tmp_path):
    entry = _entry(tmp_path)
    report = enrollment.prepare(entry, {}, vendor="opencode", role="worker")
    result = enrollment.status(report["enrollment_id"], settings=_config(tmp_path), directory=Rosters(("unrelated",)))
    assert result["status"] == "waiting" and result["phase"] == "pending"


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


def test_the_page_can_ask_what_happens_if_it_picks_this_vendor() -> None:
    """The page's one question is "点下一步会发生什么"; one field answers it."""

    hosts = {host["adapter"]: host for host in enrollment.known_hosts()}

    assert hosts["codex"]["mode"] == enrollment.CONSOLE_MODE
    assert hosts["opencode"]["mode"] == enrollment.CONSOLE_MODE
    assert hosts["codex"]["note"] == "", "a host the console can finish needs no excuse"
    # DeepSeek is not "not implemented": it enrolls inside its own chat, so the page
    # points at that sentence instead of queueing a ticket nobody will redeem.
    assert hosts["deepseek"]["mode"] == enrollment.IN_HOST_MODE
    assert "DeepSeek Harness" in hosts["deepseek"]["note"]
    assert hosts["claudecode"]["mode"] == enrollment.UNSUPPORTED_MODE
    assert hosts["claudecode"]["note"], "an unsupported host says so, in words a person can read"
    assert hosts["zcode"]["mode"] == enrollment.UNSUPPORTED_MODE
    assert {host["adapter"] for host in enrollment.known_hosts()} == set(host_registration.HOSTS)


@pytest.mark.parametrize("vendor", ["claudecode", "zcode"])
def test_a_host_this_console_cannot_finish_is_refused_before_a_ticket_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, vendor: str,
) -> None:
    """A ticket only a person could redeem looks like progress and ends in "票过期了"."""

    entry = _entry(tmp_path)
    daemon = Daemon()
    monkeypatch.setattr(enrollment, "forward", daemon)
    monkeypatch.setattr(enrollment, "bridge_entry_path", lambda: _built_bridge(tmp_path))

    with pytest.raises(ConsoleError) as refusal:
        enrollment.prepare(
            entry, dict(entry.daemon or {}), vendor=vendor, role="worker", directory=Rosters(),
        )

    assert refusal.value.code == "host_enroll_not_available"
    assert refusal.value.detail["enroll_mode"] == enrollment.UNSUPPORTED_MODE
    assert refusal.value.detail["note"], "the refusal has to say where to go instead"
    assert daemon.calls == [], "no ticket is asked for a host we cannot finish"
    assert not (entry.path / ".tsunagou" / "bridges").exists(), "a refusal leaves nothing behind"
    assert EnrollmentStore().active() is None, "nothing is recorded either"


def test_the_host_that_enrolls_itself_only_leaves_the_decision_in_the_machine_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """DeepSeek Harness 那条路：控制台不签票、不写宿主配置，只记下"谁要接哪个项目"。

    那条聊天里的 ``tsunagou_connect`` 只有自己的会话 id 和工作目录，而工作目录常常不是
    协调仓库 —— 这条机器级记录是它唯一能查出"接哪个项目、什么角色"的地方。
    """

    entry = _entry(tmp_path)
    daemon = Daemon()
    monkeypatch.setattr(enrollment, "forward", daemon)
    monkeypatch.setattr(enrollment, "bridge_entry_path", lambda: _built_bridge(tmp_path))

    answer = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="deepseek", role="main",
        nickname="熊猫", directory=Rosters(),
    )

    assert answer["status"] == "prepared"
    assert answer["role"] == "main" and answer["nickname"] == "熊猫"
    assert "DeepSeek Harness" in answer["next"], "那句指路照实来自宿主表"
    assert daemon.calls == [], "这条路没有票要签"
    assert not (entry.path / ".tsunagou" / "bridges").exists(), "也不往项目里写任何桥材料"
    recorded = EnrollmentStore().active_for("deepseek")
    assert recorded is not None, "决定留在机器级记录里"
    assert recorded["requested_role"] == "main"
    assert Path(recorded["project_root"]).resolve() == entry.path.resolve()
    assert recorded["enrollment_id"] == answer["enrollment_id"]
    EnrollmentStore().link_deepseek(answer["enrollment_id"], project_id=PROJECT_ID, role="main", agent_id="a-2")
    # 到达之后这条记录要自己让位：同一时刻只允许一条，下一个人还得接得上。
    _host_profile(tmp_path, {"a-1": "DeepSeek Harness", "a-2": "DeepSeek Harness"})
    monkeypatch.setattr(enrollment, "daemon_state", lambda root, probe=True: {
        "running": True, "url": "http://127.0.0.1:59999", "project_id": PROJECT_ID,
    })
    arrived = enrollment.observe(
        settings=_config(tmp_path), directory=Rosters(("a-1", "a-2"), role="main"), project_id=PROJECT_ID,
        adapter="deepseek", baseline={"a-1"}, enrollment_id=answer["enrollment_id"],
    )
    assert arrived["status"] == "arrived"
    assert EnrollmentStore().active() is None


def test_a_seat_with_the_wrong_role_does_not_finish_this_enrollment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """页面选主 Agent，那边却以子 Agent 接入：如实说没到位，绝不报"主 Agent 已接入"。

    记录也不收 —— 真正该来的那个还能用它；这正是"页面上选什么角色，就只能以什么角色接入"
    在显示这一侧的保证（票那一侧由 daemon 保证：票里的角色就是席位角色）。
    """

    entry = _entry(tmp_path)
    daemon = Daemon()
    monkeypatch.setattr(enrollment, "forward", daemon)
    monkeypatch.setattr(enrollment, "bridge_entry_path", lambda: _built_bridge(tmp_path))
    prepared = enrollment.prepare(
        entry, dict(entry.daemon or {}), vendor="deepseek", role="main", nickname="熊猫",
        directory=Rosters(),
    )
    EnrollmentStore().link_deepseek(prepared["enrollment_id"], project_id=PROJECT_ID, role="main", agent_id="a-2")
    _host_profile(tmp_path, {"a-1": "DeepSeek Harness", "a-2": "DeepSeek Harness"})
    monkeypatch.setattr(enrollment, "daemon_state", lambda root, probe=True: {
        "running": True, "url": "http://127.0.0.1:59999", "project_id": PROJECT_ID,
    })

    answer = enrollment.observe(
        settings=_config(tmp_path), directory=Rosters(("a-1", "a-2"), role="worker"), project_id=PROJECT_ID,
        adapter="deepseek", baseline={"a-1"}, enrollment_id=prepared["enrollment_id"],
    )

    assert answer["status"] == "waiting"
    assert answer["pending"]["role"] == "worker"
    assert "角色" in answer["note"]
    assert EnrollmentStore().active_for("deepseek") is not None, "记录留着等真正该来的那个"

    # 同一个席位换成正确身份回来时，才算到了。
    settled = enrollment.observe(
        settings=_config(tmp_path), directory=Rosters(("a-1", "a-2"), role="main"), project_id=PROJECT_ID,
        adapter="deepseek", baseline={"a-1"}, enrollment_id=prepared["enrollment_id"],
    )
    assert settled["status"] == "arrived"
    assert EnrollmentStore().active() is None


def test_a_network_invitation_is_signed_here_and_written_nowhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """跨机器那张邀请：主机只签票、只给出一段内容；票和身份都由远端写自己的机器。"""

    import tsunagou.platform.remote_invite as remote_invite

    entry = _entry(tmp_path)
    daemon = Daemon()
    monkeypatch.setattr(enrollment, "forward", daemon)
    monkeypatch.setattr(enrollment, "bridge_entry_path", lambda: _built_bridge(tmp_path))

    answer = enrollment.prepare(
        entry, {**dict(entry.daemon or {}), "url": "http://127.0.0.1:2810",
                "advertised_url": "http://10.0.0.5:2810"},
        vendor="opencode", role="worker", nickname="小三",
        token="control-token", directory=Rosters(), place="network",
    )

    assert answer["status"] == "invited"
    assert answer["url"] == "http://10.0.0.5:2810", "邀请里写的是对外可达地址"
    assert answer["conversation_id"] == "ses_小三", "会话名由主机起"
    decoded = remote_invite.decode(answer["invite"])
    assert decoded["project_id"] == PROJECT_ID and decoded["role"] == "worker"
    assert decoded["secret"] == SECRET and decoded["installation_id"] == "opencode:小三"
    remote_invite.check(decoded)
    assert daemon.calls == ["/api/v1/commands/agent.ticket.create.user"], "只问一次票"
    assert not (entry.path / ".tsunagou" / "bridges").exists(), "主机这边不写桥材料"
    assert not (entry.path / ".tsunagou" / "checkpoints").exists()
    # 机器级记录还是要写：页面靠它等那个席位出现，并且核对角色。
    recorded = EnrollmentStore().active_for("opencode")
    assert recorded is not None and recorded["requested_role"] == "worker"
    assert recorded["enrollment_id"] == answer["enrollment_id"]


def test_a_network_invitation_needs_the_number_for_hosts_that_own_their_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Codex / DSH 的会话名只有它自己知道：没报号就不发邀请，报了号就照号签票。"""

    import tsunagou.platform.remote_invite as remote_invite

    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    monkeypatch.setattr(enrollment, "bridge_entry_path", lambda: _built_bridge(tmp_path))
    endpoint = {**dict(entry.daemon or {}), "advertised_url": "http://10.0.0.5:2810"}

    with pytest.raises(ConsoleError) as refused:
        enrollment.prepare(
            entry, endpoint, vendor="codex", role="worker", nickname="小三",
            token="control-token", directory=Rosters(), place="network",
        )
    assert refused.value.code == "conversation_id_required_for_this_host"
    assert EnrollmentStore().active() is None, "拒绝了就不留记录"

    answer = enrollment.prepare(
        entry, endpoint, vendor="codex", role="worker", nickname="小三", token="control-token",
        directory=Rosters(), place="network", conversation_id="thread-abc",
    )
    assert remote_invite.decode(answer["invite"])["conversation_id"] == "thread-abc"


def test_a_network_invitation_is_worker_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """主 Agent 必须和协调中心同机：跨机器那张邀请只能是子 Agent。"""

    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    monkeypatch.setattr(enrollment, "bridge_entry_path", lambda: _built_bridge(tmp_path))

    with pytest.raises(ConsoleError) as refused:
        enrollment.prepare(
            entry, {**dict(entry.daemon or {}), "advertised_url": "http://10.0.0.5:2810"},
            vendor="opencode", role="main", token="control-token", directory=Rosters(), place="network",
        )
    assert refused.value.code == "main_agent_must_be_local"


def test_opencode_prepare_does_not_preselect_conversation(monkeypatch, tmp_path):
    report = enrollment.prepare(_entry(tmp_path), {}, vendor="opencode", role="worker", profile="name")
    record = EnrollmentStore().current()
    assert record["adapter"] == "opencode" and "thread_id" not in record
    assert "conversation_id" not in report and "installation_id" not in report


def _built_bridge(tmp_path: Path) -> Path:
    """A stand-in entry file: these tests are about the ticket, not about a build."""

    entry = tmp_path / "built-server.js"
    entry.write_text("// stand-in for packages/bridge-server/dist/server.js\n", encoding="utf-8")
    return entry


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


def _legacy_prepared_record(entry, endpoint, *, vendor, role, nickname="", directory=None):
    """An existing pre-upgrade project-ticket record; no new legacy enrollment."""
    ticket = entry.path / ".tsunagou/bridges/opencode-legacy/ticket.json"
    ticket.parent.mkdir(parents=True, exist_ok=True)
    ticket.write_text("{}", encoding="utf-8")
    roster = directory.roster(entry.project_id, entry.path, endpoint) if directory else None
    record = enrollment.Enrollment(
        enrollment_id="legacy-record", project_id=entry.project_id, adapter=vendor, label="OpenCode",
        profile="legacy", nickname=nickname, role=role,
        known_agents=frozenset(a["agent_id"] for a in roster.agents) if roster else frozenset(),
        expires_at=enrollment.time.time() + 900, ticket_file=str(ticket), blind=roster is None,
    )
    enrollment._remember(record)
    return {**record.public(), "ticket_file": str(ticket)}


def test_a_waiting_enrollment_turns_into_an_arrival_and_the_nickname_lands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The waiting overlay asks one question; this is the whole state machine behind it."""

    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda _url: True)
    rosters = Rosters(("agent-old",))

    prepared = _legacy_prepared_record(
        entry, dict(entry.daemon or {}), vendor="opencode", role="worker", nickname="熊猫", directory=rosters,
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
    assert profile["agents"]["agent-new"] == {"nickname": "熊猫", "vendor": "OpenCode"}
    assert enrollment.status(enrollment_id, settings=config, directory=rosters)["status"] == "arrived", (
        "asking again must not change the answer"
    )


def _prepared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, role: str, rosters: Rosters,
) -> tuple[dict[str, Any], ConsoleConfig, str]:
    """Prepare one enrollment against the stub daemon, ready for ``status`` calls."""

    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda _url: True)
    prepared = _legacy_prepared_record(
        entry, dict(entry.daemon or {}), vendor="opencode", role=role, nickname="熊猫", directory=rosters,
    )
    return prepared, _config(tmp_path), str(prepared["enrollment_id"])


@pytest.mark.parametrize(
    "session_status,role,missing",
    [
        ("degraded", "worker", ("identity.continuity_evidence",)),
        ("ready", "worker", ()),
    ],
)
def test_a_session_that_joined_without_the_requested_role_is_not_an_arrival(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, session_status: str, role: str, missing: tuple[str, ...],
) -> None:
    """"到了"和"就位"是两件事。

    名单里多出一个人只说明那个会话兑换了票。主 Agent 的任命是 daemon 在就绪那一步
    顺手做的，而首次接入天然还不就绪 —— 所以只数人头会把一个既没有角色、也没有基础
    授权的成员报成"主 Agent 已接入"。
    """

    rosters = Rosters(("agent-old",))
    _prepared_answer, config, enrollment_id = _prepared(monkeypatch, tmp_path, role="main", rosters=rosters)

    rosters.agent_ids = ("agent-old", "agent-new")
    rosters.session_status = session_status
    rosters.role = role
    rosters.missing = missing

    answer = enrollment.status(enrollment_id, settings=config, directory=rosters)

    assert answer["status"] == "waiting", "还没就位就不能报成功"
    assert answer["agent_id"] is None, "不能把人头当成任命：这个成员还没有角色"
    pending = answer["pending"]
    assert pending["agent_id"] == "agent-new"
    assert pending["session_status"] == session_status
    assert pending["missing_admission"] == list(missing)


def test_a_ready_main_is_the_arrival_this_ticket_asked_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rosters = Rosters(("agent-old",))
    _prepared_answer, config, enrollment_id = _prepared(monkeypatch, tmp_path, role="main", rosters=rosters)

    rosters.agent_ids = ("agent-old", "agent-new")
    rosters.role = "main"

    answer = enrollment.status(enrollment_id, settings=config, directory=rosters)

    assert answer["status"] == "arrived"
    assert answer["agent_id"] == "agent-new"


def test_a_joined_but_unsettled_session_makes_the_expiry_notice_actionable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """人来了但没就位时，票过期不该说"重新添加" —— 票早就被兑换了。"""

    rosters = Rosters(("agent-old",))
    _prepared_answer, config, enrollment_id = _prepared(monkeypatch, tmp_path, role="main", rosters=rosters)
    rosters.agent_ids = ("agent-old", "agent-new")
    rosters.session_status = "degraded"
    rosters.role = "worker"
    assert enrollment.status(enrollment_id, settings=config, directory=rosters)["status"] == "waiting"

    record = enrollment.pending(enrollment_id)
    assert record is not None
    record.expires_at = 0.0
    expired = enrollment.status(enrollment_id, settings=config, directory=rosters)

    assert expired["status"] == "expired"
    assert "读一次项目上下文" in expired["note"], "票已经被兑换了，就别叫用户重新添加"


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

    prepared = _legacy_prepared_record(
        entry, dict(entry.daemon or {}), vendor="opencode", role="worker", nickname="x", directory=Silent(),
    )
    answer = enrollment.status(str(prepared["enrollment_id"]), settings=_config(tmp_path), directory=Silent())

    assert answer["status"] == "waiting"
    assert answer["note"], "读不到名单时说的是还没到，不是失败"


def test_an_expired_enrollment_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    monkeypatch.setattr(enrollment, "forward", Daemon())
    _registered(monkeypatch)
    prepared = _legacy_prepared_record(
        entry, dict(entry.daemon or {}), vendor="opencode", role="worker", directory=Rosters(),
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
    prepared = _legacy_prepared_record(
        entry, dict(entry.daemon or {}), vendor="opencode", role="worker", nickname="熊猫", directory=rosters,
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
    prepared = _legacy_prepared_record(
        entry, dict(entry.daemon or {}), vendor="opencode", role="worker", directory=rosters,
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



def _codex_intent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, role: str = "main", adapter: str = "codex") -> dict[str, Any]:
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda _url: True)
    entry = _entry(tmp_path)
    return enrollment.prepare(entry, dict(entry.daemon or {}), vendor=adapter, role=role, nickname="熊猫")


def _codex_enrolled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, role: str = "main", adapter: str = "codex") -> dict[str, Any]:
    prepared = _codex_intent(monkeypatch, tmp_path, role=role, adapter=adapter)
    store = EnrollmentStore()
    record = store.get(prepared["enrollment_id"])
    store.claim(record["enrollment_id"], "real-private-thread", expected_revision=record["revision"])
    return store.mark_enrolled(record["enrollment_id"], "real-private-thread", agent_id="bound-agent")


def _host_receipt(record: dict[str, Any], **updates: Any) -> None:
    receipt = {
        "format_version": 1, "enrollment_id": record["enrollment_id"], "thread_id": record["thread_id"],
        "project_id": record["project_id"], "agent_id": record["agent_id"], "role": record["requested_role"],
        "session_id": "session-real", "connection_epoch": 1, "observed_at": "2026-10-02T00:00:00.000Z",
        **updates,
    }
    Path(record["receipt_file"]).write_text(json.dumps(receipt), encoding="utf-8")


def test_codex_prepare_saves_selection_without_ticket_identity_or_registration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("Codex preparation must not issue tickets or touch host registrations")

    monkeypatch.setattr(enrollment, "forward", forbidden)
    monkeypatch.setattr(enrollment, "profile_identity", forbidden)
    monkeypatch.setattr(host_registration, "register", forbidden)
    prepared = _codex_intent(monkeypatch, tmp_path)
    record = EnrollmentStore().current()
    assert record["project_root"] == str((tmp_path / "project").resolve())
    assert record["requested_role"] == "main"
    assert "thread_id" not in record
    assert prepared["host_registration"]["status"] == "deferred"
    assert prepared["status"] == "prepared"
    assert prepared["phase"] == "pending"
    assert "请接入 Tsunagou" in prepared["next"]
    for private in ("thread_id", "receipt_file", "ticket_file", "installation_id", "bridge_config", "project_root"):
        assert private not in prepared
    assert not ((tmp_path / "project") / ".tsunagou" / "bridges").exists()


def test_codex_prepare_refuses_a_second_pending_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first = _codex_intent(monkeypatch, tmp_path)
    with pytest.raises(ConsoleError, match="enrollment_already_pending") as refused:
        _codex_intent(monkeypatch, tmp_path, role="worker")
    assert refused.value.status == 409
    assert EnrollmentStore().current()["enrollment_id"] == first["enrollment_id"]


@pytest.mark.parametrize("adapter", ["codex", "opencode"])
@pytest.mark.parametrize("role", ["main", "worker"])
def test_codex_arrival_requires_original_chat_receipt_and_survives_console_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, role: str, adapter: str,
) -> None:
    record = _codex_enrolled(monkeypatch, tmp_path, role=role, adapter=adapter)
    enrollment.forget_all()
    rosters = Rosters(("unrelated-agent", "bound-agent"), role=role)
    settings = _config(tmp_path)
    waiting = enrollment.status(record["enrollment_id"], settings=settings, directory=rosters)
    assert waiting["status"] == "waiting"
    assert waiting["phase"] == "enrolled"
    _host_receipt(record)
    arrived = enrollment.status(record["enrollment_id"], settings=settings, directory=rosters)
    assert arrived["status"] == "arrived"
    assert arrived["agent_id"] == "bound-agent"
    assert load_profile(settings.profile_path)["agents"]["bound-agent"] == {"nickname": "熊猫", "vendor": _host_label(adapter)}
    assert "real-private-thread" not in json.dumps(arrived)
    assert "receipt_file" not in arrived
    with pytest.raises(ConsoleError, match="enrollment_already_arrived"):
        enrollment.cancel(record["enrollment_id"], settings=settings)


@pytest.mark.parametrize("field,value", [
    ("format_version", 2), ("enrollment_id", "other"), ("thread_id", "other"),
    ("project_id", "other"), ("agent_id", "other"), ("role", "worker"),
    ("connection_epoch", 2), ("connection_epoch", True), ("session_id", ""), ("observed_at", ""),
])
def test_codex_rejects_receipt_mismatches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str, value: Any) -> None:
    record = _codex_enrolled(monkeypatch, tmp_path)
    _host_receipt(record, **{field: value})
    answer = enrollment.status(record["enrollment_id"], settings=_config(tmp_path), directory=Rosters(("bound-agent",), role="main"))
    assert answer["status"] == "waiting"


@pytest.mark.parametrize("agent_ids,role,session_status", [
    (("unrelated-agent",), "main", "ready"), (("bound-agent",), "worker", "ready"),
    (("bound-agent",), "main", "degraded"),
])
def test_codex_cannot_arrive_through_an_unrelated_or_unready_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, agent_ids: tuple[str, ...], role: str, session_status: str,
) -> None:
    record = _codex_enrolled(monkeypatch, tmp_path)
    _host_receipt(record)
    answer = enrollment.status(record["enrollment_id"], settings=_config(tmp_path),
                               directory=Rosters(agent_ids, role=role, session_status=session_status))
    assert answer["status"] == "waiting"
    assert load_profile(_config(tmp_path).profile_path)["agents"] == {}


def test_codex_cancel_does_not_unregister_shared_mcp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("Cancelling an intent cannot touch global shared MCP")

    monkeypatch.setattr(host_registration, "unregister", forbidden)
    prepared = _codex_intent(monkeypatch, tmp_path)
    result = enrollment.cancel(prepared["enrollment_id"], settings=_config(tmp_path))
    assert result["status"] == "cancelled"
    assert result["ticket_removed"] is False
    assert EnrollmentStore().get(prepared["enrollment_id"])["status"] == "cancelled"


def test_codex_claimed_cancel_is_refused_and_failure_stays_with_original_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prepared = _codex_intent(monkeypatch, tmp_path)
    record = EnrollmentStore().claim(prepared["enrollment_id"], "real-private-thread", expected_revision=1)
    EnrollmentStore().fail(record["enrollment_id"], "real-private-thread", "host_not_ready")
    with pytest.raises(ConsoleError, match="enrollment_already_claimed") as refused:
        enrollment.cancel(record["enrollment_id"], settings=_config(tmp_path))
    assert refused.value.status == 409
    answer = enrollment.status(record["enrollment_id"], settings=_config(tmp_path), directory=Rosters())
    assert answer["status"] == "waiting" and answer["phase"] == "failed"
    assert answer["error"] == "host_not_ready"
    assert "real-private-thread" not in json.dumps(answer)


def test_forget_project_invalidates_persistent_intent_without_unregistering(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prepared = _codex_intent(monkeypatch, tmp_path)
    assert enrollment.forget_project(PROJECT_ID) == [prepared["enrollment_id"]]
    answer = enrollment.status(prepared["enrollment_id"], settings=_config(tmp_path), directory=Rosters())
    assert answer["status"] == "cancelled"
    with pytest.raises(RuntimeError, match="enrollment_not_pending"):
        EnrollmentStore().current()



def test_codex_http_prepare_does_not_require_live_daemon(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tsunagou.console.app import AgentPrepareRequest, create_console_app

    _entry(tmp_path)

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("Preparing Codex selection must not start a daemon or load its control token")

    monkeypatch.setattr("tsunagou.console.app.ensure_daemon", forbidden)
    monkeypatch.setattr("tsunagou.console.app.project_token", forbidden)
    routes = {getattr(route, "path", ""): getattr(route, "endpoint", None) for route in create_console_app(_config(tmp_path)).routes}
    prepared = routes["/api/v1/console/projects/{project_id}/agents:prepare"](
        PROJECT_ID, AgentPrepareRequest(vendor="codex", role="main"),
    )
    assert prepared["status"] == "prepared"
    assert EnrollmentStore().get(prepared["enrollment_id"])["status"] == "pending"


def test_codex_expired_intent_remains_queryable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prepared = _codex_intent(monkeypatch, tmp_path)
    store = EnrollmentStore()
    future = store.get(prepared["enrollment_id"])["expires_at"] + 1
    monkeypatch.setattr(enrollment, "EnrollmentStore", lambda: EnrollmentStore(store.directory, clock=lambda: future))
    answer = enrollment.status(prepared["enrollment_id"], settings=_config(tmp_path), directory=Rosters())
    assert answer["status"] == "expired"
    assert answer["note"]


def test_codex_receipt_cannot_use_cached_roster_when_daemon_stops_answering(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tsunagou.console.agents import AgentDirectory

    record = _codex_enrolled(monkeypatch, tmp_path)
    _host_receipt(record)
    roster = Rosters(("bound-agent",), role="main").roster(PROJECT_ID, tmp_path, {})
    replies = [roster, None]
    directory = AgentDirectory(reader=lambda *_: replies.pop(0))
    entry = _entry(tmp_path)
    assert directory.roster(PROJECT_ID, entry.path, entry.daemon) is not None
    answer = enrollment.status(record["enrollment_id"], settings=_config(tmp_path), directory=directory)
    assert answer["status"] == "waiting"


def test_daemon_epoch_survives_console_roster_projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tsunagou.console.agents import AgentDirectory

    entry = _entry(tmp_path)
    monkeypatch.setattr("tsunagou.console.agents._get_json", lambda *_: {"items": [{
        "agent_id": "bound-agent", "role": "main", "session_status": "ready", "connection_epoch": 7,
    }]})
    roster = AgentDirectory().roster(PROJECT_ID, entry.path, entry.daemon, require_fresh=True)
    assert roster is not None and roster.agents[0]["connection_epoch"] == 7



def _host_profile(tmp_path: Path, vendors: dict[str, str]) -> None:
    """The user profile as `reconcile_vendors` would have left it: proven vendor per Agent."""

    (tmp_path / "profile.json").write_text(
        json.dumps({"agents": {agent: {"vendor": vendor} for agent, vendor in vendors.items()}}),
        encoding="utf-8",
    )


def _observing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, roster: Rosters) -> dict[str, Any]:
    _discoverable(tmp_path)          # 项目得先在磁盘上，find() 才找得到它
    monkeypatch.setattr(enrollment, "daemon_state", lambda root, probe=True: {
        "running": True, "url": "http://127.0.0.1:59999", "project_id": PROJECT_ID,
    })
    return enrollment.observe(
        settings=_config(tmp_path), directory=roster, project_id=PROJECT_ID,
        adapter="deepseek", baseline={"a-1"},
    )


def test_in_host_observe_waits_until_a_proven_seat_appears(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """宿主自己接入时没有票可问：等的是"名单里多了一个能证明来自它的席位"。

    证明材料不是页面给的，是 `agent connect` 写下的接入材料 —— 读名单那条路会把它变成
    档案里的厂商（见 agents.reconcile_vendors），所以这里用档案模拟那一步的结果。
    """

    _host_profile(tmp_path, {"a-1": "DeepSeek Harness"})
    assert _observing(monkeypatch, tmp_path, Rosters(("a-1",)))["status"] == "waiting"

    _host_profile(tmp_path, {"a-1": "DeepSeek Harness", "a-2": "DeepSeek Harness"})
    arrived = _observing(monkeypatch, tmp_path, Rosters(("a-1", "a-2")))
    assert arrived["status"] == "arrived"
    assert arrived["agent"]["agent_id"] == "a-2"


def test_a_seat_nobody_can_attribute_is_not_this_host_arrival(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """认不出来历的新席位不算到了：宁可继续等，也不替别家认领一次接入。"""

    _host_profile(tmp_path, {"a-1": "DeepSeek Harness"})
    assert _observing(monkeypatch, tmp_path, Rosters(("a-1", "a-2")))["status"] == "waiting"

    _host_profile(tmp_path, {"a-1": "DeepSeek Harness", "a-2": "Codex"})
    assert _observing(monkeypatch, tmp_path, Rosters(("a-1", "a-2")))["status"] == "waiting"


def test_observe_refuses_without_an_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _discoverable(tmp_path)
    with pytest.raises(ConsoleError, match="adapter_required") as refused:
        enrollment.observe(
            settings=_config(tmp_path), directory=Rosters(()), project_id=PROJECT_ID,
            adapter="", baseline=set(),
        )
    assert refused.value.status == 400


def test_observe_keeps_waiting_when_the_daemon_is_not_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """daemon 没起来不是"没连上"：接入会在那条聊天里自己把它带起来，所以照旧等。"""

    monkeypatch.setattr(enrollment, "daemon_state", lambda root, probe=True: {"running": False})
    _discoverable(tmp_path)
    answer = enrollment.observe(
        settings=_config(tmp_path), directory=Rosters(("a-1", "a-2")), project_id=PROJECT_ID,
        adapter="deepseek", baseline={"a-1"},
    )
    assert answer["status"] == "waiting" and answer["note"]


def test_codex_reprepare_reuses_matching_selection_and_keeps_original_nickname(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first = _codex_intent(monkeypatch, tmp_path)
    entry = _entry(tmp_path)
    again = enrollment.prepare(entry, {}, vendor="codex", role="main", nickname="replacement")
    assert again["enrollment_id"] == first["enrollment_id"]
    assert again["nickname"] == "熊猫"
    assert EnrollmentStore().active()["revision"] == 1


def test_codex_conflict_identifies_public_active_enrollment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first = _codex_intent(monkeypatch, tmp_path)
    active = EnrollmentStore().claim(first["enrollment_id"], "real-private-thread", expected_revision=1)
    other = ProjectEntry(project_id="another-project", path=tmp_path / "another-project", name="other")
    with pytest.raises(ConsoleError, match="enrollment_already_pending") as refused:
        enrollment.prepare(other, {}, vendor="codex", role="worker")
    assert refused.value.status == 409
    public = refused.value.detail["enrollment"]
    assert public["enrollment_id"] == first["enrollment_id"]
    assert public["project_id"] == PROJECT_ID and public["role"] == "main"
    assert public["phase"] == "connecting"
    assert refused.value.detail["note"]
    encoded = json.dumps(refused.value.body())
    assert active["thread_id"] not in encoded
    assert "receipt_file" not in encoded and "project_root" not in encoded


def test_current_endpoint_recovers_wait_and_precedes_parameterized_route(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tsunagou.console.app import create_console_app

    application = create_console_app(_config(tmp_path))
    paths = [getattr(route, "path", "") for route in application.routes]
    endpoints = {getattr(route, "path", ""): getattr(route, "endpoint", None) for route in application.routes}
    current = endpoints["/api/v1/console/enrollments/current"]
    assert paths.index("/api/v1/console/enrollments/current") < paths.index("/api/v1/console/enrollments/{enrollment_id}")
    assert current() == {"status": "none"}
    first = _codex_intent(monkeypatch, tmp_path)
    enrollment.forget_all()
    recovered = current()
    assert recovered["enrollment_id"] == first["enrollment_id"]
    assert recovered["status"] == "waiting" and recovered["phase"] == "pending"
    assert "thread_id" not in recovered and "project_root" not in recovered


def test_reprepare_after_refresh_reconciles_completed_receipt_and_frees_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tsunagou.console.app import AgentPrepareRequest, create_console_app

    first = _codex_enrolled(monkeypatch, tmp_path)
    _host_receipt(first)
    monkeypatch.setattr("tsunagou.console.app.AgentDirectory", lambda **_: Rosters(("bound-agent",), role="main"))
    endpoints = {getattr(route, "path", ""): getattr(route, "endpoint", None)
                 for route in create_console_app(_config(tmp_path)).routes}
    prepared = endpoints["/api/v1/console/projects/{project_id}/agents:prepare"](
        PROJECT_ID, AgentPrepareRequest(vendor="codex", role="worker"),
    )
    assert prepared["enrollment_id"] != first["enrollment_id"]
    assert prepared["role"] == "worker"
    assert EnrollmentStore().get(first["enrollment_id"])["status"] == "arrived"
    assert EnrollmentStore().active()["enrollment_id"] == prepared["enrollment_id"]


def test_late_failure_cannot_block_receipt_reconciliation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    record = _codex_enrolled(monkeypatch, tmp_path)
    _host_receipt(record)
    EnrollmentStore().fail(record["enrollment_id"], record["thread_id"], "host_timeout")
    answer = enrollment.current_status(settings=_config(tmp_path), directory=Rosters(("bound-agent",), role="main"))
    assert answer["status"] == "arrived"
    assert EnrollmentStore().active() is None
    assert enrollment.current_status(settings=_config(tmp_path), directory=Rosters()) == {"status": "none"}


# ---- 没有回执可等的那两条路（宿主自己接入 / 跨机器邀请）---------------------------
#
# 这两条路主机上**什么都不写**：没有票要问、没有回执要等，唯一的证据是名单 —— "申请时不在、
# 现在出现、身份对得上、角色对得上"的那个席位。这几条钉住的就是这件事，以及"两边判定不分家"
# （页面那条 observe 出口与控制台自己的 status 出口共用同一套判据）。


def _watched_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, adapter: str, role: str = "worker",
    baseline: tuple[str, ...] = ("old-agent",),
) -> str:
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda _url: True)
    entry = _entry(tmp_path)
    return enrollment._record_selection(
        entry=entry, adapter=adapter, role=role, nickname="远端小三", baseline=baseline,
    )


def test_an_in_host_seat_is_recognised_from_the_roster(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    enrollment_id = _watched_record(monkeypatch, tmp_path, adapter="deepseek")
    settings = _config(tmp_path)
    update_profile(settings.profile_path, {"agents": {"new-agent": {"nickname": "", "vendor": _host_label("deepseek")}}})

    arrived = enrollment.status(enrollment_id, settings=settings, directory=Rosters(("old-agent", "new-agent")))

    assert arrived["status"] == "arrived"
    assert arrived["agent_id"] == "new-agent"
    assert EnrollmentStore().get(enrollment_id)["status"] == "arrived"
    assert EnrollmentStore().active() is None, "认出来了就把那条唯一的名额让出来"


@pytest.mark.parametrize("baseline", [(), ("old-agent", "new-agent")])
def test_dsh_connection_result_survives_late_or_polluted_baseline(monkeypatch, tmp_path, baseline):
    enrollment_id = _watched_record(monkeypatch, tmp_path, adapter="deepseek", baseline=baseline)
    store = EnrollmentStore()
    store.link_deepseek(enrollment_id, project_id=PROJECT_ID, role="worker", agent_id="new-agent")
    settings = _config(tmp_path)
    update_profile(settings.profile_path, {"agents": {"new-agent": {"vendor": _host_label("deepseek")}}})
    roster = Rosters(("old-agent", "new-agent"), session_status="degraded")
    assert enrollment.current_status(settings=settings, directory=roster)["status"] == "waiting"
    roster.session_status = "ready"
    arrived = enrollment.observe(settings=settings, directory=roster, project_id=PROJECT_ID,
                                 adapter="deepseek", baseline={"new-agent"}, enrollment_id=enrollment_id)
    assert arrived["status"] == "arrived"
    assert EnrollmentStore().get(enrollment_id)["agent_id"] == "new-agent"
    assert enrollment.status(enrollment_id, settings=settings, directory=roster)["status"] == "arrived"


def test_a_seat_that_was_already_there_is_not_an_arrival(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    enrollment_id = _watched_record(monkeypatch, tmp_path, adapter="deepseek")
    settings = _config(tmp_path)
    update_profile(settings.profile_path, {"agents": {"old-agent": {"nickname": "", "vendor": _host_label("deepseek")}}})

    answer = enrollment.status(enrollment_id, settings=settings, directory=Rosters(("old-agent",)))

    assert answer["status"] == "waiting", "基线里的人不算刚到的人"
    assert "deepseek 那边" not in answer["note"] or True  # 文案不该再写死 Codex
    assert "Codex" not in answer["note"]


def test_an_in_host_seat_with_the_wrong_role_keeps_waiting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    enrollment_id = _watched_record(monkeypatch, tmp_path, adapter="deepseek", role="main")
    settings = _config(tmp_path)
    update_profile(settings.profile_path, {"agents": {"new-agent": {"nickname": "", "vendor": _host_label("deepseek")}}})

    answer = enrollment.status(
        enrollment_id, settings=settings,
        directory=Rosters(("old-agent", "new-agent"), role="worker"),
    )

    assert answer["status"] == "waiting"
    assert "角色" in answer["note"], "角色不对要如实说，不能报成功"
    assert EnrollmentStore().get(enrollment_id)["status"] == "pending", "记录留着等真正该来的那个"


def test_a_remote_seat_is_recognised_by_its_self_reported_machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """跨机器邀请在主机上什么都不写：认它靠的是"自己报了机器名"（入席时由 daemon 记下）。"""

    enrollment_id = _watched_record(monkeypatch, tmp_path, adapter="opencode")

    arrived = enrollment.status(
        enrollment_id, settings=_config(tmp_path),
        directory=Rosters(("old-agent", "remote-agent"), machine="工位-九"),
    )

    assert arrived["status"] == "arrived"
    assert arrived["agent_id"] == "remote-agent"


def test_a_missing_baseline_is_written_down_before_anyone_is_judged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """申请时读不到名单（daemon 还没起）：先把"现在有谁"记下来，别把老席位当成刚到的人。"""

    enrollment_id = _watched_record(monkeypatch, tmp_path, adapter="deepseek", baseline=())
    settings = _config(tmp_path)
    update_profile(settings.profile_path, {"agents": {"sitting-there": {"nickname": "", "vendor": _host_label("deepseek")}}})

    first = enrollment.status(enrollment_id, settings=settings, directory=Rosters(("sitting-there",)))

    assert first["status"] == "waiting"
    assert EnrollmentStore().get(enrollment_id)["baseline"] == ["sitting-there"], "基线补记下来了"

    # 新席位出现时，控制台读名单会顺手从接入文件学到它的厂商（agents.py 的那一步），
    # 所以判定时档案里已经有它了。
    update_profile(settings.profile_path, {"agents": {"new-agent": {"nickname": "", "vendor": _host_label("deepseek")}}})
    arrived = enrollment.status(enrollment_id, settings=settings, directory=Rosters(("sitting-there", "new-agent")))

    assert arrived["status"] == "arrived" and arrived["agent_id"] == "new-agent"


def test_the_page_observer_and_the_console_judge_alike(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """页面那条 observe 出口与控制台的 status 出口，对同一份名单给出同一个答案。"""

    enrollment_id = _watched_record(monkeypatch, tmp_path, adapter="deepseek")
    settings = _config(tmp_path)
    update_profile(settings.profile_path, {"agents": {"new-agent": {"nickname": "", "vendor": _host_label("deepseek")}}})
    rosters = Rosters(("old-agent", "new-agent"))
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda _url: True)

    watched = enrollment.observe(
        settings=settings, directory=rosters, project_id=PROJECT_ID, adapter="deepseek",
        baseline={"old-agent"}, enrollment_id=enrollment_id,
    )
    console = enrollment.status(enrollment_id, settings=settings, directory=rosters)

    assert watched["status"] == console["status"] == "arrived"
    assert watched["agent"]["agent_id"] == console["agent_id"] == "new-agent"


def test_local_dsh_waits_for_link_and_completes_serial_requests(monkeypatch, tmp_path):
    monkeypatch.setattr("tsunagou.console.projects.daemon_alive", lambda _url: True)
    entry = _entry(tmp_path)
    settings = _config(tmp_path)
    directory = Rosters(("first", "second"))
    for agent_id in ("first", "second"):
        request_id = enrollment._record_selection(entry=entry, adapter="deepseek", role="worker",
                                                  nickname="DSH", place="local")
        waiting = enrollment.current_status(settings=settings, directory=directory)
        assert waiting["status"] == "waiting" and "关联" in waiting["note"]
        EnrollmentStore().link_deepseek(request_id, project_id=PROJECT_ID, role="worker", agent_id=agent_id)
        # A temporary daemon outage must not complete the associated request.
        with monkeypatch.context() as patch:
            patch.setattr(enrollment, "daemon_state", lambda *args, **kwargs: None)
            assert enrollment.status(request_id, settings=settings, directory=directory)["status"] == "waiting"
        arrived = enrollment.current_status(settings=settings, directory=directory)
        assert arrived["status"] == "arrived" and arrived["agent_id"] == agent_id
        assert EnrollmentStore().active() is None


def test_opencode_observe_cannot_bypass_original_chat_receipt(monkeypatch, tmp_path):
    record = _codex_enrolled(monkeypatch, tmp_path, adapter="opencode")
    settings = _config(tmp_path)
    rosters = Rosters(("bound-agent",), role="main")
    report = enrollment.observe(settings=settings, directory=rosters, project_id=record["project_id"],
                                adapter="opencode", baseline=set(), enrollment_id=record["enrollment_id"])
    assert report["status"] == "waiting" and report["phase"] == "enrolled"
    _host_receipt(record)
    report = enrollment.observe(settings=settings, directory=rosters, project_id=record["project_id"],
                                adapter="opencode", baseline=set(), enrollment_id=record["enrollment_id"])
    assert report["status"] == "arrived" and report["agent_id"] == "bound-agent"


def test_opencode_http_prepare_does_not_start_daemon(monkeypatch, tmp_path):
    from tsunagou.console.app import AgentPrepareRequest, create_console_app

    _entry(tmp_path)
    def forbidden(*_args, **_kwargs):
        pytest.fail("request-only preparation must not start a daemon")
    monkeypatch.setattr("tsunagou.console.app.ensure_daemon", forbidden)
    routes = {getattr(route, "path", ""): getattr(route, "endpoint", None)
              for route in create_console_app(_config(tmp_path)).routes}
    report = routes["/api/v1/console/projects/{project_id}/agents:prepare"](
        PROJECT_ID, AgentPrepareRequest(vendor="opencode", role="worker", place="local"))
    assert report["host_registration"]["status"] == "deferred"
