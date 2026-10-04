import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { writePrivateJson } from "../dist/private-file.js";

const bridge = fileURLToPath(new URL("../dist/server.js", import.meta.url));
const helper = fileURLToPath(new URL("connect-context.mjs", import.meta.url));
const baseEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(TSUNAGOU_|CODEX_)/.test(key)));
const hash = (text) => createHash("sha256").update(text).digest("hex");
const read = (path) => JSON.parse(readFileSync(path, "utf8"));
const respond = (response, result) => response.end(JSON.stringify({ result }));

async function fixture(t, role = "main", metaKey = "threadId") {
  const root = mkdtempSync(join(tmpdir(), "tsunagou-console-arrival-"));
  const receiptFile = join(root, "receipt.json");
  const sessionFile = join(root, "session.json");
  const routingDir = join(root, "routes");
  const thread = "original-host-thread";
  const routeFile = join(routingDir, hash(thread) + ".json");
  const credential = {
    agent_id: "agent-original", session_id: "session-original", connection_epoch: 1,
    secret_token: "private-secret-sentinel", reconnect_nonce: "private-nonce-sentinel", baseline_status: "ready",
    conversation_binding_digest: hash("conversation_id:" + thread),
    host_conversation_id_digest: hash("conversation_id:" + thread),
  };
  const context = (epoch = 1) => ({
    project_id: "project-original", agent_id: credential.agent_id, role,
    session: { session_id: credential.session_id, connection_epoch: epoch, status: "ready" },
  });
  const calls = [];
  const hooks = {};
  const server = createServer(async (request, response) => {
    let raw = "";
    for await (const chunk of request) raw += chunk;
    const call = { path: request.url, headers: request.headers, body: JSON.parse(raw || "{}") };
    calls.push(call);
    response.setHeader("content-type", "application/json");
    if (hooks.handle) return hooks.handle(call, response);
    respond(response, context());
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const route = {
    format_version: 1, conversation_id: thread, project_id: "project-original", project_root: root,
    daemon_state_dir: join(root, "daemon"), ticket_file: join(root, "absent-ticket.json"),
    session_file: sessionFile, state_dir: root,
    console_enrollment: { enrollment_id: "enrollment-original", requested_role: role, receipt_file: receiptFile },
  };
  writePrivateJson(join(root, "daemon", "endpoint.json"), { url: `http://127.0.0.1:${server.address().port}` });
  writePrivateJson(sessionFile, credential);
  writePrivateJson(routeFile, route);
  const clients = [];
  const env = { ...baseEnv, TSUNAGOU_ROUTING_DIR: routingDir, TSUNAGOU_HOST_META_KEY: metaKey };
  const connect = async (extra = {}) => {
    const transport = new StdioClientTransport({ command: process.execPath, args: [bridge],
      env: { ...env, ...extra }, stderr: "pipe" });
    const client = new Client({ name: "console-arrival-test", version: "0.1.0" }, { capabilities: {} });
    clients.push(client);
    await client.connect(transport);
    return client;
  };
  t.after(async () => {
    await Promise.all(clients.map((client) => client.close().catch(() => {})));
    await new Promise((resolve) => server.close(resolve));
    rmSync(root, { recursive: true, force: true });
  });
  const call = (client, identity = thread, name = "context__project_read") => client.callTool({ name, arguments: {},
    ...(identity ? { _meta: { [metaKey]: identity } } : {}),
  });
  return { root, receiptFile, sessionFile, routeFile, route, credential, context, thread, calls, hooks, env, connect, call };
}

for (const metaKey of ["threadId", "ai.opencode/sessionID"]) {
for (const role of ["main", "worker"]) {
  test(`${metaKey}: an already loaded shared bridge records the original ${role} context after its route is added`, async (t) => {
    const f = await fixture(t, role, metaKey);
    const { console_enrollment: enrollment, ...oldRoute } = f.route;
    writePrivateJson(f.routeFile, oldRoute);
    const client = await f.connect();
    assert.ok(!(await f.call(client)).isError);
    assert.equal(existsSync(f.receiptFile), false);
    writePrivateJson(f.routeFile, { ...oldRoute, console_enrollment: enrollment });
    assert.ok(!(await f.call(client)).isError);
    const receipt = read(f.receiptFile);
    assert.deepEqual({ ...receipt, observed_at: undefined }, {
      format_version: 1, enrollment_id: enrollment.enrollment_id, thread_id: f.thread,
      project_id: f.route.project_id, agent_id: f.credential.agent_id, role,
      session_id: f.credential.session_id, connection_epoch: 1, observed_at: undefined,
    });
    assert.ok(Number.isFinite(Date.parse(receipt.observed_at)));
    assert.ok(!readFileSync(f.receiptFile, "utf8").includes("sentinel"));
    if (process.platform !== "win32") assert.equal(statSync(f.receiptFile).mode & 0o777, 0o600);
    const restarted = await f.connect();
    assert.ok(!(await f.call(restarted)).isError);
    assert.equal(read(f.receiptFile).agent_id, receipt.agent_id);
  });
}

}

test("only a matching ready own context can produce a receipt", async (t) => {
  const f = await fixture(t);
  const client = await f.connect();
  assert.equal((await f.call(client, "")).isError, true);
  assert.equal((await f.call(client, "another-thread")).isError, true);
  const good = f.context();
  const invalid = [
    { ...good, project_id: "another-project" }, { ...good, role: "worker" },
    { ...good, agent_id: "another-agent" }, { ...good, agent_id: "" },
    { ...good, session: { ...good.session, status: "degraded" } },
    { ...good, session: { ...good.session, session_id: "another-session" } },
    { ...good, session: { ...good.session, connection_epoch: 2 } },
    { ...good, session: null },
  ];
  for (const context of invalid) {
    f.hooks.handle = (_call, response) => respond(response, context);
    assert.ok(!(await f.call(client)).isError);
    assert.equal(existsSync(f.receiptFile), false);
  }
  f.hooks.handle = (_call, response) => {
    response.statusCode = 403;
    response.end(JSON.stringify({ detail: { code: "capability_denied" } }));
  };
  assert.equal((await f.call(client)).isError, true);
  f.hooks.handle = (_call, response) => respond(response, good);
  assert.ok(!(await f.call(client, f.thread, "inbox__claim")).isError);
  assert.equal(existsSync(f.receiptFile), false);
  assert.ok(!(await f.call(client)).isError);
  assert.equal(read(f.receiptFile).role, "main");
});

test("CLI helper forces its marker even when a config tries to unset it", async (t) => {
  const f = await fixture(t);
  const client = await f.connect({ TSUNAGOU_CONNECT_HELPER: "1" });
  assert.ok(!(await f.call(client)).isError);
  assert.equal(existsSync(f.receiptFile), false);
  const configFile = join(f.root, "helper-config.json");
  const requestFile = join(f.root, "helper-request.json");
  writePrivateJson(configFile, { command: process.execPath, args: [bridge],
    env: { TSUNAGOU_ROUTING_DIR: f.env.TSUNAGOU_ROUTING_DIR, TSUNAGOU_CONNECT_HELPER: "0" } });
  writePrivateJson(requestFile, { conversation_id: f.thread });
  const output = await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [helper, configFile, requestFile], { env: baseEnv, windowsHide: true });
    let stdout = "";
    child.stdout.on("data", (data) => { stdout += data; });
    child.once("error", reject);
    child.once("close", (code) => code === 0 ? resolve(stdout) : reject(new Error(`helper failed: ${stdout}`)));
  });
  assert.equal(JSON.parse(output).agent_id, f.credential.agent_id);
  assert.equal(existsSync(f.receiptFile), false);
});

test("concurrent late contexts cannot overwrite a newer receipt", async (t) => {
  const f = await fixture(t);
  const client = await f.connect();
  let releaseOld;
  let reportOld;
  const oldStarted = new Promise((resolve) => { reportOld = resolve; });
  f.hooks.handle = async (call, response) => {
    const epoch = Number(call.headers["tsunagou-connection-epoch"]);
    if (epoch === 1) {
      reportOld();
      await new Promise((resolve) => { releaseOld = resolve; });
    }
    respond(response, f.context(epoch));
  };
  const oldCall = f.call(client);
  await oldStarted;
  writePrivateJson(f.sessionFile, { ...f.credential, connection_epoch: 2 });
  assert.ok(!(await f.call(client)).isError);
  assert.equal(read(f.receiptFile).connection_epoch, 2);
  releaseOld();
  assert.ok(!(await oldCall).isError);
  assert.equal(read(f.receiptFile).connection_epoch, 2);
  // Also retain a newer recorded observation if the credential file was restored
  // from an older snapshot; the receipt's independent epoch fence still applies.
  writePrivateJson(f.sessionFile, f.credential);
  f.hooks.handle = (_call, response) => respond(response, f.context());
  assert.ok(!(await f.call(client)).isError);
  assert.equal(read(f.receiptFile).connection_epoch, 2);
});

test("startup binding restoration alone never records original-host arrival", async (t) => {
  const f = await fixture(t);
  const endpoint = "new-desktop-generation-fixture";
  f.hooks.handle = (call, response) => {
    assert.equal(call.path, "/api/v1/commands/session.reconnect");
    respond(response, { ...f.credential, connection_epoch: 2 });
  };
  const client = await f.connect({ CODEX_APP_TOOLS_PIPE_PATH: endpoint });
  const deadline = Date.now() + 5000;
  while (read(f.sessionFile).host_binding_generation !== hash(endpoint)) {
    assert.ok(Date.now() < deadline, "startup restoration did not complete");
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  await client.listTools();
  assert.ok(f.calls.length > 0);
  assert.equal(existsSync(f.receiptFile), false);
});

test("DeepSeek routed context never records Codex console arrival or refreshes its binding", async (t) => {
  const f = await fixture(t);
  writePrivateJson(f.routeFile, { ...f.route, endpoint: "stale-codex-endpoint" });
  f.hooks.handle = (call, response) => {
    assert.equal(call.path, "/api/v1/commands/context.project_read");
    respond(response, f.context());
  };
  const client = await f.connect({
    TSUNAGOU_HOST_META_KEY: "tsunagou.hostSessionId",
    TSUNAGOU_DESKTOP_WAKE: "1", CODEX_APP_TOOLS_PIPE_PATH: "unrelated-codex-parent",
  });
  await client.listTools();
  assert.equal(f.calls.length, 0);
  assert.equal((await f.call(client)).isError, true, "Codex metadata cannot select a DeepSeek route");
  assert.equal(f.calls.length, 0);
  const result = await client.callTool({ name: "context__project_read", arguments: {},
    _meta: { "tsunagou.hostSessionId": f.thread },
  });
  assert.ok(!result.isError, JSON.stringify(result.content));
  assert.equal(f.calls.length, 1);
  assert.equal(existsSync(f.receiptFile), false, "a matching DeepSeek context is not a Codex arrival");
  assert.equal(read(f.sessionFile).connection_epoch, 1);
  assert.equal(read(f.sessionFile).host_binding_generation, undefined);
  assert.equal(read(f.routeFile).endpoint, "stale-codex-endpoint");
});


test("OpenCode native metadata records receipt without Codex wake; helper stays silent", async (t) => {
  const f = await fixture(t, "worker", "ai.opencode/sessionID");
  const extra = { CODEX_APP_TOOLS_PIPE_PATH: "unrelated-parent", TSUNAGOU_DESKTOP_WAKE: "1" };
  const helperClient = await f.connect({ ...extra, TSUNAGOU_CONNECT_HELPER: "1" });
  assert.ok(!(await f.call(helperClient)).isError);
  assert.equal(existsSync(f.receiptFile), false);
  const client = await f.connect(extra);
  assert.equal((await f.call(client, "another-chat")).isError, true);
  assert.equal((await f.call(client, "")).isError, true);
  assert.equal(existsSync(f.receiptFile), false);
  assert.ok(!(await f.call(client)).isError);
  assert.equal(read(f.receiptFile).thread_id, f.thread);
  assert.ok(f.calls.every(call => call.path === "/api/v1/commands/context.project_read"));
});
