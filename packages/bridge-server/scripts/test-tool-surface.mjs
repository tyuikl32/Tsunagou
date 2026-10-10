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
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, win32 } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { writePrivateJson } from "../dist/private-file.js";
import { OPERATING_MANUAL_LINE } from "../dist/reminders.js";

const metaKey = "tsunagou.hostSessionId";
const hash = (value) => createHash("sha256").update(value).digest("hex");
const ROOT_COMMANDS = ["root.register", "root.bind", "repository.register"];
const toolNameFor = (kind) => kind.replaceAll(".", "__");
// 脚本自己就在 packages/bridge-server/scripts/ 下，往上三级是 checkout 根；dist 与 scripts 同深。
const checkoutManual = fileURLToPath(new URL("../../../docs/overview/agent-operating-manual.md", import.meta.url));

/** instructions 里那句手册指路必须是**绝对**路径，并真的落在本 checkout 的手册上。
 *
 * 2026-10-08 实测：给的是 `docs/overview/agent-operating-manual.md` 这样的相对路径，而手册
 * 住在源码 checkout 里 —— "去读手册"于是又变成"先找到 checkout"，会话照样为了
 * `expected_physical_identity` 的来源去翻 src/。桥从自己的安装位置解析，才消得掉这趟寻找。*/
function assertManualPathIn(hint, label) {
  const path = hint.slice(hint.lastIndexOf(": ") + 2).replace(/\.$/, "");
  assert.ok(isAbsolute(path) || win32.isAbsolute(path), `${label} 必须是绝对路径：${path}`);
  assert.equal(path, checkoutManual, `${label} 应当指向本 checkout 的手册，而不是一句相对指路`);
  assert.ok(existsSync(path), `${label} 指向的文件必须真的在磁盘上：${path}`);
}

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
  return { tools, instructions: client.getInstructions() };
}

test("主 Agent 的工具面里有 root.register / root.bind / repository.register", async (t) => {
  const { tools } = await listTools(t, "main");
  const names = tools.map((tool) => tool.name);
  for (const kind of ROOT_COMMANDS) {
    assert.ok(names.includes(toolNameFor(kind)),
      `主 Agent 缺 ${toolNameFor(kind)}（注册表里它是 principal=M，必须在工具面里）`);
  }
});

test("worker 的工具面里没有这三条（M 级命令照旧被过滤掉）", async (t) => {
  const { tools } = await listTools(t, "worker");
  const names = tools.map((tool) => tool.name);
  for (const kind of ROOT_COMMANDS) {
    assert.ok(!names.includes(toolNameFor(kind)), `worker 不该看到 ${toolNameFor(kind)}`);
  }
});

test("task__create 的描述直说空 scope 的含义", async (t) => {
  const { tools } = await listTools(t, "main");
  const described = String(tools.find((tool) => tool.name === "task__create")?.description ?? "");
  assert.ok(!described.includes("no explicit restriction"),
    "别再写 no explicit restriction —— 主 Agent 会读成“随便改”");
  assert.match(described, /CLAIMS NO PATH/, "要说清空 scope = 不认领任何路径");
  assert.match(described, /not recorded in the result/, "要说清改动不进结果");
});

// 2026-10-08 实测：main 发布三个任务后就等着，没人动；它以为 publish 等于"派活了"。
// 工具面必须直说发布是静默的，并指出"要有人开工"走哪条路（coordination.plan 默认发 task.assigned）。
test("task__publish 的描述直说发布不通知任何人", async (t) => {
  const { tools } = await listTools(t, "main");
  const described = String(tools.find((tool) => tool.name === "task__publish")?.description ?? "");
  assert.match(described, /SILENT/, "要说清 publish 是静默的");
  assert.match(described, /nobody is notified/, "要明说不会通知任何人");
  assert.match(described, /coordination__plan/, "要指出唤醒指名 worker 的那条路");
  assert.match(described, /task\.assigned/, "要说清 plan 默认发的是 task.assigned");
  assert.match(described, /supersedes_task_id/, "替代已发布任务要走 plan 的 supersedes_task_id，而不是先取消");
});

test("coordination__plan 的描述说清它才是唤醒与替代的那条路", async (t) => {
  const { tools } = await listTools(t, "main");
  const described = String(tools.find((tool) => tool.name === "coordination__plan")?.description ?? "");
  assert.match(described, /WAKES/, "要说清 plan 会唤醒指名的 worker");
  assert.match(described, /task\.assigned/, "要说清默认发的消息种类");
  assert.match(described, /supersedes_task_id/, "替代已发布的任务要走这里的 supersedes_task_id");
});

// 2026-10-08 实测：`coordination.plan` 的行内字段被 schema **漏声明**（items 里只声明了
// acceptance），主 Agent 因此断言"schema 参数和 handler 要的不一致"，转头去读源码、甚至打算
// 绕开桥直接打 HTTP。行内四个必填字段必须写在描述里，且要说清 task_objective 不是 objective。
test("coordination__plan 的描述列出每一行的必填字段与一次做了什么", async (t) => {
  const { tools } = await listTools(t, "main");
  const described = String(tools.find((tool) => tool.name === "coordination__plan")?.description ?? "");
  for (const field of ["assigned_worker_id", "title", "task_objective", "acceptance"]) {
    assert.ok(described.includes(field), `行内必填字段 ${field} 必须写进描述`);
  }
  assert.match(described, /not objective/, "要说清 task_objective 不是顶层那个 objective");
  assert.match(described, /create -> ready -> publish/, "要说清一行走完 create→ready→publish→指派→消息");
  assert.match(described, /SILENT/, "要对比 task__publish 的静默语义，否则 publish 会被当成派活");
});

// 2026-10-08 实测：`expected_physical_identity` 在文档里查不到，主 Agent 只好去读 handlers 源码
// 才明白它是个 inode 串、而且"不传就不校验"。字段级事实要写在描述里，连同"怎么取到它"。
test("root__register / root__bind 的描述说清 expected_physical_identity 与 repository_id", async (t) => {
  const { tools } = await listTools(t, "main");
  const register = String(tools.find((tool) => tool.name === "root__register")?.description ?? "");
  const bind = String(tools.find((tool) => tool.name === "root__bind")?.description ?? "");
  assert.match(bind, /expected_physical_identity/, "要把这个字段名写出来");
  assert.match(bind, /inode:/, "要说清它长什么样（物理身份串，不是路径）");
  assert.match(bind, /NOT the path/, "要说清它不是路径、也不是自己能算的哈希");
  assert.match(bind, /physical_identity/, "要说清从返回值里取它");
  assert.match(bind, /physical_identity_conflict/, "要说清不符时被拒的码");
  assert.match(bind, /bindings\.json/, "要明说别去私有状态文件里找它");
  assert.match(register, /IGNORES repository_id/, "要说清 handler 根本不读 repository_id");
  assert.match(register, /repository__register/, "要说清仓库要靠 repository.register 单独登记");
});

// 2026-10-08 实测：`contract.propose` 的 contract_id 被 schema 接受、被域静默丢掉，
// 于是 main 按自己起的标签引用契约，task.begin 被拒 4 次。描述必须说清它就是提案 id、要回引返回值。
test("contract__propose 的描述直说 contract_id 就是提案 id", async (t) => {
  const { tools } = await listTools(t, "main");
  const described = String(tools.find((tool) => tool.name === "contract__propose")?.description ?? "");
  assert.match(described, /proposal_id/, "要说清 contract_id 会成为 proposal_id");
  assert.match(described, /required_contract_ids/, "要说清任务引用的是这个值");
  assert.match(described, /mints a UUID/, "要说清省略时系统发 UUID");
  assert.match(described, /never a label of your own/, "别让自己的标签再混进来");
});

// 2026-10-08 实测：会话为了 `expected_physical_identity` 的来源去找 checkout、读 handlers.py；
// 指路只有相对路径时，"读手册"就等于"先找到 checkout"。启动时可见的那句必须给绝对路径。
test("instructions 里的操作手册指路是绝对路径，且文件真的在", async (t) => {
  const { instructions } = await listTools(t, "main");
  assert.ok(instructions.includes(OPERATING_MANUAL_LINE), "instructions 必须带上手册那句");
  assertManualPathIn(OPERATING_MANUAL_LINE, "instructions 里的手册路径");
  assert.match(OPERATING_MANUAL_LINE, /expected_physical_identity/,
    "要说清手册里有这类必填值的来源，看到这句就不必读源码");
  assert.match(OPERATING_MANUAL_LINE, /refusal codes/, "要说清拒绝码也在手册里");
  assert.ok(!OPERATING_MANUAL_LINE.includes("docs/overview/agent-operating-manual.md"),
    "这个 checkout 里有手册，就不该再发相对路径");
  // 这段文本在**每次模型调用**上重复付费（方案第 5 项）：曾经的 840 字符里塞着唤醒通道与
  // 派活规矩，它们每会话只需要听一次，已经搬去首次读取。这里钉一个上限，防止再长回来。
  assert.ok(instructions.length <= 420,
    `instructions 每次都付费，必须保持精简（当前 ${instructions.length} 字符，上限 420）`);
});
