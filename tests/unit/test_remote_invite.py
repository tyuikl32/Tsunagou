"""跨机器接入的第一段：主机发一张邀请，远端一条命令收下。

邀请本身是**一段可复制的内容**（票在里面，像传密码那样交给远端）。这里只测两件事：
内容能原样解回来、坏内容各有各的拒绝码；以及两条命令各自做了什么 —— 主机那条只签票、
只读项目，远端那条只写**自己这台机器**的东西（身份、票、桥的启动配置），并把桥接进
本机宿主。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import tsunagou.platform.remote_invite as remote_invite
from tsunagou.platform.host_registration import REGISTERED, Registration
from tsunagou.platform.runtime_context import RuntimeContext
from tsunagou.shared_kernel.time import format_timestamp, now_ms

PROJECT_ID = "0192c7f1-8a4e-7c31-9d2b-6f0a5e7c1b44"
runner = CliRunner()


def _invite(**overrides: Any) -> dict[str, Any]:
    base = {
        "project_id": PROJECT_ID, "url": "http://10.0.0.5:2810", "adapter": "opencode",
        "profile": "worker3", "installation_id": "opencode:worker3",
        "conversation_id": "ses_worker3", "role": "worker", "nickname": "小三",
        "secret": "s3cret-ticket", "expires_at": format_timestamp(now_ms() + 600_000),
    }
    return {**base, **overrides}


def test_an_invitation_survives_the_round_trip() -> None:
    decoded = remote_invite.decode(remote_invite.encode(_invite()))
    assert decoded["conversation_id"] == "ses_worker3"
    assert decoded["secret"] == "s3cret-ticket"
    assert decoded["nickname"] == "小三"
    remote_invite.check(decoded)
    assert 0 < remote_invite.seconds_left(decoded) <= 600


def test_every_bad_invitation_has_its_own_code() -> None:
    """人要知道是"抄坏了"还是"过期了"：两者给的话不一样。"""

    import base64
    from datetime import UTC, datetime

    with pytest.raises(RuntimeError, match="^invite_malformed$"):
        remote_invite.decode("这不是一张邀请")
    with pytest.raises(RuntimeError, match="^invite_malformed$"):
        remote_invite.decode(remote_invite.PREFIX + "!!!!")

    future = datetime.fromtimestamp(now_ms() / 1000 + 600, tz=UTC).isoformat()
    forged = remote_invite.PREFIX + base64.urlsafe_b64encode(json.dumps({
        "v": 99, "kind": "tsunagou-invite", **_invite(expires_at=future),
    }).encode("utf-8")).decode("ascii").rstrip("=")
    with pytest.raises(RuntimeError, match="^invite_unsupported_version$"):
        remote_invite.decode(forged)

    with pytest.raises(RuntimeError, match="^invite_incomplete:secret$"):
        remote_invite.decode(remote_invite.encode(_invite(secret=" ")))
    expired = _invite(expires_at=format_timestamp(now_ms() - 1000))
    with pytest.raises(RuntimeError, match="^invite_expired$"):
        remote_invite.check(remote_invite.decode(remote_invite.encode(expired)))
    with pytest.raises(RuntimeError, match="^invite_role_invalid$"):
        remote_invite.check({**_invite(), "role": "boss"})
    assert remote_invite.seconds_left({"expires_at": "不是时间"}) == 0


def _runtime(tmp_path: Path, *, advertised: str = "") -> RuntimeContext:
    return RuntimeContext(
        project_root=tmp_path, state_dir=tmp_path / ".tsunagou/local", project_id=PROJECT_ID,
        endpoint={"url": "http://127.0.0.1:2810", "advertised_url": advertised},
        daemon_url="http://127.0.0.1:2810", source_root=None,
    )


def test_the_host_signs_one_ticket_and_hands_over_one_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cli = importlib.import_module("tsunagou.cli.app")
    signed: list[dict[str, Any]] = []
    monkeypatch.setattr(cli, "_runtime_context", lambda: _runtime(tmp_path, advertised="http://10.0.0.5:2810"))
    monkeypatch.setattr(cli, "_control_token", lambda: "control-token")
    monkeypatch.setattr(cli, "_invoke_command",
                        lambda kind, payload, authorization="": signed.append({"command": kind, **payload})
                        or {"secret": "s3cret-ticket"})

    result = runner.invoke(cli.app, ["agent", "invite", "--adapter", "opencode", "--nickname", "小三"])

    assert result.exit_code == 0, result.output
    answer = json.loads(result.output)
    assert answer["status"] == "invited" and answer["url"] == "http://10.0.0.5:2810"
    assert len(signed) == 1
    assert signed[0]["command"] == "agent.ticket.create.user"
    assert signed[0]["role"] == "worker" and signed[0]["installation_id"] == "opencode:小三"
    assert signed[0]["conversation_evidence"] == {"conversation_id": "ses_小三"}
    decoded = remote_invite.decode(answer["invite"])
    assert decoded["secret"] == "s3cret-ticket" and decoded["project_id"] == PROJECT_ID
    assert decoded["conversation_id"] == "ses_小三" and decoded["nickname"] == "小三"


def test_the_host_refuses_a_remote_main_and_asks_for_the_number_otherwise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    cli = importlib.import_module("tsunagou.cli.app")
    monkeypatch.setattr(cli, "_runtime_context", lambda: _runtime(tmp_path, advertised="http://10.0.0.5:2810"))
    monkeypatch.setattr(cli, "_control_token", lambda: "control-token")
    monkeypatch.setattr(cli, "_invoke_command", lambda *a, **k: {"secret": "s3cret-ticket"})

    # 主 Agent 必须和协调中心同机：跨机器那张邀请只能是子 Agent。
    refused = runner.invoke(cli.app, ["agent", "invite", "--adapter", "opencode", "--role", "main"])
    assert refused.exit_code == 4 and "main_agent_must_be_local" in refused.output

    # Codex / DSH 的会话名只有它们自己知道：先报号，再发邀请。
    needs_number = runner.invoke(cli.app, ["agent", "invite", "--adapter", "codex"])
    assert needs_number.exit_code == 4 and "conversation_id_required_for_this_host" in needs_number.output

    with_number = runner.invoke(cli.app, [
        "agent", "invite", "--adapter", "codex", "--conversation-id", "thread-abc", "--profile", "w1",
    ])
    assert with_number.exit_code == 0, with_number.output
    assert remote_invite.decode(json.loads(with_number.output)["invite"])["conversation_id"] == "thread-abc"


def test_the_remote_import_writes_only_its_own_material(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    cli = importlib.import_module("tsunagou.cli.app")
    registered: list[dict[str, Any]] = []
    monkeypatch.setattr(cli, "_read_daemon_health",
                        lambda url: {"status": "ok", "runtime": {"project_ids": [PROJECT_ID]}})
    monkeypatch.setattr(cli.host_registration, "register",
                        lambda adapter, **kwargs: registered.append({"adapter": adapter, **kwargs})
                        or Registration(adapter=adapter, label="OpenCode", status=REGISTERED, name="tsunagou"))
    workspace = tmp_path / "业务代码"
    workspace.mkdir()
    state = tmp_path / "远端私有"

    result = runner.invoke(cli.app, [
        "agent", "import", remote_invite.encode(_invite()),
        "--workdir", str(workspace), "--state-dir", str(state),
    ])

    assert result.exit_code == 0, result.output
    answer = json.loads(result.output)
    assert answer["status"] == "imported" and answer["workspace"] == str(workspace)
    identity = json.loads((state / "host-identity.json").read_text(encoding="utf-8"))
    assert identity["conversation_id"] == "ses_worker3" and identity["installation_id"] == "opencode:worker3"
    ticket = json.loads((state / "ticket.json").read_text(encoding="utf-8"))
    assert ticket["secret"] == "s3cret-ticket" and ticket["requested_role"] == "worker"
    config = json.loads(next(state.glob("opencode-*.json")).read_text(encoding="utf-8"))
    assert config["env"]["TSUNAGOU_HTTP_URL"] == "http://10.0.0.5:2810"
    # 桥只认主机那个地址：本机那份"daemon 在哪"的记录指到自己的私有目录（里面没有 endpoint.json）。
    assert config["env"]["TSUNAGOU_DAEMON_STATE_DIR"] == str(state)
    assert config["env"]["TSUNAGOU_PROJECT_ROOT"] == str(workspace)
    assert registered and registered[0]["project_root"] == workspace
    assert registered[0]["adapter"] == "opencode"
    assert not (workspace / ".tsunagou").exists(), "远端不该长出第二份协作数据"


def test_the_remote_says_which_machine_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """远端自己报名（不靠主机猜 IP）：名单里要显示成"远端 · 机器名"。"""

    cli = importlib.import_module("tsunagou.cli.app")
    monkeypatch.setattr(cli, "_read_daemon_health",
                        lambda url: {"status": "ok", "runtime": {"project_ids": [PROJECT_ID]}})
    monkeypatch.setattr(cli, "_remote_registration",
                        lambda adapter, **kwargs: Registration(
                            adapter=adapter, label="OpenCode", status=REGISTERED, name="tsunagou"))
    workspace, state = tmp_path / "code", tmp_path / "state"
    workspace.mkdir()

    named = runner.invoke(cli.app, [
        "agent", "import", remote_invite.encode(_invite()), "--workdir", str(workspace),
        "--state-dir", str(state), "--machine", "  工位-七\n ",
    ])
    assert named.exit_code == 0, named.output
    assert json.loads(named.output)["machine"] == "工位-七"
    assert json.loads((state / "host-identity.json").read_text(encoding="utf-8"))["machine"] == "工位-七"

    # 没人报名时用这台机器自己的名字，而不是一个 127.0.0.1 之类的猜测。
    anonymous = runner.invoke(cli.app, [
        "agent", "import", remote_invite.encode(_invite()), "--workdir", str(workspace),
        "--state-dir", str(tmp_path / "state2"),
    ])
    assert anonymous.exit_code == 0, anonymous.output
    assert json.loads(anonymous.output)["machine"]


def test_the_remote_refuses_a_loopback_address_unless_it_is_told_another_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    cli = importlib.import_module("tsunagou.cli.app")
    monkeypatch.setattr(cli, "_read_daemon_health",
                        lambda url: {"status": "ok", "runtime": {"project_ids": [PROJECT_ID]}})
    monkeypatch.setattr(cli.host_registration, "register",
                        lambda adapter, **kwargs: Registration(
                            adapter=adapter, label="OpenCode", status=REGISTERED, name="tsunagou"))
    loopback = _invite(url="http://127.0.0.1:2810")
    workspace, state = tmp_path / "code", tmp_path / "state"
    workspace.mkdir()

    refused = runner.invoke(cli.app, [
        "agent", "import", remote_invite.encode(loopback),
        "--workdir", str(workspace), "--state-dir", str(state),
    ])
    assert refused.exit_code == 4 and "invite_address_is_loopback" in refused.output

    # 走隧道时远端看到的就是回环：说清楚就行，不拦着。
    allowed = runner.invoke(cli.app, [
        "agent", "import", remote_invite.encode(loopback), "--daemon-url", "http://127.0.0.1:2810",
        "--workdir", str(workspace), "--state-dir", str(state),
    ])
    assert allowed.exit_code == 0, allowed.output


def test_the_remote_refuses_a_daemon_that_does_not_serve_that_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    cli = importlib.import_module("tsunagou.cli.app")
    monkeypatch.setattr(cli, "_read_daemon_health",
                        lambda url: {"status": "ok", "runtime": {"project_ids": ["another-project"]}})

    result = runner.invoke(cli.app, [
        "agent", "import", remote_invite.encode(_invite()),
        "--workdir", str(tmp_path), "--state-dir", str(tmp_path / "state"),
    ])

    assert result.exit_code == 4
    assert "invite_project_not_served_by_that_daemon" in result.output


def test_whichever_host_owns_the_name_reports_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """报号：Codex / DSH 的会话名只有它们自己知道，主机签票前得先拿到。"""

    cli = importlib.import_module("tsunagou.cli.app")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-from-host")
    monkeypatch.delenv("DSH_SESSION_ID", raising=False)
    monkeypatch.delenv("TSUNAGOU_HOST_CONVERSATION_ID", raising=False)

    codex = runner.invoke(cli.app, ["agent", "whoami", "--adapter", "codex"])
    assert codex.exit_code == 0, codex.output
    assert json.loads(codex.output)["conversation_id"] == "thread-from-host"

    # 在会话外跑（没有宿主上下文）时如实说"跑不出来"，不猜一个号出来。
    # （只断结构化字段：CliRunner 抓回来的中文受控制台编码影响，不适合当断言。）
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    outside = runner.invoke(cli.app, ["agent", "whoami", "--adapter", "codex"])
    assert outside.exit_code == 4
    refused = json.loads(outside.output)
    assert refused["status"] == "error" and refused["note"]
    assert refused["error"].startswith("host_conversation_required")


def test_hosts_that_find_themselves_by_a_route_get_one_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Codex / DSH 的桥按会话身份去路由目录找自己：远端导入时也得写那一条。"""

    cli = importlib.import_module("tsunagou.cli.app")
    routes = tmp_path / "远端路由"
    monkeypatch.setenv("TSUNAGOU_ROUTING_DIR", str(routes))
    monkeypatch.setattr(cli, "_read_daemon_health",
                        lambda url: {"status": "ok", "runtime": {"project_ids": [PROJECT_ID]}})
    monkeypatch.setattr(cli, "_remote_registration",
                        lambda adapter, **kwargs: Registration(
                            adapter=adapter, label="宿主", status=REGISTERED, name="tsunagou"))

    for adapter, conversation, expected in (("codex", "thread-abc", "codex"), ("deepseek", "session-9", "deepseek")):
        workspace, state = tmp_path / f"code-{adapter}", tmp_path / f"state-{adapter}"
        workspace.mkdir()
        result = runner.invoke(cli.app, [
            "agent", "import", remote_invite.encode(_invite(adapter=adapter, conversation_id=conversation,
                                                           installation_id=f"{adapter}:w1", profile="w1")),
            "--workdir", str(workspace), "--state-dir", str(state),
        ])
        assert result.exit_code == 0, result.output
        config = json.loads(next(state.glob(f"{adapter}-*.json")).read_text(encoding="utf-8"))
        assert config["env"]["TSUNAGOU_ROUTING_DIR"] == str(routes)
        written = list(routes.glob("*.json"))
        assert len(written) == 1, "每条会话一条路由"
        route = json.loads(written[0].read_text(encoding="utf-8"))
        assert route["conversation_id"] == conversation and route["project_id"] == PROJECT_ID
        assert route["project_root"] == str(workspace), "项目在主机上，这里只记代码副本位置"
        assert route["ticket_file"] == str(state / "ticket.json")
        if expected == "deepseek":
            assert route["adapter"] == "deepseek"
        (routes / written[0].name).unlink()


def test_opencode_needs_no_route_because_the_host_picks_its_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    cli = importlib.import_module("tsunagou.cli.app")
    routes = tmp_path / "远端路由"
    monkeypatch.setenv("TSUNAGOU_ROUTING_DIR", str(routes))
    monkeypatch.setattr(cli, "_read_daemon_health",
                        lambda url: {"status": "ok", "runtime": {"project_ids": [PROJECT_ID]}})
    monkeypatch.setattr(cli, "_remote_registration",
                        lambda adapter, **kwargs: Registration(
                            adapter=adapter, label="OpenCode", status=REGISTERED, name="tsunagou"))
    workspace, state = tmp_path / "code", tmp_path / "state"
    workspace.mkdir()

    result = runner.invoke(cli.app, [
        "agent", "import", remote_invite.encode(_invite()),
        "--workdir", str(workspace), "--state-dir", str(state),
    ])

    assert result.exit_code == 0, result.output
    config = json.loads(next(state.glob("opencode-*.json")).read_text(encoding="utf-8"))
    assert "TSUNAGOU_ROUTING_DIR" not in config["env"]
    assert not routes.exists()
