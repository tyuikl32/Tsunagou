"""Turning "add an Agent" into the local documents a host can pick up.

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
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from tsunagou.console.agents import AgentDirectory
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.errors import ConsoleError
from tsunagou.console.profile import update_profile
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

TICKET_COMMAND = "agent.ticket.create.user"
DELIVERY_ACK = "/api/v1/credential-deliveries/{reference}/ack"
ROLES = ("worker", "main")
BUILD_COMMAND = "pnpm -C packages/bridge-server run build"
NEXT_STEP = (
    "重启或重载这个宿主窗口，让宿主读取新的 MCP 配置；"
    "该会话里的 bridge 会用票据文件自动兑换成一个 Agent（首次调用 context__project_read 即完成）。"
)

# 票据默认活 10 分钟（authority.issue_ticket），多留一点余量再判过期。
ENROLLMENT_TTL_SECONDS = 900.0


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
            conversation_id: str, role: str) -> dict[str, Any]:
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
    return [record.enrollment_id for record in dropped]


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

    # 名单要取**签票之前**的样子：到达判定就是"比这份多出来的那个人"。
    before = directory.roster(entry.project_id, entry.path, endpoint, force=True) if directory else None
    known_agents = frozenset(agent["agent_id"] for agent in before.agents) if before else frozenset()
    conversation = profile_name(profile) if profile else uuid.uuid4().hex[:12]
    destination = (entry.path / BRIDGE_DIRECTORY / f"{host.adapter}-{conversation}").resolve()
    installation_id, conversation_id = profile_identity(destination, host.adapter, conversation)

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
        ticket_file=ticket_path.as_posix(), blind=before is None,
    )
    _remember(record)
    return {
        "status": "prepared",
        "installation_id": installation_id,
        "mode": mode,
        "bridge_dir": destination.as_posix(),
        "bridge_config": bridge_config.as_posix(),
        "ticket_file": ticket_path.as_posix(),
        "host_registration": registration.public(),
        "next": NEXT_STEP,
        **record.public(),
    }


def status(enrollment_id: str, *, settings: ConsoleConfig, directory: AgentDirectory) -> dict[str, Any]:
    """Has that Agent arrived yet? — the question the waiting overlay keeps asking.

    A project whose roster cannot be read answers ``waiting``: "not yet" and "cannot
    tell" are different things, and the waiting overlay is allowed to keep waiting
    rather than declare a failure it cannot see.
    """

    record = pending(enrollment_id)
    if record.arrived_agent_id:
        return {"status": "arrived", **record.public()}
    if record.cancelled:
        return {"status": "cancelled", **record.public()}
    if time.time() > record.expires_at:
        return {
            "status": "expired", **record.public(),
            "note": "票据有效期已过，请重新添加；上一次的票据已经作废。",
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
    arrived = [agent["agent_id"] for agent in lineup.agents if agent["agent_id"] not in record.known_agents]
    if not arrived:
        return {"status": "waiting", **record.public()}
    record.arrived_agent_id = arrived[0]
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

    record = pending(enrollment_id)
    if record.arrived_agent_id:
        raise ConsoleError(
            "enrollment_already_arrived", status=409,
            detail={"agent_id": record.arrived_agent_id, "hint": "它已经连上了；要撤它得走退席那条路。"},
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
    """The host table as the page may see it: who can be registered, and who cannot.

    Sending this to the page is what keeps the two layers honest about each other —
    the page picks a vendor from what the console actually implements, instead of
    offering a vendor and finding out from an error.
    """

    return [
        {
            "adapter": host.adapter,
            "label": host.label,
            "supported": host.commands is not None,
            "note": host.note,
        }
        for host in host_registration.HOSTS.values()
    ]
