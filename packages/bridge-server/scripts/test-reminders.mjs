import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { writePrivateJson } from "../dist/private-file.js";

import { WAKE_REMINDER as wake, WAKE_INSTRUCTIONS } from "../dist/reminders.js";

const completion = "如果所有工作已经完成，且合并与验收已通过，请记得调用 `project__completion_propose` 发起任务完成提案，不要仅在聊天中宣布完成。已有待确认的提案时不要重复提交，最终完工由用户确认。";
const hash = (value) => createHash("sha256").update(value).digest("hex");

async function fixture(t, metaKey) {
  const root = mkdtempSync(join(tmpdir(), "tsunagou-reminders-"));
  const calls = [];
  const state = { main: "agent-a", fail: undefined, context: undefined, result: undefined, wake: undefined };
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
      response.end(JSON.stringify({ result: kind === "context.project_read" ? context(agent) : kind === "coordination.wake_status" ? state.wake : kind === "coordination.wake_candidates" ? {messages: state.result?.messages ?? []} : state.result ?? result }));
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
  const connect = async () => {
    const transport = new StdioClientTransport({ command: process.execPath,
      args: [fileURLToPath(new URL("../dist/server.js", import.meta.url))],
      env: { ...env, TSUNAGOU_ROUTING_DIR: routingDir, TSUNAGOU_HOST_META_KEY: metaKey }, stderr: "pipe" });
    const client = new Client({ name: "reminder-test", version: "1.0.0" }, { capabilities: {} });
    await client.connect(transport);
    return client;
  };
  let client = await connect();
  const restart = async () => { await client.close(); client = await connect(); };
  t.after(async () => {
    await client.close();
    await new Promise((resolve) => server.close(resolve));
    rmSync(root, { recursive: true, force: true });
  });
  const { tools } = await client.listTools();
  const call = (kind, agent = "agent-a", args = {}) => {
    // Review tools have historical flat names, so resolve via the explicit mapping.
    const name = kind.startsWith("task.review.") ? kind.replace("task.review.", "task__review_") : kind.replaceAll(".", "__");
    assert.ok(tools.some((tool) => tool.name === name), name);
    return client.callTool({ name, arguments: args, _meta: { [metaKey]: agent } });
  };
  return { root, calls, state, result, context, client, call, restart };
}

function check(output, result, hints) {
  assert.ok(!output.isError);
  assert.deepEqual(output.content, [{ type: "text", text: JSON.stringify(result) },
    ...hints.map((text) => ({ type: "text", text }))]);
}

for (const metaKey of ["threadId", "ai.opencode/sessionID", "tsunagou.hostSessionId"]) {
  test(`${metaKey}: persistent first guide, quiet calls, scoped hints and original JSON`, async (t) => {
    const f = await fixture(t, metaKey);
    assert.ok(f.client.getInstructions().includes(WAKE_INSTRUCTIONS));
    assert.ok(!f.client.getInstructions().includes(wake));
    assert.ok(wake.includes("Codex → Codex 只走现有 Tsunagou Codex 通道"));
    assert.ok(wake.includes("不要求用户手动唤醒"));

    check(await f.call("task.review.accept"), f.result, [completion]);
    assert.equal(existsSync(join(f.root, "agent-a-receipt.json")), false);
    check(await f.call("context.project_read"), f.context("agent-a"), [wake, completion]);
    check(await f.call("context.project_read"), f.context("agent-a"), [completion]);
    const reminders = join(f.root, "daemon", "reminders");
    for (const file of readdirSync(reminders)) writePrivateJson(join(reminders, file), {guide_version:"old-version"});
    check(await f.call("context.project_read"), f.context("agent-a"), [wake, completion]);
    check(await f.call("context.project_read", "agent-b"), f.context("agent-b"), [wake]);
    await f.restart();
    check(await f.call("context.project_read", "agent-b"), f.context("agent-b"), []);
    check(await f.call("context.project_read"), f.context("agent-a"), [completion]);
    f.state.main = "agent-b";
    check(await f.call("task.review.accept"), f.result, []);
    check(await f.call("task.self_accept", "agent-b"), f.result, [completion]);
    for (const kind of ["coordination.takeover", "task.publish", "task.review.request_changes", "message.send",
      "message.respond", "inbox.claim", "task.begin", "project.completion_propose"]) {
      const before = f.calls.length;
      check(await f.call(kind), f.result, []);
      assert.equal(f.calls.length, before + 1);
    }
    f.state.wake = {message_id: "message-one", target: {agent_id:"agent-b",host:"opencode",version:"2.0.18",machine:"local"},
      lane:"fallback",state:"idle",can_queue:true,result:"observed",entry:{tool:"coordination__wake",arguments:{message_id:"message-one"}},progress:{durably_received:true,host_turn_started:false,presented:false,business_response:false}};
    f.state.result = {message_id: "message-one",recipient_agent_id:"agent-b"};
    const required = {response_contract: {required:true}};
    const output = await f.call("message.send", "agent-a", required);
    assert.equal(output.content[0].text, JSON.stringify(f.state.result));
    assert.equal(output.content.length, 2);
    assert.ok(output.content[1].text.includes('coordination__wake {"message_id":"message-one"}'));
    check(await f.call("message.send", "agent-a", required), f.state.result, []);
    await f.restart();
    check(await f.call("message.send", "agent-a", required), f.state.result, []);
    f.state.wake = {...f.state.wake,state:"running",result:"queued",request_associated:true};
    assert.ok((await f.call("message.send", "agent-a", required)).content[1].text.includes("不追加回合"));
    f.state.wake = {...f.state.wake,lane:"native",result:"failed"};
    const nativeHint = (await f.call("message.send", "agent-a", required)).content[1].text;
    assert.ok(nativeHint.includes("路由不代表已派发"));
    assert.ok(nativeHint.includes("仅在确认已有派发或处理时避免重复"));
    assert.ok(!nativeHint.includes("不追加唤醒"));
    f.state.wake = {...f.state.wake,native:{enabled:false,outbox_status:"pending",attempt_count:0}};
    assert.ok((await f.call("message.send", "agent-a", required)).content[1].text.includes("项目已明确关闭"));
    for (let index = 0; index < 2; index++) {
      const explicit = await f.call("coordination.wake_status", "agent-a", {message_id:"message-one"});
      assert.equal(explicit.content[0].text, JSON.stringify(f.state.wake));
      assert.equal(explicit.content.length, 2);
    }
    f.state.wake = {...f.state.wake,message_id:"submitted-message",lane:"fallback",state:"unknown"};
    f.state.result = {result_id:"result-one",messages:[{message_id:"submitted-message"}]};
    const submitted = await f.call("task.submit", "agent-b", {command_id:"original-submit-id"});
    assert.equal(submitted.content[0].text, JSON.stringify(f.state.result));
    assert.equal(submitted.content.length, 2);
    const query = f.calls.find(({kind}) => kind === "coordination.wake_candidates");
    assert.equal(query.body.payload.source_command_id, "original-submit-id");
    assert.equal(query.agent, "agent-b");
    for (const result of ["same_request_running", "already_delivered", "failed", "unknown", "unsupported"]) {
      f.state.wake = {...f.state.wake,state:"idle",result,error_code:"host_test_failure",entry:{tool:"coordination__wake_status"}};
      const guarded = await f.call("coordination.wake_status", "agent-a", {message_id:"submitted-message"});
      assert.ok(!guarded.content[1].text.includes('显式调用 coordination__wake '));
      assert.ok(guarded.content[1].text.includes("host_test_failure"));
    }
    const diagnostics = {stage:"process",interpreter:"powershell",interpreter_version:"5.1.19041.1",
      exit_code:1,error_class:"powershell_parse_error"};
    f.state.wake = {...f.state.wake,result:"unknown",error_code:"host_runner_failed",diagnostics};
    f.state.result = {message_id:"submitted-message"};
    const failure = await f.call("message.send", "agent-a", required);
    assert.equal(failure.content[0].text, JSON.stringify(f.state.result));
    assert.ok(failure.content[1].text.includes("停止重复尝试同一失败路径"));
    assert.ok(failure.content[1].text.includes("仅调用一次 coordination__wake_status"));
    assert.ok(failure.content[1].text.includes("解释器=powershell"));
    assert.ok(failure.content[1].text.includes("错误类别=powershell_parse_error"));
    check(await f.call("message.send", "agent-a", required), f.state.result, []);
    const inspected = await f.call("coordination.wake_status", "agent-a", {message_id:"submitted-message"});
    assert.equal(inspected.content[0].text, JSON.stringify(f.state.wake));
    assert.ok(inspected.content[1].text.includes("本次已查询"));
    assert.ok(inspected.content[1].text.includes("不循环查询或再次唤醒"));
    assert.ok(inspected.content[1].text.includes("worker 向 main 升级一次"));
    assert.ok(inspected.content[1].text.includes("main 自己记录阻塞"));
    assert.ok(!inspected.content[1].text.includes("先调用 coordination__wake_status"));
    assert.ok(!inspected.content[1].text.includes("尚未执行唤醒操作"));
    f.state.wake = {...f.state.wake,preflight_failed:true};
    const preflight = await f.call("coordination.wake_status", "agent-a", {message_id:"submitted-message"});
    assert.ok(preflight.content[1].text.includes("本次前置检查失败，尚未执行唤醒操作"));
    assert.ok(!preflight.content[1].text.includes("本次已查询"));
    assert.ok(!preflight.content[1].text.includes("核实是否已启动"));
    f.state.wake = {...f.state.wake,state:"idle",result:"observed",error_code:"wake_already_attempted",
      prior_result:"unknown",retry_allowed:false,diagnostics:undefined,prior_diagnostics:diagnostics,preflight_failed:undefined};
    const prior = await f.call("coordination.wake_status", "agent-a", {message_id:"submitted-message"});
    assert.ok(prior.content[1].text.includes("上次执行诊断：阶段=process"));
    assert.ok(prior.content[1].text.includes("不循环查询或再次唤醒"));
    for (const invalid of [{}, {agent_id:"",main_agent_id:""}, {agent_id:1,main_agent_id:1}]) {
      f.state.context = invalid;
      check(await f.call("context.project_read"), invalid, []);
    }
    f.state.context = undefined;
    f.state.result = undefined;
    f.state.fail = "context.project_read";
    check(await f.call("task.review.accept"), f.result, []);
    const failed = await f.call("context.project_read");
    assert.equal(failed.isError,true);
    assert.equal(failed.content.length,1);
    assert.ok(!JSON.stringify(failed).includes("token-agent"));
    assert.equal(f.calls.some(({kind}) => kind === "coordination.wake"), false);
  });
}
