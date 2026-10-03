"""Turning "add an Agent" into a handoff a real host conversation can claim.

Not every host can be enrolled the same way, and the page must not pretend
otherwise. A host is in exactly one of three states (``enroll_mode``):

* ``console`` — this console can finish the handoff. Codex stores only a private
  selection and its real chat claims it later; OpenCode gets a ticket bound to a
  session name the console hands out, and the person opens that named session.
* ``in_host`` — the host enrolls from inside its own chat (DeepSeek Harness).
  Nothing is signed or queued here: the page says where to say the one sentence.
* ``unsupported`` — no implementation yet; the page says so instead of queueing.

The daemon owns the Agent: it issues the one-time ticket, and it enrolls whoever
redeems that ticket through ``agent.enroll``. What no daemon can do is the local
half of the job — write the private ticket file, describe how to launch the bridge,
and put that description inside the host's own configuration. Every one of those is
a local side effect on the person's own machine, which is why the console (a local
process, the same kind of thing as the CLI) does them and the page never does:

* **the secret never goes to the page.** The ticket's plaintext comes back from the
  daemon and goes straight into a private file (0600/ACL); the answer carries paths
  and statuses only. A page that held an enrollment secret would be one browser
  extension away from handing somebody an Agent identity.
* **an unknown host is not guessed at.** The per-host command comes from the host
  table (``platform/host_registration.py``); a host with no command yet is reported
  as unsupported, together with the command a person would run by hand.

The last step still belongs to a person: only the host can load its own configuration
and spawn the bridge that redeems the ticket. So this prepares everything and says
what is left to do — it never claims an Agent exists.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from tsunagou.console.agents import AgentDirectory, _host_label
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.errors import ConsoleError
from tsunagou.console.profile import load_profile, update_profile
from tsunagou.console.projects import ProjectEntry, daemon_state, find
from tsunagou.console.proxy import forward
from tsunagou.platform import host_registration
from tsunagou.platform.bridge_files import (
    BRIDGE_DIRECTORY,
    bridge_entry_path,
    profile_identity,
    read_bridge_config,
    write_bridge_config,
    write_ticket_file,
)
from tsunagou.platform.enrollment_store import EnrollmentStore

TICKET_COMMAND = "agent.ticket.create.user"
DELIVERY_ACK = "/api/v1/credential-deliveries/{reference}/ack"
ROLES = ("worker", "main")
BUILD_COMMAND = "pnpm -C packages/bridge-server run build"
NEXT_STEP = (
    "重启或重载这个宿主窗口，让宿主读取新的 MCP 配置；"
    "该会话里的 bridge 会用票据文件自动兑换成一个 Agent（首次调用 context__project_read 即完成）。"
)

# 接入只有三种状态，页面按它说真话（见模块说明）。中间层能替宿主把票和配置备好，
# 叫作 console；只能在宿主自己的聊天里接入，叫作 in_host；还没做，就是 unsupported。
CONSOLE_MODE = "console"
IN_HOST_MODE = "in_host"
UNSUPPORTED_MODE = "unsupported"


def enroll_mode(host: host_registration.Host) -> str:
    """Can this console finish this host's handoff, or is it somebody else's step?

    It answers the page's question — "点下一步会发生什么" — not "有没有注册命令":
    a host whose configuration is a file we write counts just as much as one whose
    CLI we run, and a host that enrolls inside its own chat is neither.
    """

    if host.enroll_in_host:
        return IN_HOST_MODE
    if host.commands is not None or host.config_write is not None:
        return CONSOLE_MODE
    return UNSUPPORTED_MODE


def _enroll_note(host: host_registration.Host, mode: str) -> str:
    """One sentence a person can act on; empty when there is nothing to explain."""

    if mode == IN_HOST_MODE:
        return host.enroll_in_host
    if mode == UNSUPPORTED_MODE:
        return host.note or "这个宿主的 MCP 注册还没实现，暂时不能从网页接入。"
    return ""

# 票据默认活 10 分钟（authority.issue_ticket），多留一点余量再判过期。
ENROLLMENT_TTL_SECONDS = 900.0
#: 跨机器那张邀请：从主机签票到远端导入、开窗口，全在一个"传密码"式的时间窗里完成。
REMOTE_INVITE_TTL_SECONDS = 600


def _registry() -> dict[str, Any]:
    """The protocol bundle the envelope must name; the daemon validates it."""

    raw = files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8")
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ConsoleError("protocol_registry_invalid", status=500)
    return loaded


def _command_path(command: str) -> str:
    return f"/api/v1/commands/{command}"


def profile_name(name: str) -> str:
    """A path-safe conversation name, derived from whatever the person typed.

    A profile names one local slot, so two different names must not land on the same
    one. Sanitising alone cannot promise that ("主 Agent" and "子 Agent" both lose
    their Chinese and would become the same word), so whenever the safe spelling is
    not the name itself, a short digest of the *whole* name is appended: readable
    prefix for the person, and equality for the machine.
    """

    text = (name or "").strip()
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")
    if text and safe != text:
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        return f"{safe[:32]}-{digest}" if safe else f"profile-{digest}"
    return safe[:40] if safe else "current"


def _ticket(*, endpoint: dict[str, Any], token: str | None, installation_id: str,
            conversation_id: str, role: str, ttl_seconds: int | None = None) -> dict[str, Any]:
    """Ask the daemon for a one-time ticket; the plaintext stays inside this process."""

    registry = _registry()
    body = json.dumps({
        # 每次一个新的幂等键：重试必须拿到**新**票据（已兑换/已投递的票据重放只会回安全收据）。
        "command_id": uuid.uuid4().hex,
        "protocol_version": registry.get("protocol_version"),
        "schema_bundle_digest": registry.get("schema_bundle_digest"),
        "payload": {
            "installation_id": installation_id,
            "role": role,
            "conversation_evidence": {"conversation_id": conversation_id},
            **({"ttl_seconds": int(ttl_seconds)} if ttl_seconds else {}),
        },
    }).encode("utf-8")
    answer = forward(
        endpoint=endpoint, method="POST", path=_command_path(TICKET_COMMAND),
        body=body, token=token, timeout=15.0,
    )
    payload = _json_or_none(answer.body)
    if answer.status != 200:
        code = _code_of(payload) or f"http_{answer.status}"
        raise ConsoleError(code, status=answer.status, detail={"command": TICKET_COMMAND})
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("secret"), str) or not result["secret"]:
        raise ConsoleError("ticket_unavailable", status=502, detail={"command": TICKET_COMMAND})
    return result


def _ack(*, endpoint: dict[str, Any], token: str | None, reference: str) -> None:
    """The ticket is already durably saved; a lost acknowledgement cannot free it."""

    try:
        forward(
            endpoint=endpoint, method="POST",
            path=DELIVERY_ACK.format(reference=reference), token=token, timeout=10.0,
        )
    except ConsoleError:
        pass


def _json_or_none(raw: bytes) -> Any:
    try:
        return json.loads(raw or b"null")
    except json.JSONDecodeError:
        return None


def _code_of(payload: Any) -> str | None:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        return str(detail["code"])
    return detail if isinstance(detail, str) else None


@dataclass
class Enrollment:
    """One pending "add an Agent", and how to tell whether it arrived.

    Nothing is *created* by preparing: a ticket is a promise. The Agent exists only
    after the host has loaded the new MCP entry and the bridge inside it has redeemed
    the ticket, which is a thing a person has to trigger by opening (or reloading)
    that window. So the console keeps the question — "has a new Agent shown up in this
    project?" — and answers it by comparing the project's roster against the one it
    saw when the ticket was issued.
    """

    enrollment_id: str
    project_id: str
    adapter: str
    label: str
    profile: str
    nickname: str
    role: str
    known_agents: frozenset[str]
    expires_at: float
    ticket_file: str = ""
    blind: bool = False
    cancelled: bool = False
    arrived_agent_id: str | None = None
    store_id: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "enrollment_id": self.enrollment_id,
            "project_id": self.project_id,
            "vendor": self.adapter,
            "label": self.label,
            "role": self.role,
            "profile": self.profile,
            "nickname": self.nickname,
            "agent_id": self.arrived_agent_id,
            "expires_in_seconds": max(0, int(self.expires_at - time.time())),
            **self.extras,
        }


_ENROLLMENTS: dict[str, Enrollment] = {}
_ENROLLMENT_LOCK = threading.Lock()


def _remember(record: Enrollment) -> None:
    with _ENROLLMENT_LOCK:
        _ENROLLMENTS[record.enrollment_id] = record


def forget_all() -> None:
    """Drop every pending enrollment — for tests, and for a console being restarted."""

    with _ENROLLMENT_LOCK:
        _ENROLLMENTS.clear()


def forget_project(project_id: str) -> list[str]:
    """Drop the enrollments waiting on one project, and take their tickets back out.

    Deleting a whole project has to clean these up too: a ticket that outlives its
    project would let a host bridge enroll into a project nobody can see any more.
    Returns the enrollment ids that were dropped.
    """

    wanted = str(project_id or "").strip()
    with _ENROLLMENT_LOCK:
        dropped = [record for record in _ENROLLMENTS.values() if record.project_id == wanted]
        for record in dropped:
            _ENROLLMENTS.pop(record.enrollment_id, None)
    for record in dropped:
        if not record.ticket_file:
            continue
        try:
            Path(record.ticket_file).unlink(missing_ok=True)
        except OSError:  # pragma: no cover - a locked ticket file is not worth failing the delete
            continue
    durable = EnrollmentStore()
    persisted = durable.forget_project(wanted) if durable.path.exists() else []
    return [record.enrollment_id for record in dropped] + persisted


def pending(enrollment_id: str) -> Enrollment:
    with _ENROLLMENT_LOCK:
        record = _ENROLLMENTS.get(enrollment_id)
    if record is None:
        raise ConsoleError("enrollment_not_found", status=404, detail={"enrollment_id": enrollment_id})
    return record


def prepare(
    entry: ProjectEntry, endpoint: dict[str, Any], *, vendor: str, role: str,
    nickname: str = "", profile: str | None = None, mode: str = "attach",
    token: str | None = None, directory: AgentDirectory | None = None,
    place: str = "local", conversation_id: str = "",
) -> dict[str, Any]:
    """Prepare one host conversation to become an Agent, and say what is left to do.

    The order matters: everything that can refuse without side effects is checked
    first (host known, bridge built), so a refusal never leaves a live ticket behind.

    ``profile`` is the machine's name for this local slot, not the person's name for
    the Agent: the nickname is only remembered here and written into the user profile
    once the Agent it belongs to actually exists.
    """

    host = host_registration.host_for(vendor)
    if host is None:
        raise ConsoleError(
            "unknown_host_vendor", detail={"vendor": vendor, "known": sorted(host_registration.HOSTS)},
        )
    if role not in ROLES:
        raise ConsoleError("invalid_requested_role", detail={"role": role, "roles": list(ROLES)})
    if mode not in {"attach", "launch"}:
        raise ConsoleError("invalid_mode", detail={"mode": mode})
    entry_path = bridge_entry_path()
    if not entry_path.is_file():
        raise ConsoleError(
            "bridge_not_built", status=503,
            detail={"entry": str(entry_path), "build": BUILD_COMMAND},
        )

    enrollment_mode = enroll_mode(host)
    if enrollment_mode == UNSUPPORTED_MODE:
        # 给一个兑不了的宿主签票比拒绝更糟：它看起来像有进展，最后只会等成"票过期了，重来吧"。
        raise ConsoleError(
            "host_enroll_not_available", detail={
                "vendor": host.adapter, "label": host.label, "enroll_mode": enrollment_mode,
                "note": _enroll_note(host, enrollment_mode),
            },
        )
    if place == "network":
        return _prepare_network(
            entry, endpoint, host=host, entry_path=entry_path, role=role, nickname=nickname,
            profile=profile, token=token, conversation_id=conversation_id, directory=directory,
        )

    if enrollment_mode == IN_HOST_MODE:
        # 这条路的票由那条聊天里的 CLI 以用户身份自己签（身份来自宿主给的会话 id），
        # 控制台不签票、不写宿主配置。但"用户要让谁接入哪个项目"这个决定必须留在机器上：
        # 聊天里说"请接入 Tsunagou"的那一刻，它只有自己的会话 id 和工作目录，而工作目录
        # 常常不是协调仓库 —— 唯一能回答"接哪个项目、什么角色"的就是这条记录。
        #
        # 顺带把"现在名单上有谁"记下来：这条路没有票也没有回执可等，等到了没有，只能靠
        # "比这份多出来的那个席位"来认（页面刷新过、控制台重启过也一样认得出）。
        store_id = _record_selection(
            entry=entry, adapter=host.adapter, role=role, nickname=nickname,
            baseline=_roster_ids(directory, entry, endpoint),
        )
        return {
            "status": "prepared", "enrollment_id": store_id, "store_id": store_id,
            "project_id": entry.project_id, "vendor": host.adapter, "label": host.label,
            "role": role, "nickname": (nickname or "").strip(), "profile": "",
            "mode": mode,
            "host_registration": {
                "adapter": host.adapter, "label": host.label, "status": "in_host",
                "note": _enroll_note(host, enrollment_mode),
            },
            "next": _enroll_note(host, enrollment_mode),
        }

    if host.adapter == "codex":
        try:
            intent = EnrollmentStore().create(
                project_id=entry.project_id, project_root=entry.path.resolve(), role=role, nickname=nickname,
            )
        except RuntimeError as exc:
            error = _intent_error(exc)
            if str(exc) == "enrollment_already_pending":
                active = EnrollmentStore().active()
                if active is not None:
                    error.detail["enrollment"] = {**_intent_public(active), "status": "waiting"}
                error.detail["note"] = (
                    "已有其他项目或角色的接入申请，请先处理当前申请。"
                    "未认领的申请可取消；已认领的申请需在原 Codex 聊天继续完成。"
                )
            raise error from exc
        return {
            **_intent_public(intent), "status": "prepared", "mode": mode,
            "host_registration": {
                "adapter": "codex", "label": host.label, "status": "deferred", "name": "tsunagou",
                "note": "等待目标 Codex 聊天认领；项目和角色已保存，认领时才签票并绑定真实聊天。",
            },
            "next": "在要接入的 Codex 桌面聊天中说：请接入 Tsunagou。首次安装需先加载 Tsunagou Skill 和共享 MCP。",
        }

    # 名单要在**记下这次选择之前**取：这些记录没有票、没有回执，等到没到只能靠"比这份多
    # 出来的那个席位"来认，而这份基线必须和记录一起落盘（页面刷新、控制台重启都得还在）。
    before = directory.roster(entry.project_id, entry.path, endpoint, force=True) if directory else None
    known_agents = frozenset(agent["agent_id"] for agent in before.agents) if before else frozenset()

    # 其余能由页面办完的宿主（OpenCode）：也把这次选择记进机器级记录 —— 它让"不在项目
    # 目录里开会话"的那条聊天也查得到该接哪个项目，并且让"同一时刻只有一条"这件事在
    # 控制台重启后依然成立（内存里的记录活不过重启）。
    store_id = _record_selection(
        entry=entry, adapter=host.adapter, role=role, nickname=nickname,
        baseline=tuple(sorted(known_agents)),
    )
    conversation = profile_name(profile) if profile else uuid.uuid4().hex[:12]
    destination = (entry.path / BRIDGE_DIRECTORY / f"{host.adapter}-{conversation}").resolve()
    # OpenCode 认的是"开会话时用的那个名字"，而这个名字可以由接入方先定：票绑它，
    # 人再用同一个名字开会话，两边的身份就对得上了（其他宿主没有这一步，见 enroll_mode）。
    chosen_session = f"ses_{conversation}" if host.adapter == "opencode" else None
    installation_id, conversation_id = profile_identity(
        destination, host.adapter, conversation, preferred_id=chosen_session,
    )

    issued = _ticket(
        endpoint=endpoint, token=token, installation_id=installation_id,
        conversation_id=conversation_id, role=role,
    )
    ticket_path = write_ticket_file(
        installation_id, conversation_id, str(issued["secret"]), destination / "ticket.json", role,
    )
    reference = issued.get("delivery_ref")
    if isinstance(reference, str) and reference:
        _ack(endpoint=endpoint, token=token, reference=reference)

    bridge_config = write_bridge_config(
        adapter=host.adapter, mode=mode, installation_id=installation_id, output_dir=destination,
        ticket_path=ticket_path,
        daemon_url=str(endpoint.get("url") or ""),
        daemon_state_dir=str(endpoint.get("state_dir") or (entry.path / ".tsunagou" / "local")),
        project_root=entry.path,
    )
    registration = host_registration.register(
        host.adapter, profile=conversation, project_root=entry.path,
        bridge=read_bridge_config(bridge_config),
    )
    record = Enrollment(
        enrollment_id=uuid.uuid4().hex,
        project_id=entry.project_id, adapter=host.adapter, label=host.label,
        profile=conversation, nickname=(nickname or "").strip(), role=role,
        known_agents=known_agents, expires_at=time.time() + ENROLLMENT_TTL_SECONDS,
        ticket_file=ticket_path.as_posix(), blind=before is None, store_id=store_id,
    )
    _remember(record)
    # 名字是我们发的，所以"下一步做什么"也只能由这里说清 —— 页面照抄这句话。
    next_step = (
        f"在这个项目里用会话名 {conversation_id} 打开 {host.label}"
        f"（opencode --session {conversation_id}），reload 一次让 MCP 配置生效；"
        "该会话首次读取项目上下文即完成接入。"
        if chosen_session else NEXT_STEP
    )
    return {
        "status": "prepared",
        "installation_id": installation_id,
        "mode": mode,
        "bridge_dir": destination.as_posix(),
        "bridge_config": bridge_config.as_posix(),
        "ticket_file": ticket_path.as_posix(),
        "host_registration": registration.public(),
        "next": next_step,
        **record.public(),
    }


def _requested_role_landed(agent: dict[str, Any], requested_role: str) -> bool:
    """Is this newcomer actually the Agent the ticket asked for, and is it ready?

    Both halves are required and they are independent facts:

    * ``session_status == "ready"`` -- the session proved every admission capability.
      A degraded session is already in the roster while being unable to work at all.
    * ``role == requested_role`` -- ``main`` is not something a session has by existing;
      the daemon appoints it right after a *ready* enrollment. Until that happens the
      Agent keeps the default ``worker`` role.

    Reading either half alone is what produced "主 Agent 已接入" for a session that had
    no role and no base grant.
    """

    return (
        agent.get("session_status") == "ready"
        and agent.get("role") == requested_role
    )


def _intent_error(error: RuntimeError) -> ConsoleError:
    code = str(error).split(":", 1)[0]
    return ConsoleError(code, status=404 if code == "enrollment_not_found" else 409)


def _intent_public(record: dict[str, Any]) -> dict[str, Any]:
    """Allowlist page fields: raw thread, receipt paths and credentials stay private."""
    phase = "connecting" if record["status"] == "claimed" else record["status"]
    return {
        "enrollment_id": record["enrollment_id"], "project_id": record["project_id"],
        "vendor": record["adapter"], "label": _host_label(str(record["adapter"])),
        "role": record["requested_role"],
        "profile": record["enrollment_id"][:12], "nickname": record["nickname"],
        "agent_id": record.get("agent_id") if record["status"] == "arrived" else None,
        "expires_in_seconds": max(0, int(record["expires_at"] - time.time())),
        "phase": phase,
    }


def _roster_ids(
    directory: AgentDirectory | None, entry: ProjectEntry, endpoint: dict[str, Any] | None,
) -> tuple[str, ...]:
    """Who sits in this project right now (empty when that cannot be answered).

    Empty means "unknown", not "nobody": the console writes no baseline then, and the
    waiting judgement adopts one from the first roster it can read (see ``_watch_roster``)
    rather than risk calling a seat that was there all along a new arrival.
    """

    if directory is None or not isinstance(endpoint, dict) or not endpoint.get("running"):
        return ()
    lineup = directory.roster(entry.project_id, entry.path, endpoint, force=True)
    if lineup is None:
        return ()
    return tuple(sorted(str(agent.get("agent_id") or "") for agent in lineup.agents if agent.get("agent_id")))


def _record_selection(
    *, entry: ProjectEntry, adapter: str, role: str, nickname: str,
    baseline: tuple[str, ...] = (),
) -> str:
    """Write the person's decision into the machine-level slot, and return its id.

    This is the record an in-chat entry point reads to answer "which coordination root,
    which role" without asking anybody (see ``platform/enrollment_store.py``). It holds
    no credential: the ticket either does not exist yet (Codex signs it at claim time)
    or is signed by the chat itself (the hosts that enroll in their own chat).

    ``baseline`` is who already sat in this project when the request was made: these
    records have no receipt to wait for, so "who is new" is the only arrival evidence
    there will ever be — and it has to survive a console restart or a page reload.
    """

    store = EnrollmentStore()
    try:
        record = store.create(
            project_id=entry.project_id, project_root=entry.path.resolve(),
            role=role, nickname=nickname, adapter=adapter, baseline=baseline,
        )
    except RuntimeError as exc:
        error = _intent_error(exc)
        if str(exc) == "enrollment_already_pending":
            active = store.active()
            if active is not None:
                error.detail["enrollment"] = {**_intent_public(active), "status": "waiting"}
            error.detail["note"] = (
                "已有其他项目或角色的接入申请，请先处理当前申请。"
                "未认领的申请可取消；已认领的申请需在原聊天继续完成。"
            )
        raise error from exc
    return str(record["enrollment_id"])


def _intent_or_none(enrollment_id: str) -> dict[str, Any] | None:
    store = EnrollmentStore()
    if not store.path.exists():
        return None
    try:
        return store.get(enrollment_id)
    except RuntimeError as exc:
        if str(exc) == "enrollment_not_found":
            return None
        raise _intent_error(exc) from exc


def _receipt_matches(record: dict[str, Any], agent: dict[str, Any]) -> bool:
    try:
        path = Path(record["receipt_file"])
        if path.is_symlink():
            return False
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(receipt, dict) or receipt.get("format_version") != 1:
        return False
    expected = {
        "enrollment_id": record["enrollment_id"], "thread_id": record.get("thread_id"),
        "project_id": record["project_id"], "agent_id": record.get("agent_id"),
        "role": record["requested_role"],
    }
    epoch = receipt.get("connection_epoch")
    return (
        all(value and receipt.get(key) == value for key, value in expected.items())
        and isinstance(receipt.get("session_id"), str) and bool(receipt["session_id"])
        and isinstance(receipt.get("observed_at"), str) and bool(receipt["observed_at"])
        and type(epoch) is int and epoch > 0
        and type(agent.get("connection_epoch")) is int and epoch == agent["connection_epoch"]
        and agent.get("agent_id") == record.get("agent_id")
        and _requested_role_landed(agent, record["requested_role"])
    )


def _waiting_note(record: dict[str, Any]) -> str:
    """What this wait is waiting for, in the words of the host it belongs to."""

    label = _host_label(str(record.get("adapter") or ""))
    if str(record.get("adapter") or "") == "codex":
        return "已登记，等待原 Codex 聊天调用项目上下文并确认角色和就绪状态。"
    return f"已登记，等待 {label} 那边完成接入：它一出现在名单里且角色正确，这里就会显示已接入。"


def _watch_roster(
    record: dict[str, Any], *, lineup: Any, settings: ConsoleConfig, waiting: dict[str, Any],
) -> dict[str, Any]:
    """Judge a record that has no receipt to wait for.

    Three outcomes: arrived (the console closes the record and says so), wrong role (the
    seat showed up with the other role — say it plainly and leave the record for whoever
    it is really for), or waiting (including "the baseline is unknown", which gets written
    down here and judged from the next poll on).
    """

    adapter = str(record.get("adapter") or "")
    enrollment_id = str(record["enrollment_id"])
    store = EnrollmentStore()
    try:
        known = load_profile(settings.profile_path)["agents"]
        if record.get("baseline") is None:
            # 申请时读不到名单（daemon 还没起）：把"现在"当作基线写下来，免得把已经在那儿的人
            # 当成刚到的人。下一次轮询起才作数 —— 没记下来之前，一律按还没到处理。
            store.note_baseline(enrollment_id, agent_ids=[str(a.get("agent_id") or "") for a in lineup.agents])
            return {**waiting, "note": "已经记下这个项目现在有谁；那边一出现就会认出来。"}
        seat = _attributed_seat(
            lineup, adapter=adapter, baseline=record["baseline"], known=known,
            awaiting=str(record.get("requested_role") or ""),
        )
        if seat["state"] == "arrived":
            arrived = store.observe_arrival(enrollment_id, agent_id=seat["agent_id"])
            return {
                **_intent_public(arrived), "status": "arrived",
                "agent": {"agent_id": seat["agent_id"], "role": seat["role"],
                          "session_status": seat["session_status"]},
            }
        if seat["state"] == "wrong_role":
            return {
                **waiting,
                "pending": {"agent_id": seat["agent_id"], "role": seat["role"],
                            "session_status": seat["session_status"]},
                "note": seat["note"],
            }
    except RuntimeError as exc:
        raise _intent_error(exc) from exc
    return {**waiting, "note": _waiting_note(record)}


def _intent_status(record: dict[str, Any], *, settings: ConsoleConfig, directory: AgentDirectory) -> dict[str, Any]:
    public = _intent_public(record)
    phase = record["status"]
    if phase in {"arrived", "cancelled", "expired"}:
        result = {**public, "status": phase}
        if phase == "expired":
            result["note"] = "接入申请已过期，请在前端重新准备。"
        return result
    if phase == "forgotten":
        return {**public, "status": "cancelled", "note": "项目已从控制台移除，这次接入申请已失效。"}
    waiting = {**public, "status": "waiting"}
    # 有没有回执可等，决定这条申请的"到了"由什么判定：
    #   · Codex 的申请：那个聊天认领（claimed/enrolled）后由桥写回执，主机核对回执；
    #   · 宿主自己接入（in_host）与跨机器邀请：主机这边**什么都不写**，没有票可问、没有回执
    #     可等 —— 唯一的证据是名单里那个"申请时不在、现在出现、身份与角色都对得上"的席位。
    # 判据是记录里有没有**基线**（那两条路申请时会写下"当时名单上有谁"），加上宿主本身是否
    # 走回执（只有 codex 走）。两者共用 _attributed_seat，页面那条 observe 出口不会各说各话。
    watched = "baseline" in record or str(record.get("adapter") or "") != "codex"
    if phase == "failed":
        return {**waiting, "error": record.get("error"),
                "note": (f"接入遇到问题，请在刚才的 {_host_label(str(record.get('adapter') or ''))} 聊天重试；"
                         "申请仍绑定那个聊天。")}
    if phase == "pending" and not watched:
        return {**waiting, "note": "等待 Codex 聊天认领：请接入 Tsunagou。"}
    if phase == "claimed":
        return {**waiting, "note": "目标 Codex 聊天已认领，正在完成接入。"}
    try:
        entry = find(settings, record["project_id"])
    except ConsoleError:
        return {**waiting, "note": "暂时找不到这个项目，等它回来了再看。"}
    if entry.path.resolve() != Path(record["project_root"]).resolve():
        return {**waiting, "note": "项目目录与接入申请不一致，请恢复原项目目录。"}
    endpoint = daemon_state(entry.path, probe=True)
    lineup = (
        directory.roster(record["project_id"], entry.path, endpoint, require_fresh=True)
        if endpoint and endpoint.get("running") else None
    )
    if lineup is None:
        return {**waiting, "note": "暂时读不到这个项目的 Agent 名单。"}
    if watched:
        return _watch_roster(record, lineup=lineup, settings=settings, waiting=waiting)
    candidate = next((a for a in lineup.agents if a.get("agent_id") == record.get("agent_id")), None)
    if candidate is None or not _receipt_matches(record, candidate):
        return {**waiting, "note": _waiting_note(record)}
    try:
        arrived = EnrollmentStore().mark_arrived(record["enrollment_id"])
    except RuntimeError as exc:
        raise _intent_error(exc) from exc
    try:
        # 厂商按这条申请自己的宿主写，不写死 Codex：写错了会让这个 Agent 以后一直显示成
        # 另一家的图标（页面就是按档案里的厂商取 logo 的）。
        update_profile(settings.profile_path, {"agents": {
            arrived["agent_id"]: {"nickname": arrived["nickname"],
                                  "vendor": _host_label(str(record.get("adapter") or ""))},
        }})
    except ValueError:
        pass
    return {**_intent_public(arrived), "status": "arrived"}


def current_status(*, settings: ConsoleConfig, directory: AgentDirectory) -> dict[str, Any]:
    """Recover the active wait after refresh, reconciling a completed host receipt."""
    try:
        active = EnrollmentStore().active()
    except RuntimeError as exc:
        raise _intent_error(exc) from exc
    if active is None:
        return {"status": "none"}
    return _intent_status(active, settings=settings, directory=directory)


def status(enrollment_id: str, *, settings: ConsoleConfig, directory: AgentDirectory) -> dict[str, Any]:
    """Has that Agent arrived yet? — the question the waiting overlay keeps asking.

    A project whose roster cannot be read answers ``waiting``: "not yet" and "cannot
    tell" are different things, and the waiting overlay is allowed to keep waiting
    rather than declare a failure it cannot see.
    """

    intent = _intent_or_none(enrollment_id)
    if intent is not None:
        return _intent_status(intent, settings=settings, directory=directory)
    record = pending(enrollment_id)
    if record.arrived_agent_id:
        return {"status": "arrived", **record.public()}
    if record.cancelled:
        return {"status": "cancelled", **record.public()}
    if time.time() > record.expires_at:
        return {
            "status": "expired", **record.public(),
            "note": (
                "票的有效期过了，但那个会话已经连上了，只是还没就位 —— "
                "在那边让它读一次项目上下文就能完成接入，不用重新添加。"
                if record.extras.get("settling_agent_id") else
                "票据有效期已过，请重新添加；上一次的票据已经作废。"
            ),
        }
    entry = None
    try:
        entry = find(settings, record.project_id)
    except ConsoleError:
        # 项目找不到了（被移走/删了）：等下去也等不到，但这不是"没连上"，
        # 所以照实说是哪一种，别让遮罩一直转。
        return {"status": "waiting", **record.public(), "note": "暂时找不到这个项目，等它回来了再看。"}
    endpoint = daemon_state(entry.path, probe=True)
    lineup = None
    if endpoint is not None and endpoint.get("running"):
        lineup = directory.roster(record.project_id, entry.path, endpoint)
    if lineup is None or record.blind:
        return {
            "status": "waiting", **record.public(),
            "note": "暂时读不到这个项目的 Agent 名单（daemon 没起或没答），先按还没到处理。",
        }
    arrived = [agent for agent in lineup.agents if agent["agent_id"] not in record.known_agents]
    if not arrived:
        return {"status": "waiting", **record.public()}
    # "到了"和"就位"是两件事，这份等待要的是后者。
    #
    # 名单里多出一个人只说明那个会话兑换了那张票。它还要：**会话就绪**（准入能力都被
    # 证明过），而且**角色已经落到这张票要求的那一个**。要紧的是后者不是因为别的窗口
    # 先兑换了票，而是因为主 Agent 的任命是兑换之后、由 daemon 判定就绪那一步顺手做的
    # —— 首次接入必然还不就绪，所以"人数变了"会把一个**还没有角色的普通成员**报成
    # "主 Agent 已接入"，而按票要求核对角色就能挡住它（顺带也挡住"另一个窗口先兑换了
    # 子 Agent 那张票"这种情形）。
    settled = [agent for agent in arrived if _requested_role_landed(agent, record.role)]
    if not settled:
        candidate = arrived[0]
        # 记下"人来了但没就位"，这样票过期时能说清该做什么（见上面 expired 分支）。
        record.extras["settling_agent_id"] = candidate["agent_id"]
        return {
            "status": "waiting", **record.public(),
            "pending": {
                "agent_id": candidate["agent_id"],
                "role": candidate["role"],
                "session_status": candidate["session_status"],
                "missing_admission": list(candidate["missing_admission"]),
            },
            "note": "已经连上，但还没就位。",
        }
    record.arrived_agent_id = settled[0]["agent_id"]
    _close_selection(record, arrived_agent_id=record.arrived_agent_id)
    if record.nickname or record.label:
        # 昵称跟着 Agent 走：名字只有等这个人真的存在了才能落到它头上。
        # 没有昵称也要登记一行：厂商（label）是这台机器知道的事实，界面上"按厂商
        # 显示 logo"就靠它 —— 丢了它，所有 Agent 都只能显示默认图标。
        patch: dict[str, Any] = {"agents": {record.arrived_agent_id: {"nickname": record.nickname, "vendor": record.label}}}
        try:
            update_profile(settings.profile_path, patch)
        except ValueError as exc:  # pragma: no cover - only a hand-edited profile gets here
            record.extras["nickname_error"] = str(exc)
    return {"status": "arrived", **record.public()}


def _attributed_seat(
    lineup: Any, *, adapter: str, baseline: Iterable[str], known: Mapping[str, Any], awaiting: str,
) -> dict[str, Any]:
    """Which seat this request was waiting for — one rule, two callers.

    A seat counts only when all three hold: it was **not** in ``baseline`` (who was there
    when the request was made), the profile knows it came from *this* host product
    (``agent connect`` writes that beside the bridge folder, before the bridge ever
    enrolls), and its role is the one the request asked for. Anything else is not an
    arrival: handing one host somebody else's enrollment is worse than waiting.

    One exception, and only one: a seat that **self-reports a machine** arrived through
    an invitation. A cross-machine invitation leaves *nothing* on this machine by design,
    so there is no enrollment file here to learn a vendor from — the machine name the
    daemon recorded at redeem time is the only attribution that exists. A vendor the
    profile *does* know still has to match, so this never overrides real evidence.

    ``observe`` (the page watching an in-chat enrollment) and ``_intent_status`` (the
    console answering the same question for the same record) both judge with this, so the
    page and the console can never disagree about whether somebody arrived.
    """

    label = _host_label(adapter)
    for agent in lineup.agents:
        agent_id = str(agent.get("agent_id") or "")
        if not agent_id or agent_id in baseline:
            continue
        vendor = str((known.get(agent_id) or {}).get("vendor") or "").strip()
        remote = bool(str(agent.get("machine") or "").strip())
        if vendor:
            if vendor != label:
                continue
        elif not remote:
            continue
        role = str(agent.get("role") or "")
        session = str(agent.get("session_status") or "")
        if awaiting and role != awaiting:
            # 连上了，但不是这次申请要的那个角色（页面选主 Agent、那边却以子 Agent 接入）。
            # 如实说，不报成功，也不替它把记录收掉 —— 真正该来的那个还能用它。
            return {
                "state": "wrong_role", "agent_id": agent_id, "role": role, "session_status": session,
                "note": (
                    "有个席位连上了，但它的角色是"
                    + ("子 Agent" if role == "worker" else ("主 Agent" if role == "main" else role))
                    + "，不是这次申请的" + ("主 Agent" if awaiting == "main" else "子 Agent")
                    + "。请在那边以正确身份重新接入。"
                ),
            }
        return {"state": "arrived", "agent_id": agent_id, "role": role, "session_status": session}
    return {"state": "waiting"}


def observe(
    *, settings: ConsoleConfig, directory: AgentDirectory, project_id: str, adapter: str,
    baseline: set[str] | frozenset[str], enrollment_id: str = "",
) -> dict[str, Any]:
    """Has a host that enrolls inside its own chat shown up yet?

    ``in_host`` has no ticket to ask about: the CLI running in that chat signs its own,
    bound to the conversation identity the host handed it (``DSH_SESSION_ID``), so there
    is nothing here to prepare, remember or void. The console can only *watch* — and it
    watches for something it can prove: a roster seat that was not in ``baseline``
    (what the page saw when it started waiting) whose vendor the profile learned from an
    enrollment file (``.tsunagou/bridges/<adapter>-*``, or the onboarding folder).
    That evidence is written by ``agent connect`` before the bridge ever enrolls, so it
    is already there when the seat appears.

    A new seat nobody can attribute is **not** an arrival: this answers ``waiting``
    rather than hand this host somebody else's enrollment. Asking twice changes nothing,
    so a page that lost its polling loop can ask again with the same baseline.

    ``enrollment_id`` (the machine-level record the console wrote for this attempt) is
    optional and only used to free that slot on arrival: the record says "somebody is
    joining this project as this role", and once the Agent is here it is no longer true.
    """

    wanted = str(adapter or "").strip().lower()
    if not wanted:
        raise ConsoleError("adapter_required", status=400)
    entry = find(settings, project_id)
    endpoint = daemon_state(entry.path, probe=True)
    if endpoint is None or not endpoint.get("running"):
        return {"status": "waiting", "adapter": wanted,
                "note": "这个项目的 daemon 还没起来：接入会在那条聊天里自己把它带起来，先按还没到处理。"}
    lineup = directory.roster(project_id, entry.path, endpoint, require_fresh=True)
    if lineup is None:
        return {"status": "waiting", "adapter": wanted, "note": "暂时读不到这个项目的 Agent 名单。"}
    known = load_profile(settings.profile_path)["agents"]
    awaiting = _awaiting_role(enrollment_id)
    seat = _attributed_seat(lineup, adapter=wanted, baseline=baseline, known=known, awaiting=awaiting)
    if seat["state"] == "arrived":
        if enrollment_id:
            try:
                EnrollmentStore().observe_arrival(enrollment_id, agent_id=seat["agent_id"])
            except RuntimeError:
                pass
        return {
            "status": "arrived", "adapter": wanted,
            "agent": {"agent_id": seat["agent_id"], "role": seat["role"],
                      "session_status": seat["session_status"]},
        }
    if seat["state"] == "wrong_role":
        return {
            "status": "waiting", "adapter": wanted,
            "pending": {"agent_id": seat["agent_id"], "role": seat["role"],
                        "session_status": seat["session_status"]},
            "note": seat["note"],
        }
    return {"status": "waiting", "adapter": wanted}


def _awaiting_role(enrollment_id: str) -> str:
    """Which role the pending record asks for ("" = unknown, e.g. no id passed)."""
    if not enrollment_id:
        return ""
    try:
        record = EnrollmentStore().get(enrollment_id)
    except RuntimeError:
        return ""
    return str(record.get("requested_role") or "")


def _close_selection(record: Enrollment, *, arrived_agent_id: str) -> None:
    """Free the machine-level slot once the console has *seen* this Agent arrive.

    The slot is what makes "which project" unambiguous, so it must not stay taken by an
    enrollment that is already finished — the person may be adding the next Agent a
    minute later. Failing here is not worth failing the answer: the record expires on
    its own, and ``observe``/``status`` will try again on the next poll.
    """

    if not record.store_id:
        return
    try:
        EnrollmentStore().observe_arrival(record.store_id, agent_id=arrived_agent_id)
    except RuntimeError:
        return


def _drop_selection(record: Enrollment) -> None:
    """The person stopped waiting: take the machine-level record back out too."""

    if not record.store_id:
        return
    try:
        EnrollmentStore().cancel(record.store_id)
    except RuntimeError:
        return


def _prepare_network(
    entry: ProjectEntry, endpoint: dict[str, Any], *, host: host_registration.Host, entry_path: Path,
    role: str, nickname: str, profile: str | None, token: str | None, conversation_id: str,
    directory: AgentDirectory | None = None,
) -> dict[str, Any]:
    """打一张给远端机器的邀请（页面这条路）。

    与本地接入的区别只有一个：**这台机器什么都不写**。票、身份和桥的启动配置都由远端那条
    命令写到它自己的机器上；这里产出一段可复制的内容交给人（票在里面，像传密码那样递过去）。

    身份分两种宿主：会话名由主机起的（OpenCode）这里直接起一个；只有它自己知道会话名的
    （Codex、DeepSeek Harness）必须先报号，`conversation_id` 就是那个号。
    """

    import tsunagou.platform.remote_invite as remote_invite

    if role != "worker":
        raise ConsoleError(
            "main_agent_must_be_local",
            detail={"note": "主 Agent 必须和协调中心在同一台机器上：跨机器那张邀请只能是子 Agent。"},
        )
    if not token:
        raise ConsoleError("control_credential_missing", detail={"note": "读不到本机控制凭据，无法签票。"})
    url = str(endpoint.get("advertised_url") or endpoint.get("url") or "")
    if not url:
        raise ConsoleError("daemon_endpoint_not_configured",
                           detail={"note": "协调中心没在跑，或还没有地址：先把它起来再发邀请。"})
    chosen_profile = (profile or "").strip() or (nickname or "").strip() or "remote"
    conversation = conversation_id.strip()
    if not conversation:
        if host.adapter != "opencode":
            raise ConsoleError(
                "conversation_id_required_for_this_host",
                detail={"vendor": host.adapter, "label": host.label,
                        "note": f"{host.label} 的会话名只有它自己知道：先在那台机器上报号，再把号填进来。"},
            )
        conversation = f"ses_{chosen_profile}"
    installation_id = f"{host.adapter}:{chosen_profile}"
    ttl = REMOTE_INVITE_TTL_SECONDS
    issued = _ticket(
        endpoint=endpoint, token=token, installation_id=installation_id,
        conversation_id=conversation, role="worker", ttl_seconds=ttl,
    )
    expires_at = time_utc_offset(ttl)
    invite = remote_invite.encode({
        "project_id": entry.project_id, "url": url, "adapter": host.adapter, "profile": chosen_profile,
        "installation_id": installation_id, "conversation_id": conversation, "role": "worker",
        "nickname": (nickname or "").strip(), "secret": str(issued["secret"]), "expires_at": expires_at,
    })
    store_id = _record_selection(
        entry=entry, adapter=host.adapter, role="worker", nickname=nickname,
        # 这台机器上什么都不写，所以"它到没到"唯一能靠的就是这份基线：比它多出来的那个
        # 席位。远端入席时会自己报机器名，判定据此把它认出来（见 _attributed_seat）。
        baseline=_roster_ids(directory, entry, endpoint),
    )
    return {
        "status": "invited", "invite": invite, "enrollment_id": store_id, "store_id": store_id,
        "project_id": entry.project_id, "vendor": host.adapter, "label": host.label,
        "role": "worker", "profile": chosen_profile, "conversation_id": conversation,
        "nickname": (nickname or "").strip(), "url": url,
        "expires_at": expires_at, "expires_in_seconds": max(0, ttl),
        "next": "把邀请内容发给那台机器上的人；他在那边跑一次 "
                "tsunagou agent import <邀请> 就完成接入，页面会自己等到他出现。",
    }


def time_utc_offset(seconds: int) -> str:
    """An ISO instant ``seconds`` from now, in the same shape the rest of the repo writes."""

    from tsunagou.shared_kernel.time import format_timestamp, now_ms

    stamp = format_timestamp(now_ms() + max(0, int(seconds)) * 1000)
    if not stamp:  # pragma: no cover - now_ms() is never None
        raise ConsoleError("invite_expiry_unavailable")
    return stamp


def cancel(enrollment_id: str, *, settings: ConsoleConfig) -> dict[str, Any]:
    """Stop an enrollment the person decided not to finish.

    Three things make it stop, and none of them is "pretend it never happened":
    the ticket file is deleted (a bridge cannot redeem a ticket it cannot read), the
    host entry is removed where we know how to remove one, and the record is marked
    cancelled so the waiting loop stops asking and a later arrival is not greeted with
    the nickname that belonged to this attempt.

    A host we cannot take the entry back out of is reported as such: the person then
    knows their host config still names a bridge that will never enroll.
    """

    intent = _intent_or_none(enrollment_id)
    if intent is not None:
        try:
            cancelled = EnrollmentStore().cancel(enrollment_id)
        except RuntimeError as exc:
            raise _intent_error(exc) from exc
        adapter = str(cancelled.get("adapter") or "codex")
        return {**_intent_public(cancelled), "status": "cancelled", "ticket_removed": False,
                # 只有 Codex 那条路会把条目写进宿主配置；其余宿主是"没有票可作废"的形态。
                "host_registration": {"adapter": adapter, "status": "unchanged",
                                      "name": "tsunagou" if adapter == "codex" else adapter}}
    record = pending(enrollment_id)
    if record.arrived_agent_id:
        raise ConsoleError(
            "enrollment_already_arrived", status=409,
            detail={"agent_id": record.arrived_agent_id,
                    "hint": "它已经连上了；这次等待到此为止，不用再取消。"},
        )
    record.cancelled = True
    ticket = Path(record.ticket_file) if record.ticket_file else None
    removed = False
    if ticket is not None and ticket.is_file():
        try:
            ticket.unlink()
            removed = True
        except OSError:
            removed = False
    root: Path | None = None
    try:
        root = find(settings, record.project_id).path
    except ConsoleError:
        root = None
    registration = (
        host_registration.unregister(
            record.adapter, profile=record.profile, project_root=root,
            # Cancel exactly the registration this enrollment created. The bridge
            # directory is derived the same way `prepare` derived it, so cancelling one
            # enrollment cannot delete a sibling conversation's launch configuration.
            bridge_dir=(root / BRIDGE_DIRECTORY / f"{record.adapter}-{record.profile}").resolve(),
        )
        if root is not None
        else host_registration.Registration(
            adapter=record.adapter, label=record.label, status=host_registration.UNSUPPORTED,
            name="", note="项目暂时找不到，没能从宿主配置里注销这次接入。",
        )
    )
    return {
        "status": "cancelled",
        "ticket_removed": removed,
        "host_registration": registration.public(),
        **record.public(),
    }


def known_hosts() -> list[dict[str, Any]]:
    """The host table as the page may see it: what happens if you pick this vendor.

    Sending this to the page is what keeps the two layers honest about each other —
    the page picks a vendor from what the console actually implements, instead of
    offering a vendor and finding out from an error. ``mode`` is the whole answer
    (see ``enroll_mode``); ``note`` is the one sentence to show for the two modes
    where the page is not the one finishing the job.
    """

    return [
        {
            "adapter": host.adapter,
            "label": host.label,
            "mode": enroll_mode(host),
            "note": _enroll_note(host, enroll_mode(host)),
        }
        for host in host_registration.HOSTS.values()
    ]
