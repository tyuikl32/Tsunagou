"""Real daemon and real bridge: a console-prepared OpenCode session can arrive.

The console used to bind its ticket to a conversation id it invented, while the bridge
insists on the id the host reports on every call (``_meta["ai.opencode/sessionID"]``) —
a mismatch silently drops the ticket, so the page could only ever wait for an expiry.
The unit tests could not see this, because they replace both the daemon and the host
registration with fakes and never start a bridge. This one starts the real thing twice:

* a session that is **not** the one the ticket names must be refused, and must leave the
  ticket alone for its own conversation;
* the session the console actually handed out must enroll, and the console must then
  report that Agent as arrived.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tsunagou.console import enrollment
from tsunagou.console.agents import AgentDirectory
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.projects import ensure_daemon, find
from tsunagou.console.proxy import ensure_matching_project, project_token
from tsunagou.platform import host_registration
from tsunagou.platform.host_registration import REGISTERED

cli_module = importlib.import_module("tsunagou.cli.app")

# One tool call per run, so a failed call and a successful one are separate processes.
CALL = r"""
import { readFileSync } from 'node:fs';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
const [configPath, sessionId] = process.argv.slice(1);
const config = JSON.parse(readFileSync(configPath, 'utf8'));
const env = { ...process.env, ...config.env };
delete env.TSUNAGOU_CONNECT_HELPER;
const transport = new StdioClientTransport({command: config.command, args: config.args, env, stderr: 'pipe'});
const client = new Client({name: 'fixture-opencode-session', version: '1.0'}, {capabilities: {}});
try {
  await client.connect(transport);
  const result = await client.callTool({
    name: 'context__project_read', arguments: {}, _meta: {'ai.opencode/sessionID': sessionId},
  });
  const text = (result.content || []).filter((item) => item.type === 'text').map((item) => item.text).join(' ');
  if (result.isError) process.stdout.write(JSON.stringify({error: text}));
  else {
    const context = JSON.parse(text);
    process.stdout.write(JSON.stringify({
      project_id: context.project_id, agent_id: context.agent_id, role: context.role,
    }));
  }
} catch (error) {
  process.stdout.write(JSON.stringify({error: String((error && error.message) || error)}));
} finally { await client.close(); }
"""


def test_a_console_prepared_opencode_session_is_the_one_that_arrives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = Path(__file__).resolve().parents[2]
    if not (source / "packages" / "bridge-server" / "dist" / "server.js").is_file():
        pytest.skip("bridge not built: pnpm -C packages/bridge-server run build")
    root = tmp_path / "projects" / "opencode"
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    for name in (
        "TSUNAGOU_PROJECT_ROOT", "TSUNAGOU_PROJECT_ID", "TSUNAGOU_STATE_DIR", "TSUNAGOU_DAEMON_URL",
        # The bridge must decide from the configuration the console wrote, not from
        # whatever this machine's terminal happens to export.
        "TSUNAGOU_ROUTING_DIR", "TSUNAGOU_HOST_META_KEY", "TSUNAGOU_HOST_CONVERSATION_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    # The host's own CLI is out of scope here: the bridge and the daemon are not.
    monkeypatch.setattr(
        host_registration, "register",
        lambda adapter, *, profile, project_root, bridge, **_: host_registration.Registration(
            adapter=adapter, label="OpenCode", status=REGISTERED, name=f"tsunagou-{profile}",
        ),
    )

    def cli(*args: str) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, "-m", "tsunagou", "--project-root", str(root), *args],
            cwd=source, capture_output=True, text=True, timeout=90,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return json.loads(result.stdout)

    def call_bridge(bridge_config: str, session_id: str) -> dict[str, Any]:
        observed = subprocess.run(
            ["node", "--input-type=module", "-e", CALL, bridge_config, session_id],
            cwd=source / "packages" / "bridge-server", env=os.environ.copy(),
            capture_output=True, text=True, timeout=90,
        )
        assert observed.returncode == 0, observed.stderr or observed.stdout
        return json.loads(observed.stdout)

    project = cli("project", "init", "--coordination-root", str(root))
    cli("daemon", "start")
    try:
        config = ConsoleConfig(
            projects_root=root.parent, scan_roots=[root.parent],
            index_path=tmp_path / "index.json", profile_path=tmp_path / "profile.json",
        )
        entry = find(config, project["project_id"])
        directory = AgentDirectory()
        # Exactly what the console's own route does: a probed endpoint (``running``),
        # which is also what lets the roster be read at all.
        endpoint = ensure_daemon(entry, autostart=True)
        ensure_matching_project(endpoint, project["project_id"])
        prepared = enrollment.prepare(
            entry, endpoint, vendor="opencode", role="worker", nickname="熊猫",
            profile="worker-a", directory=directory, token=project_token(entry.path, endpoint),
        )
        session = json.loads(Path(str(prepared["ticket_file"])).read_text(encoding="utf-8"))["conversation_id"]
        assert str(session).startswith("ses_"), "OpenCode 认的是开会话时用的那个名字"
        assert str(session) in str(prepared["next"]), "页面要把这个名字说给人听"

        # Another session in the same project must not be able to spend this ticket.
        stranger = call_bridge(str(prepared["bridge_config"]), "ses_some-other-session")
        assert "not_enrolled" in str(stranger.get("error", "")), stranger
        assert Path(str(prepared["ticket_file"])).is_file(), "被拒的会话不许把票用掉"

        arrived = call_bridge(str(prepared["bridge_config"]), str(session))
        assert arrived["project_id"] == project["project_id"]
        assert arrived["role"] == "worker" and arrived["agent_id"]

        answer = enrollment.status(str(prepared["enrollment_id"]), settings=config, directory=directory)
        assert answer["status"] == "arrived" and answer["agent_id"] == arrived["agent_id"]
    finally:
        cli("daemon", "stop")
