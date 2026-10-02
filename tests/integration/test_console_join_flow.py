"""Real daemon/bridge with a fixture Desktop: console selection reaches one chat."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tsunagou.application import onboarding
from tsunagou.console import enrollment
from tsunagou.console.agents import AgentDirectory
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.projects import find
from tsunagou.platform.enrollment_store import EnrollmentStore
from tsunagou.platform.runtime_context import resolve_runtime

cli_module = importlib.import_module("tsunagou.cli.app")


@pytest.mark.parametrize("role", ["main", "worker"])
def test_console_join_through_real_daemon_and_bridge(tmp_path, monkeypatch, role):
    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "projects" / "chosen"
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    outside = tmp_path / "other-cwd"
    outside.mkdir()
    for name in ("TSUNAGOU_PROJECT_ROOT", "TSUNAGOU_PROJECT_ID", "TSUNAGOU_STATE_DIR", "TSUNAGOU_DAEMON_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(tmp_path / "enrollments"))
    monkeypatch.setenv("TSUNAGOU_ROUTING_DIR", str(tmp_path / "routes"))
    monkeypatch.setenv("CODEX_THREAD_ID", "fixture-console-thread")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "fixture-desktop-pipe")

    class Host:
        def __init__(self, endpoint, thread):
            self.thread = thread

        def call_tool(self, _name, _args):
            return {"thread": {"id": self.thread}}

        def close(self):
            pass

    monkeypatch.setattr(onboarding, "NativeAppToolsClient", Host)
    monkeypatch.setattr(cli_module, "_register_codex_mcp", lambda **_: "unchanged:tsunagou")

    def cli(*args):
        result = subprocess.run(
            [sys.executable, "-m", "tsunagou", "--project-root", str(root), *args], cwd=source, capture_output=True, text=True, timeout=45
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return json.loads(result.stdout)

    project = cli("project", "init", "--coordination-root", str(root))
    cli("daemon", "start")
    try:
        config = ConsoleConfig(
            projects_root=root.parent, scan_roots=[root.parent], index_path=tmp_path / "index.json", profile_path=tmp_path / "profile.json"
        )
        entry = find(config, project["project_id"])
        directory = AgentDirectory()
        pending = enrollment.prepare(entry, resolve_runtime(root).endpoint, vendor="codex", role=role, directory=directory)
        assert pending["host_registration"]["status"] == "deferred"
        monkeypatch.chdir(outside)
        result = CliRunner().invoke(cli_module.app, ["agent", "join"])
        assert result.exit_code == 0, result.output
        joined = json.loads(result.output)
        assert joined["project_id"] == project["project_id"] and joined["role"] == role
        store = EnrollmentStore()
        intent = store.get(pending["enrollment_id"])
        assert not Path(intent["receipt_file"]).exists(), "CLI bootstrap is not an original-host read"
        waiting = enrollment.status(pending["enrollment_id"], settings=config, directory=directory)
        assert waiting["status"] == "waiting"
        # A fixture MCP client models the original Desktop call. This is integration
        # evidence, not a claim that the real Codex Desktop has been exercised.
        script = r"""
import { readFileSync } from 'node:fs';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
const config = JSON.parse(readFileSync(process.argv[1], 'utf8'));
const env = { ...process.env, ...config.env };
delete env.TSUNAGOU_CONNECT_HELPER;
const transport = new StdioClientTransport({command: config.command, args: config.args, env, stderr: 'pipe'});
const client = new Client({name: 'fixture-original-host', version: '1.0'}, {capabilities: {}});
try {
  await client.connect(transport);
  const result = await client.callTool({name: 'context__project_read', arguments: {}, _meta: {threadId: 'fixture-console-thread'}});
  if (result.isError) throw new Error('fixture_context_failed');
  const context = JSON.parse(result.content.find(item => item.type === 'text').text);
  process.stdout.write(JSON.stringify({project_id: context.project_id, agent_id: context.agent_id, role: context.role}));
} finally { await client.close(); }
"""
        observed = subprocess.run(
            ["node", "--input-type=module", "-e", script, joined["bridge_config"]],
            cwd=source / "packages/bridge-server",
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert observed.returncode == 0, observed.stderr or observed.stdout
        assert json.loads(observed.stdout)["agent_id"] == joined["agent_id"]
        arrived = enrollment.status(pending["enrollment_id"], settings=config, directory=directory)
        assert arrived["status"] == "arrived" and arrived["agent_id"] == joined["agent_id"]
        again = CliRunner().invoke(cli_module.app, ["agent", "join"])
        assert again.exit_code == 0, again.output
        assert json.loads(again.output)["agent_id"] == joined["agent_id"]
        assert len(cli("agent", "list", "--json")["items"]) == 1
        assert not (outside / ".tsunagou").exists()
    finally:
        cli("daemon", "stop")
