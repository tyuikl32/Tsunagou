"""跨机器端到端：真 daemon + 真桥 + 真的"另一台机器"目录。

前面那些测试各自只覆盖一端：CLI 只断言"文件写对了"，中间层只有假 daemon，执行判定直接调 handler。
于是有两处**只有把两端接起来才会暴露**的问题（这次审计才发现）：

* 路由式的宿主（Codex、深寻）**只看**它状态目录里的 `endpoint.json` 取主机地址（它不读
  `TSUNAGOU_HTTP_URL`）—— 远端本来没有这份文件，于是第一次调用直接 `daemon_endpoint_not_configured`；
* OpenCode 那条路靠代码副本里的 `.tsunagou/project.json` 认项目 —— 远端只有副本、没有那个文件，
  于是多项目 daemon 会以 `project_context_required` 拒绝。

这个文件起一个真项目、一个真 daemon，把"主机发邀请 → 远端 `agent import` → 真桥入席"整条走一遍，
再让那台远端**接一个要动文件的任务**（D192 的第 0 档），断言：

1. 远端自报的机器名与副本位置真的到了名单里（页面就靠这两项）；
2. 远端能开工、能交活，而且**没有基线、交活时没有清单**——主机没读过那份副本，就不许留下看起来像
   观察的记录；
3. 本机那条路一点没变（同一个项目里另一个本机会话照旧）。
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from tsunagou.console import enrollment
from tsunagou.console.agents import AgentDirectory
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.projects import ensure_daemon, find
from tsunagou.console.proxy import project_token
from tsunagou.platform import host_registration
from tsunagou.platform.host_registration import REGISTERED

cli_module = importlib.import_module("tsunagou.cli.app")
SOURCE = Path(__file__).resolve().parents[2]
REGISTRY = json.loads((SOURCE / "protocol/registry/commands.json").read_text(encoding="utf-8"))

# 一次调用一个进程：失败的调用与成功的调用各自独立，不会互相污染。
CALL = r"""
import { readFileSync } from 'node:fs';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
const [configPath, metaKey, metaValue, toolName, argsJson] = process.argv.slice(1);
const config = JSON.parse(readFileSync(configPath, 'utf8'));
const env = { ...process.env, ...config.env };
delete env.TSUNAGOU_CONNECT_HELPER;
const transport = new StdioClientTransport({command: config.command, args: config.args, env, stderr: 'pipe'});
const client = new Client({name: 'fixture-remote-machine', version: '1.0'}, {capabilities: {}});
const reply = (value) => process.stdout.write(JSON.stringify(value));
try {
  await client.connect(transport);
  const result = await client.callTool({
    name: toolName, arguments: JSON.parse(argsJson), _meta: {[metaKey]: metaValue},
  });
  const text = (result.content || []).filter((item) => item.type === 'text').map((item) => item.text).join(' ');
  if (result.isError) reply({error: text});
  else reply(JSON.parse(text));
} catch (error) {
  reply({error: String((error && error.message) || error)});
} finally { await client.close(); }
"""


class Bridge:
    """一个宿主会话：桥是它自己那一份配置起的，身份由每次调用带上去。"""

    def __init__(self, config_path: Path, meta_key: str, conversation: str) -> None:
        self.config_path = config_path
        self.meta_key = meta_key
        self.conversation = conversation

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        observed = subprocess.run(
            ["node", "--input-type=module", "-e", CALL, str(self.config_path),
             self.meta_key, self.conversation, tool, json.dumps(arguments)],
            cwd=SOURCE / "packages" / "bridge-server", env=os.environ.copy(),
            capture_output=True, text=True, timeout=120,
        )
        assert observed.returncode == 0, observed.stderr or observed.stdout
        return json.loads(observed.stdout)

    def session(self) -> dict[str, Any]:
        """桥落下来的会话凭据：主 Agent 那边正是用它来发 M 权限的命令。"""

        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        session_file = Path(str(config["env"]["TSUNAGOU_SESSION_FILE"]))
        return json.loads(session_file.read_text(encoding="utf-8"))


class RemoteMachine:
    """一台"另一台机器"：自己的私有状态目录、自己的代码副本，桥也在它这边起。"""

    def __init__(self, root: Path, machine: str) -> None:
        self.state = root / "remote-state"
        self.copy = root / "remote-code-copy"
        self.copy.mkdir(parents=True, exist_ok=True)
        self.machine = machine
        self.imported: dict[str, Any] = {}

    def import_invitation(self, invite: str, daemon_url: str, conversation: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "tsunagou", "agent", "import", invite,
             "--workdir", str(self.copy), "--state-dir", str(self.state),
             "--machine", self.machine, "--copy", str(self.copy), "--baseline", "main",
             "--daemon-url", daemon_url],
            cwd=SOURCE, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        self.imported = json.loads(result.stdout)
        self.bridge = Bridge(self.bridge_config, "ai.opencode/sessionID", conversation)

    @property
    def bridge_config(self) -> Path:
        configs = sorted(self.state.glob("opencode-*.json"))
        assert configs, f"远端应当写下一份桥的启动配置，实际有：{list(self.state.iterdir())}"
        return configs[0]

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.bridge.call(tool, arguments)


@pytest.fixture(name="host")
def host_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """一台主机：项目在本地、daemon 在本地、控制台也在本地。"""

    if not (SOURCE / "packages" / "bridge-server" / "dist" / "server.js").is_file():
        pytest.skip("bridge not built: pnpm -C packages/bridge-server run build")
    for name in ("TSUNAGOU_PROJECT_ROOT", "TSUNAGOU_PROJECT_ID", "TSUNAGOU_STATE_DIR",
                 "TSUNAGOU_DAEMON_URL", "TSUNAGOU_ROUTING_DIR", "TSUNAGOU_HOST_META_KEY",
                 "TSUNAGOU_HOST_CONVERSATION_ID", "TSUNAGOU_HTTP_URL", "TSUNAGOU_TICKET_FILE",
                 "TSUNAGOU_SESSION_FILE"):
        monkeypatch.delenv(name, raising=False)
    # 宿主自己的注册动作（往 Codex/OpenCode 配置里写条目）不在这个测试的范围内：
    # 它由各自的单测盯着，这里要的是 daemon 与桥这两端。
    monkeypatch.setattr(
        host_registration, "register",
        lambda adapter, *, profile, project_root, bridge, **_: host_registration.Registration(
            adapter=adapter, label="OpenCode", status=REGISTERED, name=f"tsunagou-{profile}",
        ),
    )
    root = tmp_path / "projects" / "跨机器"
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)

    def cli(*args: str) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, "-m", "tsunagou", "--project-root", str(root), *args],
            cwd=SOURCE, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return json.loads(result.stdout)

    project = cli("project", "init", "--coordination-root", str(root))
    cli("daemon", "start")
    try:
        yield host_handle(tmp_path, root, project, cli)
    finally:
        cli("daemon", "stop")


def host_handle(tmp_path: Path, root: Path, project: dict[str, Any], cli) -> dict[str, Any]:
    """主机侧的几个入口：发邀请、以控制权/主 Agent 身份发命令、读名单、读工作区。"""

    endpoint = json.loads((root / ".tsunagou" / "local" / "endpoint.json").read_text(encoding="utf-8"))
    token = (root / ".tsunagou" / "local" / "control.token").read_text(encoding="utf-8").strip()

    def post(kind: str, payload: dict[str, Any], *, bearer: str, session: dict[str, Any] | None = None) -> dict[str, Any]:
        envelope = json.dumps({
            "command_id": os.urandom(16).hex(), "protocol_version": REGISTRY["protocol_version"],
            "schema_bundle_digest": REGISTRY["schema_bundle_digest"], "payload": payload,
        }).encode("utf-8")
        headers = {"content-type": "application/json", "authorization": f"Bearer {bearer}",
                   "tsunagou-project-id": project["project_id"]}
        if session is not None:
            headers["tsunagou-session-id"] = session["session_id"]
            headers["tsunagou-connection-epoch"] = str(session["connection_epoch"])
        request = urllib.request.Request(
            f"{endpoint['url']}/api/v1/commands/{kind}", data=envelope, method="POST", headers=headers,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))["result"]

    def query(kind: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{endpoint['url']}/api/v1/projects/{project['project_id']}/{kind}",
            headers={"tsunagou-project-id": project["project_id"]},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    config = ConsoleConfig(
        projects_root=root.parent, scan_roots=[root.parent],
        index_path=tmp_path / "index.json", profile_path=tmp_path / "profile.json",
    )
    entry = find(config, project["project_id"])
    directory = AgentDirectory()
    daemon_endpoint = ensure_daemon(entry, autostart=True)

    def roster() -> dict[str, Any]:
        lineup = directory.roster(project["project_id"], root, daemon_endpoint, force=True)
        assert lineup is not None, "daemon 在跑，名单就该读得到"
        return {item["agent_id"]: item for item in lineup.agents}

    def local_main() -> Bridge:
        """本机那条路：中间层发起的本地接入，票里写着 main —— 入席那一刻由 daemon 自行任命。

        它也顺便证明了"远端之外的那条路一点没变"。
        """

        prepared = enrollment.prepare(
            entry, daemon_endpoint, vendor="opencode", role="main", nickname="主机主控",
            profile="main-a", directory=directory, token=project_token(entry.path, daemon_endpoint),
        )
        ticket = json.loads(Path(str(prepared["ticket_file"])).read_text(encoding="utf-8"))
        bridge = Bridge(Path(str(prepared["bridge_config"])), "ai.opencode/sessionID", ticket["conversation_id"])
        arrived = bridge.call("context__project_read", {})
        assert "error" not in arrived, arrived
        assert arrived["role"] == "main", "票里写着 main，席位就是主 Agent"
        return bridge

    return {
        "root": root, "project": project, "url": endpoint["url"], "token": token,
        "cli": cli, "post": post, "query": query, "roster": roster, "local_main": local_main,
    }


def test_a_remote_machine_imports_an_invitation_and_reports_itself(host, tmp_path: Path) -> None:
    """整条：主机发邀请 → 远端导入 → 真桥入席 → 名单里出现"哪台机器 + 哪份副本"。"""

    invite = host["cli"]("agent", "invite", "--adapter", "opencode",
                         "--profile", "remote-a", "--nickname", "远端小三")
    assert invite["status"] == "invited" and invite["conversation_id"] == "ses_remote-a"

    remote = RemoteMachine(tmp_path, "工位-九")
    remote.import_invitation(invite["invite"], host["url"], invite["conversation_id"])

    assert remote.imported["machine"] == "工位-九"
    assert remote.imported["copy_path"] == str(remote.copy.resolve())
    # 路由式的宿主只从状态目录里取主机地址，这份文件是远端能连上的前提之一。
    assert json.loads((remote.state / "endpoint.json").read_text(encoding="utf-8"))["url"] == host["url"]

    arrived = remote.call("context__project_read", {})

    assert "error" not in arrived, arrived
    assert arrived["project_id"] == host["project"]["project_id"] and arrived["agent_id"]
    row = host["roster"]()[arrived["agent_id"]]
    assert row["machine"] == "工位-九", "远端自报的机器名要出现在名单里"
    assert row["copy_path"] == str(remote.copy.resolve())
    assert row["copy_baseline"] == "main"


def test_a_remote_worker_can_take_a_file_task_end_to_end(host, tmp_path: Path) -> None:
    """远端接一个要动文件的任务：放行、能干、交活，而且**没有基线、没有清单**（D192 第 0 档）。"""

    invite = host["cli"]("agent", "invite", "--adapter", "opencode",
                         "--profile", "remote-b", "--nickname", "远端小四")
    remote = RemoteMachine(tmp_path, "工位-十")
    remote.import_invitation(invite["invite"], host["url"], invite["conversation_id"])
    remote.call("context__project_read", {})

    # 主机侧：主 Agent 的活（建任务、选隔离方式、发布）由真的主 Agent 会话来发。
    main = host["local_main"]()
    main_session = main.session()
    scope = {"resources": [{"kind": "path", "root_id": "coordination",
                            "segments": ["demo.txt"], "mode": "exclusive_write"}]}
    task = host["post"]("task.create", {"title": "在远端副本上改一处",
                                        "objective": "产出一份改动", "execution_scope": scope},
                        bearer=main_session["secret_token"], session=main_session)
    host["post"]("workspace.select", {"task_id": task["task_id"], "driver_kind": "external",
                                      "external_locator": str(remote.copy.resolve())},
                 bearer=main_session["secret_token"], session=main_session)
    host["post"]("task.ready", {"task_id": task["task_id"]},
                 bearer=main_session["secret_token"], session=main_session)
    published = host["post"]("task.publish", {"task_id": task["task_id"]},
                             bearer=main_session["secret_token"], session=main_session)

    # **开工之前**就看得出这个任务要碰文件：远端因此不会白跑一趟（它没报副本时接不了）。
    before = remote.call("context__project_read", {})
    assert "error" not in before, before
    listed = next(row for row in before["open_tasks"] if row["task_id"] == task["task_id"])
    assert listed["requires_workspace"] is True

    # 远端侧：全部通过真桥。
    started = remote.call("task__begin", {"task_id": task["task_id"],
                                          "expected_task_revision": published["revision"]})

    assert "error" not in started, started
    assert started["workspace_id"], "放行的那一条会真的开出一个工作区"
    workspace = next(item for item in host["query"]("workspaces")["items"]
                     if item["workspace_id"] == started["workspace_id"])
    assert workspace["driver_kind"] == "external"
    assert workspace["external_locator"] == str(remote.copy.resolve())
    assert workspace["status"] == "remote_reported", "主机会如实写：这是那台机器自报的"
    assert not workspace.get("baseline_manifest_id"), "主机没读过那份副本，就没有基线"

    done = remote.call("task__submit", {"task_id": task["task_id"],
                                        "attempt_id": started["attempt_id"],
                                        "summary": "在远端副本上改完了 demo.txt"})

    assert "error" not in done, done
    assert done["status"] == "submitted"
    assert not done.get("workspace_result_ref"), "没有清单：那不是主机观察出来的东西"
    # 交完之后状态要往前走一步：停在"远端自报"会让人以为这活还在做。
    after = next(item for item in host["query"]("workspaces")["items"]
                 if item["workspace_id"] == started["workspace_id"])
    assert after["status"] == "remote_result_reported"


def test_the_same_project_still_serves_a_local_session(host, tmp_path: Path) -> None:
    """本机那条路一点没变：同一个项目里，本机自己的会话照旧接入，而且是主 Agent。"""

    invite = host["cli"]("agent", "invite", "--adapter", "opencode",
                         "--profile", "remote-c", "--nickname", "远端小五")
    remote = RemoteMachine(tmp_path, "工位-十一")
    remote.import_invitation(invite["invite"], host["url"], invite["conversation_id"])
    remote.call("context__project_read", {})
    main = host["local_main"]()

    rows = host["roster"]()

    remote_ids = {agent["agent_id"] for agent in rows.values() if agent.get("machine")}
    assert remote_ids, "远端那一条要在名单里"
    assert all("machine" not in agent for agent in rows.values() if agent["agent_id"] not in remote_ids), \
        "其余席位不该凭空多出机器名"
    main_id = main.session()["agent_id"]
    assert rows[main_id].get("machine") in (None, ""), "本机主 Agent 不是远端"
