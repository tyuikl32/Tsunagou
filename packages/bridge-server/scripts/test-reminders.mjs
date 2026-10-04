import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { writePrivateJson } from "../dist/private-file.js";

const wake = "需要唤醒其他 Agent 时，请通过 PowerShell 执行对应宿主的唤醒操作；发起方和接收方都为 Codex 时，沿用 Codex 已有的唤醒机制。请确认是否确实需要唤醒，避免重复操作。请优先使用已验证的宿主原会话入口，不要把尚未完整实现或未经当前宿主验证的 Tsunagou 自动唤醒当作前提，也不要反复配置、探测或重绑来等待它生效。各宿主操作指南：优先读取当前安装源码中的 docs/overview/agent-wake-guide.md；在线入口 https://github.com/tyuikl32/Tsunagou/blob/HEAD/docs/overview/agent-wake-guide.md（未发布的本地更新以安装源码为准）。消息已入队不等于对方已开始新回合。唤醒失败时先自行排查是否认错目标厂商或宿主、原会话及操作入口，依据真实注册信息纠正后再试；不要请用户手动唤醒。仍受真实能力或权限阻塞时，向 main 记录证据和未解决状态，不要宣称成功或扩大权限。";
const completion = "如果所有工作已经完成，且合并与验收已通过，请记得调用 `project__completion_propose` 发起任务完成提案，不要仅在聊天中宣布完成。已有待确认的提案时不要重复提交，最终完工由用户确认。";
const hash = (value) => createHash("sha256").update(value).digest("hex");

async function fixture(t, metaKey) {
  const root = mkdtempSync(join(tmpdir(), "tsunagou-reminders-"));
  const calls = [];
  const state = { main: "agent-a", fail: undefined, context: undefined };
  const result = { accepted: true, nested: { evidence: ["unchanged"] } };
  const context = (agent) => state.context ?? { agent_id: agent, main_agent_id: state.main,
    // Deliberately stale role: only authoritative main_agent_id decides guidance.
    role: "main", project_id: "project", session: { session_id: `session-${agent}`, connection_epoch: 1, status: "ready" } };
  const server = createServer(async (request, response) => {
    let raw = "";
    for await (const chunk of request) raw += chunk;
    const kind = request.url.split("/").at(-1);
    const agent = request.headers.authorization === "Bearer token-agent-a" ? "agent-a" : "agent-b";
    calls.push({ kind, agent, body: JSON.parse(raw), session: request.headers["tsunagou-session-id"] });
    response.setHeader("content-type", "application/json");
    if (state.fail === kind) {
      response.statusCode = 403;
      response.end(JSON.stringify({ detail: { code: "capability_denied" } }));
    } else {
      response.end(JSON.stringify({ result: kind === "context.project_read" ? context(agent) : result }));
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const routingDir = join(root, "routes");
  for (const agent of ["agent-a", "agent-b"]) {
    const sessionFile = join(root, `${agent}.json`);
    writePrivateJson(sessionFile, { agent_id: agent, session_id: `session-${agent}`, connection_epoch: 1,
      secret_token: `token-${agent}`, reconnect_nonce: `nonce-${agent}`, baseline_status: "ready",
      conversation_binding_digest: hash(`conversation_id:${agent}`),
      host_conversation_id_digest: hash(`conversation_id:${agent}`) });
    writePrivateJson(join(routingDir, hash(agent) + ".json"), {
      format_version: 1, conversation_id: agent, project_id: "project", project_root: root,
      daemon_state_dir: join(root, "daemon"), session_file: sessionFile, state_dir: root,
      ticket_file: join(root, "absent-ticket.json"),
      console_enrollment: { enrollment_id: `enrollment-${agent}`, requested_role: "main", receipt_file: join(root, `${agent}-receipt.json`) },
    });
  }
  writePrivateJson(join(root, "daemon", "endpoint.json"), { url: `http://127.0.0.1:${server.address().port}` });
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(TSUNAGOU_|CODEX_)/.test(key)));
  const transport = new StdioClientTransport({ command: process.execPath,
    args: [fileURLToPath(new URL("../dist/server.js", import.meta.url))],
    env: { ...env, TSUNAGOU_ROUTING_DIR: routingDir, TSUNAGOU_HOST_META_KEY: metaKey }, stderr: "pipe" });
  const client = new Client({ name: "reminder-test", version: "1.0.0" }, { capabilities: {} });
  t.after(async () => {
    await client.close();
    await new Promise((resolve) => server.close(resolve));
    rmSync(root, { recursive: true, force: true });
  });
  await client.connect(transport);
  const { tools } = await client.listTools();
  const call = (kind, agent = "agent-a", args = {}) => {
    // Review tools have historical flat names, so resolve via the explicit mapping.
    const name = kind.startsWith("task.review.") ? kind.replace("task.review.", "task__review_") : kind.replaceAll(".", "__");
    assert.ok(tools.some((tool) => tool.name === name), name);
    return client.callTool({ name, arguments: args, _meta: { [metaKey]: agent } });
  };
  return { root, calls, state, result, context, client, call };
}

function check(output, result, hints) {
  assert.ok(!output.isError);
  assert.deepEqual(output.content, [{ type: "text", text: JSON.stringify(result) },
    ...hints.map((text) => ({ type: "text", text }))]);
}

for (const metaKey of ["threadId", "ai.opencode/sessionID", "tsunagou.hostSessionId"]) {
  test(`${metaKey}: real stdio reminders preserve JSON, role isolation and operation boundaries`, async (t) => {
    const f = await fixture(t, metaKey);
    assert.ok(f.client.getInstructions().includes(wake));
    assert.ok(!f.client.getInstructions().includes("project__completion_propose"));

    // An internal role lookup must not impersonate an original-host context read.
    check(await f.call("task.review.accept"), f.result, [wake, completion]);
    assert.equal(existsSync(join(f.root, "agent-a-receipt.json")), false);
    assert.deepEqual(f.calls.map(({ kind }) => kind), ["task.review.accept", "context.project_read"]);

    check(await f.call("context.project_read"), f.context("agent-a"), [wake, completion]);
    check(await f.call("context.project_read", "agent-b"), f.context("agent-b"), [wake]);
    check(await f.call("task.self_accept", "agent-b", { role: "main", agent_id: "agent-a" }), f.result, [wake]);
    assert.equal(f.calls.at(-1).session, "session-agent-b");
    f.state.main = "agent-b";
    check(await f.call("task.review.accept"), f.result, [wake]);
    check(await f.call("task.self_accept", "agent-b"), f.result, [wake, completion]);

    for (const kind of ["coordination.plan", "coordination.takeover", "task.publish", "task.submit",
      "task.review.request_changes", "message.send", "message.respond"]) {
      const before = f.calls.length;
      check(await f.call(kind), f.result, [wake]);
      assert.deepEqual(f.calls.slice(before).map((row) => row.kind), [kind]);
    }
    for (const kind of ["inbox.claim", "task.begin", "project.completion_propose"]) {
      const before = f.calls.length;
      check(await f.call(kind), f.result, []);
      assert.deepEqual(f.calls.slice(before).map((row) => row.kind),
        [kind === "project.completion_propose" ? "project.completion.propose.main" : kind]);
    }
    for (const invalid of [{}, { agent_id: "", main_agent_id: "" }, { agent_id: 1, main_agent_id: 1 },
      { agent_id: "agent-a", role: "main" }]) {
      f.state.context = invalid;
      check(await f.call("context.project_read"), invalid, [wake]);
    }
    f.state.context = undefined;
    f.state.fail = "context.project_read";
    check(await f.call("task.review.accept"), f.result, [wake]);
    const failedContext = await f.call("context.project_read");
    assert.equal(failedContext.isError, true);
    assert.equal(failedContext.content.length, 1);
    f.state.fail = "task.review.accept";
    const before = f.calls.length;
    const failed = await f.call("task.review.accept");
    assert.equal(failed.isError, true);
    assert.equal(failed.content.length, 1);
    assert.equal(JSON.parse(failed.content[0].text).code, "capability_denied");
    assert.deepEqual(f.calls.slice(before).map((row) => row.kind), ["task.review.accept"]);
    assert.ok(!JSON.stringify(failed).includes("token-agent"));
  });
}
