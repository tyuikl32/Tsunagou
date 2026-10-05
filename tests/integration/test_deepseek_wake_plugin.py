"""Assemble the shipped plugin and private Python client, with no real DSH calls."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tsunagou.application.deepseek_wake_runner import run_deepseek_operation
from tsunagou.platform.deepseek_wake import (
    bind_deepseek_wake,
    deepseek_wake_runtime_path,
    ensure_deepseek_wake_configuration,
)


def test_managed_plugin_and_python_client_original_session_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the shipped plugin integration")
    plugin = Path(__file__).resolve().parents[2] / "packages/dsh-wake-plugin/index.js"
    private_home = tmp_path / "私有 home"
    monkeypatch.setattr(Path, "home", lambda: private_home)
    managed = ensure_deepseek_wake_configuration()
    project, agent, session, message = "project", "worker", "original-session", "message"
    bind_deepseek_wake(project, agent, session)
    captured = tmp_path / "captured.json"
    fixture = tmp_path / "host-double.mjs"
    fixture.write_text('''
import { createServer } from "node:http";
import { writeFileSync } from "node:fs";
const [pluginUrl, managedFile, capturedFile] = process.argv.slice(2);
const { apply } = await import(pluginUrl);
const routes = new Map();
const disposers = [];
const inspected = [];
const server = createServer((req, res) => {
  const handler = routes.get(req.url);
  if (!handler) { res.writeHead(404); res.end(); return; }
  Promise.resolve(handler(req, res)).catch(() => { res.writeHead(500); res.end(); });
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const services = {
  credentials: { resolve() { throw new Error("managed mode must not resolve credentials"); } },
  agents: { get() { return undefined; } },
  sessionController: {
    async inspect(id) { inspected.push(id); },
    async prompt(request) {
      writeFileSync(capturedFile, JSON.stringify({ inspected, request }));
      return { accepted: true };
    },
  },
};
await apply({
  get(name) { return services[name]; },
  effect(register) { disposers.push(register()); },
  webServer: {
    host: "127.0.0.1", port: server.address().port,
    register({ path, handler }) {
      routes.set(path, handler);
      return () => routes.delete(path);
    },
  },
}, { managedFile });
process.stdin.once("data", () => {
  for (const dispose of disposers.reverse()) dispose();
  server.close();
  process.stdin.pause();
});
''', encoding="utf-8")
    process = subprocess.Popen([node, str(fixture), plugin.as_uri(), str(managed), str(captured)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    runtime = deepseek_wake_runtime_path()
    try:
        deadline = time.monotonic() + 10
        while not runtime.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert runtime.exists(), "isolated plugin did not publish runtime discovery"
        descriptor = json.loads(runtime.read_text(encoding="utf-8"))
        assert descriptor["pid"] == process.pid and descriptor["contract_version"] == 1
        assert descriptor["endpoint"].startswith("http://127.0.0.1:")
        ids = {"project_id": project, "agent_id": agent, "conversation_id": session, "message_id": message}
        status = run_deepseek_operation("status", **ids)
        assert status["state"] == "unloaded" and status["can_queue"] is True
        assert status["result"] == "observed" and not captured.exists()
        accepted = run_deepseek_operation("wake", **ids)
        assert accepted["result"] == "queued" and accepted["request_associated"] is True
        assert accepted["turn_started"] is False
        submission = json.loads(captured.read_text(encoding="utf-8"))
        expected_id = "tsunagou-wake-v1:" + hashlib.sha256(json.dumps(
            [project, agent, session, message], separators=(",", ":"),
        ).encode()).hexdigest()
        assert submission["inspected"] == [session, session]
        assert submission["request"] == {
            "requestId": expected_id, "sessionId": session, "mode": "queue",
            "content": [{"type": "text", "text": (
                "请读取你自己的 Tsunagou 项目上下文和收件箱，核对当前身份与指定项目，"
                "按已有授权处理指定消息关联的待办，并通过 Tsunagou 回复结果。"
                "不要代替用户确认项目完成。\n\nproject_id: project\nmessage_id: message"
            )}],
        }
        key = json.loads(managed.read_text(encoding="utf-8"))["key"]
        assert key not in json.dumps([descriptor, status, accepted, submission])
        _stdout, stderr = process.communicate(input=b"stop\n", timeout=10)
        assert process.returncode == 0, stderr.decode("utf-8", errors="replace")
        assert not runtime.exists()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
