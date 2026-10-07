// 工具面：主 Agent 必须有根/仓库的通道，空 scope 的措辞不能把"不做文件改动"说成"随便改"。
//
// 为什么有这个测试（2026-10-07 实测）：
//   · 主 Agent 报"没有 root.register / root.bind / repository.register 的通道"，查证属实：
//     注册表里三条都是 principal=M，但 TOOLS 数组里没有它们 —— 权限有、入口漏登记。
//   · task__create 的描述把 `{}` 写成 "no explicit restriction"（无显式限制），主 Agent 照此
//     理解，给三个**文件任务**发了空 scope：没有工作区、没有租约、改动不进结果。
// 所以这里钉两件事：三条工具在主 Agent 的工具面里**在**，在 worker 的工具面里**不在**；
// 以及描述必须直说"空 scope = 不认领任何路径、不做文件改动"。
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { writePrivateJson } from "../dist/private-file.js";

const metaKey = "tsunagou.hostSessionId";
const hash = (value) => createHash("sha256").update(value).digest("hex");
const ROOT_COMMANDS = ["root.register", "root.bind", "repository.register"];
const toolNameFor = (kind) => kind.replaceAll(".", "__");

async function listTools(t, role) {
  const root = mkdtempSync(join(tmpdir(), "tsunagou-tools-"));
  const routingDir = join(root, "routes");
  const sessionFile = join(root, "agent-a.json");
  writePrivateJson(sessionFile, {
    agent_id: "agent-a", session_id: "session-agent-a", connection_epoch: 1,
    secret_token: "token-agent-a", reconnect_nonce: "nonce-agent-a", baseline_status: "ready",
    conversation_binding_digest: hash("conversation_id:agent-a"),
    host_conversation_id_digest: hash("conversation_id:agent-a"),
  });
  writePrivateJson(join(routingDir, hash("agent-a") + ".json"), {
    format_version: 1, conversation_id: "agent-a", project_id: "project", project_root: root,
    daemon_state_dir: join(root, "daemon"), session_file: sessionFile, state_dir: root,
    ticket_file: join(root, "absent-ticket.json"),
    console_enrollment: {
      enrollment_id: "enrollment-agent-a", requested_role: role,
      receipt_file: join(root, "agent-a-receipt.json"),
    },
  });
  // 桥启动时只读配置；这里不需要真的守护进程，所以让端点指向一个没人听的端口。
  writePrivateJson(join(root, "daemon", "endpoint.json"), { url: "http://127.0.0.1:1" });
  const ticketFile = join(root, "ticket.json");
  writePrivateJson(ticketFile, {
    installation_id: "installation", conversation_id: "conversation",
    secret: "secret", requested_role: role,
  });
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([key]) => !/^(TSUNAGOU_|CODEX_)/.test(key)),
  );
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [fileURLToPath(new URL("../dist/server.js", import.meta.url))],
    env: { ...env, TSUNAGOU_ROUTING_DIR: routingDir, TSUNAGOU_HOST_META_KEY: metaKey,
      TSUNAGOU_TICKET_FILE: ticketFile },
    stderr: "pipe",
  });
  const client = new Client({ name: "tool-surface-test", version: "1.0.0" }, { capabilities: {} });
  await client.connect(transport);
  t.after(async () => {
    await client.close();
    rmSync(root, { recursive: true, force: true });
  });
  const { tools } = await client.listTools();
  return tools;
}

test("主 Agent 的工具面里有 root.register / root.bind / repository.register", async (t) => {
  const tools = await listTools(t, "main");
  const names = tools.map((tool) => tool.name);
  for (const kind of ROOT_COMMANDS) {
    assert.ok(names.includes(toolNameFor(kind)),
      `主 Agent 缺 ${toolNameFor(kind)}（注册表里它是 principal=M，必须在工具面里）`);
  }
});

test("worker 的工具面里没有这三条（M 级命令照旧被过滤掉）", async (t) => {
  const tools = await listTools(t, "worker");
  const names = tools.map((tool) => tool.name);
  for (const kind of ROOT_COMMANDS) {
    assert.ok(!names.includes(toolNameFor(kind)), `worker 不该看到 ${toolNameFor(kind)}`);
  }
});

test("task__create 的描述直说空 scope 的含义", async (t) => {
  const tools = await listTools(t, "main");
  const described = String(tools.find((tool) => tool.name === "task__create")?.description ?? "");
  assert.ok(!described.includes("no explicit restriction"),
    "别再写 no explicit restriction —— 主 Agent 会读成“随便改”");
  assert.match(described, /CLAIMS NO PATH/, "要说清空 scope = 不认领任何路径");
  assert.match(described, /not recorded in the result/, "要说清改动不进结果");
});
