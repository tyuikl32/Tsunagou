import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { CredentialHandoff, loadSession, parseCredential } from "../dist/credential-handoff.js";
import { writePrivateJson } from "../dist/private-file.js";
import { withPrivateFileLock } from "../dist/private-file-lock.js";

const ticket = { installation_id: "codex:one", conversation_id: "conversation-one", secret: "ticket-sentinel" };
const credential = {
  agent_id: "agent-one", session_id: "session-one", connection_epoch: 1,
  secret_token: "credential-sentinel", reconnect_nonce: "nonce-sentinel", baseline_status: "ready",
  receipt_id: "receipt-one", delivery_ref: "delivery:one", delivery_status: "delivered",
  created_at: "2026-09-27T17:00:00.000Z", expires_at: "2026-09-27T17:10:00.000Z",
  delivered_at: "2026-09-27T17:00:01.000Z", consumed_at: null,
};

async function fixture(t, handle) {
  const root = mkdtempSync(join(tmpdir(), "tsunagou-credential-test-"));
  const sessionFile = join(root, "session.json");
  const ticketFile = join(root, "ticket.json");
  writePrivateJson(ticketFile, ticket);
  const calls = [];
  const server = createServer(async (request, response) => {
    let text = "";
    for await (const chunk of request) text += chunk;
    const call = { path: request.url, headers: request.headers, text, body: JSON.parse(text || "{}") };
    calls.push(call);
    response.setHeader("content-type", "application/json");
    await handle(call, response, { sessionFile, ticketFile, calls });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    await new Promise((resolve) => server.close(resolve));
    rmSync(root, { recursive: true, force: true });
  });
  const options = {
    baseUrl: `http://127.0.0.1:${server.address().port}`, protocolVersion: "1.0",
    schemaBundleDigest: "schema-fixture", sessionFile, conversationBindingDigest: "conversation-digest",
    hostDigest: "host-digest",
  };
  const input = { ticket, ticketFile, baseline: { observation: "before-loss" } };
  return { root, sessionFile, ticketFile, calls, options, input };
}

const isAck = (call) => call.path.endsWith("/ack");
function respond(response, result) { response.end(JSON.stringify({ result })); }
function ack(response) { response.end(JSON.stringify({ delivery_status: "consumed" })); }

test("reconnect carries private Desktop refresh without changing the target identity", async (t) => {
  const refresh = { provider: "codex_desktop_app", endpoint: "private-pipe-sentinel", host_generation: "generation-2" };
  const f = await fixture(t, (call, response) => {
    if (isAck(call)) return ack(response);
    assert.equal(call.path, "/api/v1/commands/session.reconnect");
    assert.deepEqual(call.body.payload.host_binding_refresh, refresh);
    assert.equal(call.body.payload.target_agent_id, undefined);
    assert.equal(call.body.payload.thread_id, undefined);
    respond(response, { ...credential, connection_epoch: 2, secret_token: "new-credential", reconnect_nonce: "new-nonce" });
  });
  writePrivateJson(f.sessionFile, { ...credential, conversation_binding_digest: "conversation-digest", host_conversation_id_digest: "host-digest" });
  const session = await new CredentialHandoff(f.options).recover({ forceReconnect: true, hostBindingRefresh: refresh });
  assert.equal(session.agent_id, credential.agent_id);
  assert.equal(session.connection_epoch, 2);
  assert.ok(!readFileSync(f.sessionFile, "utf8").includes(refresh.endpoint));
});

test("overlapping and late host restores rotate a generation only once", async (t) => {
  const refresh = { provider: "codex_desktop_app", endpoint: "new-private-pipe", host_generation: "new-generation" };
  const waiting = [];
  const f = await fixture(t, (call, response) => {
    if (isAck(call)) return ack(response);
    assert.equal(call.path, "/api/v1/commands/session.reconnect");
    waiting.push(response);
    if (waiting.length === 2) {
      for (const reply of waiting) respond(reply, { ...credential, connection_epoch: 2,
        secret_token: "refreshed-token", reconnect_nonce: "refreshed-nonce" });
    }
  });
  writePrivateJson(f.sessionFile, { ...credential, host_binding_generation: "old-generation",
    conversation_binding_digest: f.options.conversationBindingDigest });
  const initial = await Promise.all([0, 1].map(() => new CredentialHandoff(f.options).recover({ hostBindingRefresh: refresh })));
  assert.ok(initial.every((session) => session.connection_epoch === 2 && session.host_binding_generation === refresh.host_generation));
  const before = f.calls.filter((call) => !isAck(call));
  assert.equal(before.length, 2);
  assert.equal(before[0].text, before[1].text);
  // A restore selected before the first exchange can enter prepare after it
  // completes. It must compare against the current locked session, not rotate
  // again merely because its caller previously observed the old generation.
  const late = await new CredentialHandoff(f.options).recover({ hostBindingRefresh: refresh });
  assert.equal(late.connection_epoch, 2);
  assert.equal(f.calls.filter((call) => !isAck(call)).length, 2);
});

test("lost enrollment response and restart reuse exact envelope and original baseline", async (t) => {
  let attempts = 0;
  const f = await fixture(t, (call, response, { sessionFile }) => {
    if (isAck(call)) {
      assert.equal(loadSession(sessionFile).secret_token, credential.secret_token);
      assert.equal(call.headers.authorization, `Bearer ${credential.secret_token}`);
      assert.equal(call.headers["tsunagou-session-id"], credential.session_id);
      assert.equal(call.headers["tsunagou-connection-epoch"], "1");
      return ack(response);
    }
    if (++attempts === 1) return response.destroy();
    respond(response, credential);
  });
  await assert.rejects(new CredentialHandoff(f.options).recover(f.input), /retry_pending_request/);
  const pendingText = readFileSync(`${f.sessionFile}.pending.json`, "utf8");
  assert.ok(!pendingText.includes(ticket.secret));
  assert.ok(!pendingText.includes(credential.secret_token));
  const recovered = await new CredentialHandoff(f.options).recover({ ...f.input, baseline: { observation: "after-restart" } });
  assert.equal(recovered.agent_id, credential.agent_id);
  assert.equal(recovered.delivery_ack_pending, false);
  assert.equal(f.calls[0].text, f.calls[1].text);
  assert.deepEqual(f.calls[1].body.payload.probe_payload, f.input.baseline);
  assert.equal(f.calls[2].path, "/api/v1/credential-deliveries/delivery%3Aone/ack");
  assert.equal(existsSync(`${f.sessionFile}.pending.json`), false);
  assert.equal(existsSync(f.ticketFile), false);
});

test("lost reconnect response reuses original token, nonce, epoch and command", async (t) => {
  let attempts = 0;
  const rotated = { ...credential, secret_token: "rotated-token", reconnect_nonce: "rotated-nonce", connection_epoch: 2 };
  const f = await fixture(t, (call, response) => {
    if (isAck(call)) return ack(response);
    assert.equal(call.path, "/api/v1/commands/session.reconnect");
    assert.equal(call.headers.authorization, `Bearer ${credential.secret_token}`);
    assert.equal(call.body.payload.reconnect_nonce, credential.reconnect_nonce);
    if (++attempts === 1) return response.destroy();
    respond(response, rotated);
  });
  writePrivateJson(f.sessionFile, { ...credential, conversation_binding_digest: f.options.conversationBindingDigest });
  await assert.rejects(new CredentialHandoff(f.options).recover({ forceReconnect: true }), /retry_pending_request/);
  const recovered = await new CredentialHandoff(f.options).recover();
  assert.equal(recovered.connection_epoch, 2);
  assert.equal(f.calls[0].text, f.calls[1].text);
  assert.equal(loadSession(f.sessionFile).secret_token, rotated.secret_token);
});

test("lost rebind response cannot change its ticket proof or target Agent", async (t) => {
  let attempts = 0;
  const f = await fixture(t, (call, response) => {
    if (isAck(call)) return ack(response);
    assert.equal(call.path, "/api/v1/commands/session.rebind");
    assert.equal(call.body.payload.target_agent_id, credential.agent_id);
    if (++attempts === 1) return response.destroy();
    respond(response, { ...credential, connection_epoch: 2 });
  });
  writePrivateJson(f.sessionFile, { ...credential, conversation_binding_digest: f.options.conversationBindingDigest });
  await assert.rejects(new CredentialHandoff(f.options).recover(f.input), /retry_pending_request/);
  await assert.rejects(new CredentialHandoff(f.options).recover({ ...f.input, ticket: { ...ticket, secret: "other-proof" } }), /auth_binding_mismatch/);
  assert.equal(f.calls.length, 1);
  await new CredentialHandoff(f.options).recover(f.input);
  assert.equal(f.calls[0].text, f.calls[1].text);
});

test("a degraded session re-sends its baseline on reconnect", async (t) => {
  // The daemon only accepts a fresh report from a session that is *not* ready
  // (api/auth.py: authenticate_reconnect_refresh). Sending one when the last known
  // status is ready would let a flaky startup probe downgrade a working host, so the
  // bridge hands the report over only when the saved status says it is needed.
  const payloads = [];
  const f = await fixture(t, (call, response) => {
    if (isAck(call)) return ack(response);
    assert.equal(call.path, "/api/v1/commands/session.reconnect");
    payloads.push(call.body.payload);
    respond(response, credential);
  });
  writePrivateJson(f.sessionFile, {
    ...credential, baseline_status: "degraded",
    conversation_binding_digest: f.options.conversationBindingDigest,
  });

  // No ticket: the one-shot ticket was consumed and deleted when the session was
  // created, so a restart with a saved session is a reconnect.
  const healed = await new CredentialHandoff(f.options).recover({ baseline: f.input.baseline });

  assert.equal(healed.baseline_status, "ready");
  assert.deepEqual(payloads[0], {
    reconnect_nonce: credential.reconnect_nonce,
    expected_connection_epoch: credential.connection_epoch,
    probe_payload: f.input.baseline,
  });
});

test("a reconnect from a session that is not known to be degraded stays quiet", async (t) => {
  const payloads = [];
  const f = await fixture(t, (call, response) => {
    if (isAck(call)) return ack(response);
    payloads.push(call.body.payload);
    respond(response, credential);
  });
  // A saved handoff whose binding digest no longer matches is a new attempt (the
  // normal case: the epoch moved on and the daemon asked for a reconnect).
  writePrivateJson(f.sessionFile, {
    ...credential, conversation_binding_digest: f.options.conversationBindingDigest,
    credential_auth_binding_digest: "previous-handoff",
  });

  await new CredentialHandoff(f.options).recover({
    forceReconnect: true, baseline: { observation: "after-restart" },
  });

  assert.deepEqual(payloads[0], {
    reconnect_nonce: credential.reconnect_nonce,
    expected_connection_epoch: credential.connection_epoch,
  });
});

test("session save failure leaves pending request and never ACKs", async (t) => {
  const f = await fixture(t, (_call, response) => respond(response, credential));
  const writePrivate = (path, value) => {
    if (path === f.sessionFile) throw new Error("injected_save_failure");
    writePrivateJson(path, value);
  };
  await assert.rejects(new CredentialHandoff({ ...f.options, writePrivate }).recover(f.input), /save_failure/);
  assert.equal(f.calls.length, 1);
  assert.equal(existsSync(f.sessionFile), false);
  assert.equal(existsSync(`${f.sessionFile}.pending.json`), true);
  assert.equal(existsSync(f.ticketFile), true);
});

test("crash after private save finalizes journal without another credential command", async (t) => {
  const f = await fixture(t, (call, response) => isAck(call) ? ack(response) : respond(response, credential));
  const writePrivate = (path, value) => {
    writePrivateJson(path, value);
    if (path === f.sessionFile) throw new Error("injected_after_save_crash");
  };
  await assert.rejects(new CredentialHandoff({ ...f.options, writePrivate }).recover(f.input), /after_save_crash/);
  const recovered = await new CredentialHandoff(f.options).recover(f.input);
  assert.equal(recovered.agent_id, credential.agent_id);
  assert.equal(f.calls.filter((call) => !isAck(call)).length, 1);
  assert.equal(f.calls.filter(isAck).length, 1);
});

test("lost ACK preserves valid session and startup retries only ACK", async (t) => {
  let ackAttempts = 0;
  const f = await fixture(t, (call, response) => {
    if (!isAck(call)) return respond(response, credential);
    if (++ackAttempts === 1) return response.destroy();
    ack(response);
  });
  const first = await new CredentialHandoff(f.options).recover(f.input);
  assert.equal(first.delivery_ack_pending, true);
  assert.equal(loadSession(f.sessionFile).secret_token, credential.secret_token);
  const recovered = await new CredentialHandoff(f.options).recover();
  assert.equal(recovered.delivery_ack_pending, false);
  assert.equal(f.calls.filter((call) => !isAck(call)).length, 1);
  assert.equal(ackAttempts, 2);
});

test("late ACK cannot overwrite a newer session credential", async (t) => {
  const newer = { ...credential, secret_token: "new-epoch-token", reconnect_nonce: "new-epoch-nonce",
    connection_epoch: 2, credential_command_id: "newer-command", delivery_ack_pending: false };
  const f = await fixture(t, (call, response, { sessionFile }) => {
    if (!isAck(call)) return respond(response, credential);
    writePrivateJson(sessionFile, newer);
    ack(response);
  });
  const recovered = await new CredentialHandoff(f.options).recover(f.input);
  assert.equal(recovered.connection_epoch, 2);
  assert.equal(loadSession(f.sessionFile).secret_token, newer.secret_token);
});

test("consumed, expired and invalid receipts never replace the session", async (t) => {
  for (const delivery_status of ["consumed", "expired", "revoked"]) {
    assert.throws(() => parseCredential({ ...credential, secret_token: undefined, delivery_status, recovery_action: "reconnect_required" }), /reconnect_required/);
  }
  assert.throws(() => parseCredential({ ...credential, reconnect_nonce: undefined }), /response_invalid/);
  const f = await fixture(t, (_call, response) => respond(response, {
    session_id: credential.session_id, delivery_status: "expired", recovery_action: "reconnect_required",
  }));
  writePrivateJson(f.sessionFile, credential);
  const original = readFileSync(f.sessionFile, "utf8");
  await assert.rejects(new CredentialHandoff(f.options).recover({ forceReconnect: true }), /reconnect_required/);
  assert.equal(readFileSync(f.sessionFile, "utf8"), original);
  assert.equal(f.calls.length, 1);
});

test("pending journal cannot be adopted by another conversation", async (t) => {
  const f = await fixture(t, (_call, response) => response.destroy());
  await assert.rejects(new CredentialHandoff(f.options).recover(f.input), /retry_pending_request/);
  await assert.rejects(new CredentialHandoff({ ...f.options, conversationBindingDigest: "different-conversation" }).recover(f.input), /binding_mismatch/);
  assert.equal(f.calls.length, 1);
});

test("cleanup preserves a newly issued ticket instead of deleting it", async (t) => {
  const replacement = { ...ticket, secret: "fresh-ticket-must-survive" };
  const f = await fixture(t, (call, response, { ticketFile }) => {
    if (isAck(call)) return ack(response);
    writePrivateJson(ticketFile, replacement);
    respond(response, credential);
  });
  await new CredentialHandoff(f.options).recover(f.input);
  assert.equal(JSON.parse(readFileSync(f.ticketFile, "utf8")).secret, replacement.secret);
});

test("private files have owner-only ACL/mode and corrupt journals cannot enroll again", async (t) => {
  const f = await fixture(t, (_call, response) => response.destroy());
  await assert.rejects(new CredentialHandoff(f.options).recover(f.input), /retry_pending_request/);
  const path = `${f.sessionFile}.pending.json`;
  if (process.platform === "win32") {
    const aclFile = join(f.root, "permissions.txt");
    execFileSync("icacls.exe", [path, "/save", aclFile], { windowsHide: true, stdio: "pipe" });
    const acl = readFileSync(aclFile, "utf16le");
    const currentSid = execFileSync("whoami.exe", ["/user", "/fo", "csv", "/nh"], { encoding: "utf8", windowsHide: true }).match(/S-1-\d+(?:-\d+)+/)[0];
    assert.deepEqual(acl.match(/\(A;[^)]*\)/g), [`(A;;FA;;;${currentSid})`]);
  } else {
    assert.equal(statSync(path).mode & 0o777, 0o600);
  }
  writeFileSync(path, "incomplete");
  await assert.rejects(new CredentialHandoff(f.options).recover(f.input), /private_file_invalid/);
  assert.equal(f.calls.length, 1);
});

test("Windows ACL failure leaves the old session intact and no secret temporary file", { skip: process.platform !== "win32" }, (t) => {
  const root = mkdtempSync(join(tmpdir(), "tsunagou-acl-failure-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, "session.json");
  writePrivateJson(path, { previous: "safe" });
  const originalPath = process.env.PATH;
  try {
    process.env.PATH = root; // Force ACL command failure before bytes are written.
    assert.throws(() => writePrivateJson(path, { secret_token: "must-never-be-written" }), /private_save_failed/);
  } finally {
    process.env.PATH = originalPath;
  }
  assert.deepEqual(JSON.parse(readFileSync(path, "utf8")), { previous: "safe" });
  assert.deepEqual(readdirSync(root), ["session.json"]);
});

test("two bridge processes sharing one handoff use one command ID even after ACK", { timeout: 20000 }, async (t) => {
  const waiting = [];
  const f = await fixture(t, (call, response) => {
    if (isAck(call)) return ack(response);
    waiting.push(response);
    if (waiting.length === 2) {
      respond(waiting[0], credential);
      // By this response the other process has saved and consumed delivery.
      setTimeout(() => respond(waiting[1], {
        agent_id: credential.agent_id, session_id: credential.session_id,
        delivery_status: "consumed", recovery_action: "reconnect_required",
      }), 250);
    }
  });
  const moduleUrl = pathToFileURL(join(import.meta.dirname, "../dist/credential-handoff.js")).href;
  const source = `
    import { readFileSync } from 'node:fs';
    import { CredentialHandoff } from ${JSON.stringify(moduleUrl)};
    const options = JSON.parse(process.env.TSUNAGOU_HANDOFF_TEST_OPTIONS);
    const ticketFile = process.env.TSUNAGOU_HANDOFF_TEST_TICKET;
    const ticket = JSON.parse(readFileSync(ticketFile, 'utf8'));
    process.send('ready');
    process.once('message', async () => {
      try {
        const session = await new CredentialHandoff(options).recover({ ticket, ticketFile, baseline: { probe: process.pid } });
        process.stdout.write(JSON.stringify({ agent_id: session.agent_id, connection_epoch: session.connection_epoch }));
        process.disconnect();
      } catch (error) {
        process.stderr.write(error.message); process.exitCode = 1; process.disconnect();
      }
    });
  `;
  const children = [0, 1].map(() => {
    const processHandle = spawn(process.execPath, ["--input-type=module", "-e", source], {
      windowsHide: true, stdio: ["ignore", "pipe", "pipe", "ipc"],
      env: { ...process.env, TSUNAGOU_HANDOFF_TEST_OPTIONS: JSON.stringify(f.options), TSUNAGOU_HANDOFF_TEST_TICKET: f.ticketFile },
    });
    let stdout = ""; let stderr = "";
    processHandle.stdout.on("data", (data) => { stdout += data; });
    processHandle.stderr.on("data", (data) => { stderr += data; });
    const ready = new Promise((resolve) => processHandle.once("message", resolve));
    const done = new Promise((resolve) => processHandle.once("exit", (code) => resolve({ code, stdout, stderr })));
    t.after(() => { if (processHandle.exitCode === null) processHandle.kill(); });
    return { processHandle, ready, done };
  });
  await Promise.all(children.map((child) => child.ready));
  for (const child of children) child.processHandle.send("go");
  const outcomes = await Promise.all(children.map((child) => child.done));
  for (const outcome of outcomes) {
    assert.equal(outcome.code, 0, outcome.stderr);
    assert.equal(JSON.parse(outcome.stdout).agent_id, credential.agent_id);
    assert.ok(!outcome.stdout.includes(credential.secret_token));
  }
  const requests = f.calls.filter((call) => !isAck(call));
  assert.equal(requests.length, 2);
  assert.equal(requests[0].text, requests[1].text);
  assert.equal(loadSession(f.sessionFile).agent_id, credential.agent_id);
});

test("Node-owned private lock excludes Python and Node and is released when its owner dies", { timeout: 20000 }, async (t) => {
  const root = mkdtempSync(join(tmpdir(), "tsunagou-private-lock-"));
  const path = join(root, "session.json");
  const moduleUrl = pathToFileURL(join(import.meta.dirname, "../dist/private-file-lock.js")).href;
  const source = `
    import { withPrivateFileLock } from ${JSON.stringify(moduleUrl)};
    await withPrivateFileLock(process.env.TSUNAGOU_TEST_SESSION, () => {
      process.send('held');
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 30000);
    });
  `;
  const child = spawn(process.execPath, ["--input-type=module", "-e", source], {
    windowsHide: true, stdio: ["ignore", "ignore", "pipe", "ipc"],
    env: { ...process.env, TSUNAGOU_TEST_SESSION: path },
  });
  t.after(() => { child.kill(); rmSync(root, { recursive: true, force: true }); });
  await new Promise((resolve) => child.once("message", resolve));
  let entered = false;
  await assert.rejects(withPrivateFileLock(path, () => { entered = true; }), /private_lock_busy/);
  assert.equal(entered, false);
  const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
  const python = `
import sys
from pathlib import Path
from tsunagou.platform.private_file_lock import private_file_lock
try:
    with private_file_lock(Path(sys.argv[1]), timeout=0):
        result = 'acquired'
except RuntimeError as error:
    if str(error) != 'credential_private_lock_busy:retry_pending_request':
        raise
    result = 'busy'
print(result)
`;
  const probePython = () => execFileSync("uv", ["run", "--no-sync", "--project", repoRoot, "python", "-c", python, path], {
    cwd: repoRoot, windowsHide: true, encoding: "utf8", timeout: 5000,
  }).trim();
  assert.equal(probePython(), "busy");
  const exited = new Promise((resolve) => child.once("exit", resolve));
  child.kill();
  await exited;
  assert.equal(probePython(), "acquired");
  await withPrivateFileLock(path, () => { entered = true; });
  assert.equal(entered, true);
});

test("Python-owned private lock excludes Node and is released when its owner dies", { timeout: 20000 }, async (t) => {
  const root = mkdtempSync(join(tmpdir(), "tsunagou-private-lock-"));
  const path = join(root, "session.json");
  const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
  // Spawn the interpreter itself so kill targets the process holding the lock,
  // not an intermediary uv process that could leave its child alive.
  const interpreter = execFileSync("uv", ["run", "--no-sync", "--project", repoRoot, "python", "-c", "import sys; print(sys.executable)"], {
    cwd: repoRoot, windowsHide: true, encoding: "utf8", timeout: 5000,
  }).trim();
  const python = `
import sys, time
from pathlib import Path
from tsunagou.platform.private_file_lock import private_file_lock
with private_file_lock(Path(sys.argv[1])):
    print('held', flush=True)
    time.sleep(30)
`;
  const child = spawn(interpreter, ["-u", "-c", python, path], {
    cwd: repoRoot, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  let stderr = "";
  child.stderr.on("data", (data) => { stderr += data; });
  const exited = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", resolve);
  });
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) child.kill();
    await exited;
    rmSync(root, { recursive: true, force: true });
  });
  await Promise.race([
    new Promise((resolve) => child.stdout.on("data", (data) => { if (data.toString().includes("held")) resolve(); })),
    exited.then(() => { throw new Error(`Python lock owner exited before readiness: ${stderr}`); }),
  ]);
  let entered = false;
  await assert.rejects(withPrivateFileLock(path, () => { entered = true; }), /private_lock_busy/);
  assert.equal(entered, false);
  child.kill();
  await exited;
  await withPrivateFileLock(path, () => { entered = true; });
  assert.equal(entered, true);
  assert.equal(existsSync(path), false);
});

test("paused old session writer cannot overwrite the next epoch from another process", { timeout: 20000 }, async (t) => {
  const enrollmentResponses = [];
  let releaseReplay;
  const replayReady = new Promise((resolve) => { releaseReplay = resolve; });
  const f = await fixture(t, (call, response) => {
    if (isAck(call)) return ack(response);
    if (call.path.endsWith("session.reconnect")) return respond(response, {
      ...credential, connection_epoch: 2, secret_token: "epoch-two-token", reconnect_nonce: "epoch-two-nonce",
    });
    enrollmentResponses.push(response);
    if (enrollmentResponses.length === 2) releaseReplay();
  });
  const gate = join(f.root, "release-writer");
  const handoffUrl = pathToFileURL(join(import.meta.dirname, "../dist/credential-handoff.js")).href;
  const privateUrl = pathToFileURL(join(import.meta.dirname, "../dist/private-file.js")).href;
  const source = `
    import { readFileSync, existsSync } from 'node:fs';
    import { CredentialHandoff } from ${JSON.stringify(handoffUrl)};
    import { writePrivateJson } from ${JSON.stringify(privateUrl)};
    const options = JSON.parse(process.env.TSUNAGOU_HANDOFF_TEST_OPTIONS);
    const ticketFile = process.env.TSUNAGOU_HANDOFF_TEST_TICKET;
    const ticket = JSON.parse(readFileSync(ticketFile, 'utf8'));
    const slow = process.env.TSUNAGOU_HANDOFF_TEST_SLOW === 'true';
    let firstWrite = true;
    const writePrivate = (path, value) => {
      if (slow && firstWrite && path === options.sessionFile) {
        firstWrite = false;
        process.send('before-save');
        const deadline = Date.now() + 10000;
        while (!existsSync(process.env.TSUNAGOU_HANDOFF_TEST_GATE)) {
          if (Date.now() > deadline) throw new Error('test_gate_timeout');
          Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
        }
      }
      writePrivateJson(path, value);
    };
    process.send('ready');
    process.once('message', async () => {
      try {
        const handoff = new CredentialHandoff({ ...options, writePrivate });
        await handoff.recover({ ticket, ticketFile });
        if (!slow) await handoff.recover({ forceReconnect: true });
        process.disconnect();
      } catch (error) {
        process.stderr.write(error.message); process.exitCode = 1; process.disconnect();
      }
    });
  `;
  const children = [true, false].map((slow) => {
    const handle = spawn(process.execPath, ["--input-type=module", "-e", source], {
      windowsHide: true, stdio: ["ignore", "ignore", "pipe", "ipc"],
      env: { ...process.env, TSUNAGOU_HANDOFF_TEST_OPTIONS: JSON.stringify(f.options),
        TSUNAGOU_HANDOFF_TEST_TICKET: f.ticketFile, TSUNAGOU_HANDOFF_TEST_GATE: gate,
        TSUNAGOU_HANDOFF_TEST_SLOW: String(slow) },
    });
    let stderr = "";
    handle.stderr.on("data", (data) => { stderr += data; });
    const ready = new Promise((resolve) => handle.once("message", resolve));
    const beforeSave = new Promise((resolve) => handle.on("message", (value) => { if (value === "before-save") resolve(); }));
    const done = new Promise((resolve) => handle.once("exit", (code) => resolve({ code, stderr })));
    t.after(() => { if (handle.exitCode === null) handle.kill(); });
    return { handle, ready, beforeSave, done };
  });
  await Promise.all(children.map((child) => child.ready));
  // Send the slow process first and wait for its HTTP request before starting
  // its peer, so the first saved-response barrier belongs to the slow writer.
  children[0].handle.send("go");
  while (enrollmentResponses.length < 1) await new Promise((resolve) => setTimeout(resolve, 10));
  children[1].handle.send("go");
  await replayReady;
  respond(enrollmentResponses[0], credential);
  await children[0].beforeSave;
  respond(enrollmentResponses[1], credential);
  // Without the mutex the peer saves N and N+1 while the old writer is paused.
  // With it the peer cannot pass the final compare/save until release.
  await Promise.race([children[1].done, new Promise((resolve) => setTimeout(resolve, 1000))]);
  writeFileSync(gate, "release");
  for (const result of await Promise.all(children.map((child) => child.done))) assert.equal(result.code, 0, result.stderr);
  assert.equal(loadSession(f.sessionFile).connection_epoch, 2);
  assert.equal(loadSession(f.sessionFile).secret_token, "epoch-two-token");
});

test("Python CLI ticket replacement and Node cleanup share one process-owned lock", { timeout: 20000 }, async (t) => {
  const f = await fixture(t, (call, response) => isAck(call) ? ack(response) : respond(response, credential));
  const gate = join(f.root, "release-python-ticket-writer");
  const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
  const python = `
import sys, time
from pathlib import Path
from tsunagou.cli.app import _write_ticket_private
from tsunagou.platform import bridge_files
target, gate = Path(sys.argv[1]), Path(sys.argv[2])
# The ticket writer lives in platform/bridge_files.py and binds write_private_bytes
# at import time, so the pause has to be installed on that module (patching
# private_files itself would be a no-op and this test would wait for a gate
# that can never open).
original = bridge_files.write_private_bytes
def paused(path, data):
    print('writer-held', flush=True)
    deadline = time.monotonic() + 15
    while not gate.exists():
        if time.monotonic() > deadline:
            raise RuntimeError('test_gate_timeout')
        time.sleep(0.01)
    original(path, data)
bridge_files.write_private_bytes = paused
_write_ticket_private('codex:one', 'conversation-one', 'new-python-ticket-sentinel', target)
`;
  const child = spawn("uv", ["run", "--no-sync", "--project", repoRoot, "python", "-u", "-c", python, f.ticketFile, gate], {
    cwd: repoRoot, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  let stderr = "";
  child.stderr.on("data", (data) => { stderr += data; });
  const done = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve({ code, stderr }));
  });
  t.after(() => { if (child.exitCode === null) child.kill(); });
  await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.stdout.on("data", (data) => { if (data.toString().includes("writer-held")) resolve(); });
  });
  // The CLI has already entered _write_ticket_private's lock and is paused
  // before replacing bytes. A real bridge saves its session, then must fail
  // busy instead of deleting this file while the producer owns it.
  await assert.rejects(new CredentialHandoff(f.options).recover(f.input), /private_lock_busy/);
  assert.equal(loadSession(f.sessionFile).agent_id, credential.agent_id);
  assert.equal(JSON.parse(readFileSync(f.ticketFile, "utf8")).secret, ticket.secret);
  writeFileSync(gate, "release");
  const result = await done;
  assert.equal(result.code, 0, result.stderr);
  await new CredentialHandoff(f.options).recover(f.input);
  assert.equal(JSON.parse(readFileSync(f.ticketFile, "utf8")).secret, "new-python-ticket-sentinel");
});

async function metadataBridgeFixture(t) {
  const secondTicket = { ...ticket, conversation_id: "conversation-two", secret: "second-ticket-sentinel" };
  const secondCredential = {
    ...credential, agent_id: "agent-two", session_id: "session-two", secret_token: "second-credential-sentinel",
    reconnect_nonce: "second-nonce-sentinel", receipt_id: "receipt-two", delivery_ref: "delivery:two",
  };
  const tickets = new Map([ticket, secondTicket].map((item) => [item.conversation_id, item]));
  const sessions = new Map([credential, secondCredential].map((item) => [item.session_id, item]));
  const rejectContextOnce = new Set();
  const hooks = {};
  const f = await fixture(t, async (call, response) => {
    if (call.path.endsWith("agent.enroll")) {
      const conversation = call.body.payload.conversation_evidence.conversation_id;
      assert.equal(call.headers.authorization, `Bearer ${tickets.get(conversation)?.secret}`);
      if (await hooks.beforeEnroll?.(conversation, response)) return;
      return respond(response, conversation === ticket.conversation_id ? credential : secondCredential);
    }
    const current = sessions.get(call.headers["tsunagou-session-id"]);
    if (!current || call.headers.authorization !== `Bearer ${current.secret_token}`
        || call.headers["tsunagou-connection-epoch"] !== String(current.connection_epoch)) {
      response.statusCode = 401;
      response.end(JSON.stringify({ detail: { code: "authentication_failed" } }));
      return;
    }
    if (isAck(call)) return ack(response);
    if (call.path.endsWith("session.reconnect")) {
      await hooks.beforeReconnect?.(current);
      const rotated = {
        ...current, connection_epoch: current.connection_epoch + 1,
        secret_token: `${current.secret_token}-rotated`, reconnect_nonce: `${current.reconnect_nonce}-rotated`,
      };
      sessions.set(rotated.session_id, rotated);
      return respond(response, rotated);
    }
    assert.ok(call.path.endsWith("context.project_read"));
    if (rejectContextOnce.delete(current.agent_id)) {
      response.statusCode = 401;
      response.end(JSON.stringify({ detail: { code: "authentication_failed" } }));
      return;
    }
    respond(response, { agent_id: current.agent_id, session_id: current.session_id, connection_epoch: current.connection_epoch });
  });
  const stateDir = join(f.root, "state");
  const digest = (conversation) => createHash("sha256").update(`conversation_id:${conversation}`).digest("hex");
  const sessionPath = (conversation) => join(stateDir, "sessions", `bridge-session-${digest(conversation).slice(0, 32)}.json`);
  const clients = [];
  let diagnostics = "";
  async function connect(extraEnv = {}) {
    const transport = new StdioClientTransport({
      command: process.execPath,
      args: [fileURLToPath(new URL("../dist/server.js", import.meta.url))],
      env: {
        ...process.env,
        TSUNAGOU_HTTP_URL: f.options.baseUrl,
        TSUNAGOU_DAEMON_STATE_DIR: join(f.root, "missing-daemon-state"),
        TSUNAGOU_TICKET_FILE: f.ticketFile,
        TSUNAGOU_SESSION_FILE: f.sessionFile,
        TSUNAGOU_PROJECT_ROOT: f.root,
        TSUNAGOU_STATE_DIR: stateDir,
        TSUNAGOU_HOST_ID_ENV: "TSUNAGOU_METADATA_TEST_HOST_ID",
        TSUNAGOU_METADATA_TEST_HOST_ID: "",
        TSUNAGOU_HOST_META_KEY: "",
        TSUNAGOU_ROUTING_DIR: "",
        TSUNAGOU_DESKTOP_WAKE: "",
        ...extraEnv,
      },
      stderr: "pipe",
    });
    transport.stderr?.on("data", (data) => { diagnostics += data; });
    const client = new Client({ name: "metadata-handoff-test", version: "0.1.0" }, { capabilities: {} });
    clients.push(client);
    await client.connect(transport);
    return client;
  }
  t.after(async () => {
    await Promise.all(clients.map((client) => client.close().catch(() => {})));
    assert.ok(!diagnostics.includes(ticket.secret));
    assert.ok(!diagnostics.includes(credential.secret_token));
    assert.ok(!diagnostics.includes(secondCredential.secret_token));
  });
  const call = (client, conversation) => client.callTool({
    name: "context__project_read", arguments: {},
    ...(conversation ? { _meta: { "ai.opencode/sessionID": conversation } } : {}),
  });
  const result = (response) => {
    assert.ok(!response.isError, response.content?.[0]?.text);
    const text = response.content.find((item) => item.type === "text").text;
    assert.ok(!text.includes("sentinel"));
    return JSON.parse(text);
  };
  return { ...f, connect, call, result, sessionPath, digest, secondTicket, secondCredential, rejectContextOnce, hooks };
}

test("MCP metadata preserves explicit bootstrap credentials across A/B/A and restart", { timeout: 30000 }, async (t) => {
  const f = await metadataBridgeFixture(t);
  let client = await f.connect({ TSUNAGOU_HOST_META_KEY: "ai.opencode/sessionID" });
  assert.equal(f.result(await f.call(client, ticket.conversation_id)).agent_id, credential.agent_id);
  assert.equal(loadSession(f.sessionFile).agent_id, credential.agent_id);

  // An unenrolled conversation must neither borrow the startup credential nor
  // consume a currently shared ticket that belongs to another conversation.
  const foreignTicket = { ...ticket, conversation_id: "foreign-conversation" };
  writePrivateJson(f.ticketFile, foreignTicket);
  assert.equal((await f.call(client, f.secondTicket.conversation_id)).isError, true);
  assert.deepEqual(JSON.parse(readFileSync(f.ticketFile, "utf8")), foreignTicket);
  assert.equal(f.calls.filter((call) => call.path.endsWith("agent.enroll")).length, 1);

  writePrivateJson(f.ticketFile, f.secondTicket);
  assert.equal(f.result(await f.call(client, f.secondTicket.conversation_id)).agent_id, f.secondCredential.agent_id);
  assert.equal(f.result(await f.call(client, ticket.conversation_id)).agent_id, credential.agent_id);
  assert.equal(loadSession(f.sessionPath(f.secondTicket.conversation_id)).agent_id, f.secondCredential.agent_id);
  assert.equal(loadSession(f.sessionFile).agent_id, credential.agent_id);
  assert.equal((await f.call(client, "unknown-conversation")).isError, true);
  assert.equal((await f.call(client)).isError, true);
  assert.equal(f.calls.filter((call) => call.path.endsWith("agent.enroll")).length, 2);

  await client.close();
  client = await f.connect({ TSUNAGOU_HOST_META_KEY: "ai.opencode/sessionID" });
  for (const [conversation, expected] of [[f.secondTicket.conversation_id, f.secondCredential], [ticket.conversation_id, credential]]) {
    const recovered = f.result(await f.call(client, conversation));
    assert.equal(recovered.agent_id, expected.agent_id);
    assert.equal(recovered.connection_epoch, 1);
  }
  assert.equal(f.calls.filter((call) => call.path.endsWith("agent.enroll")).length, 2);
  assert.equal(f.calls.filter((call) => call.path.endsWith("session.reconnect")).length, 0);
});

test("concurrent MCP conversations retain their identity through recovery and auth retry", { timeout: 30000 }, async (t) => {
  const f = await metadataBridgeFixture(t);
  const client = await f.connect({ TSUNAGOU_HOST_META_KEY: "ai.opencode/sessionID" });
  assert.equal(f.result(await f.call(client, ticket.conversation_id)).agent_id, credential.agent_id);
  writePrivateJson(f.ticketFile, f.secondTicket);
  for (const [delayedConversation, delayedAgent, otherConversation, otherAgent, authRetry] of [
    [f.secondTicket.conversation_id, f.secondCredential.agent_id, ticket.conversation_id, credential.agent_id, false],
    [ticket.conversation_id, credential.agent_id, f.secondTicket.conversation_id, f.secondCredential.agent_id, true],
  ]) {
    let entered;
    let release;
    const reconnectEntered = new Promise((resolve) => { entered = resolve; });
    const reconnectReleased = new Promise((resolve) => { release = resolve; });
    f.hooks.beforeEnroll = async (conversation) => {
      if (conversation === delayedConversation) { entered(); await reconnectReleased; }
    };
    f.hooks.beforeReconnect = async (session) => {
      if (session.agent_id === delayedAgent) { entered(); await reconnectReleased; }
    };
    if (authRetry) f.rejectContextOnce.add(delayedAgent);
    const delayed = f.call(client, delayedConversation);
    try {
      await reconnectEntered;
      // The other conversation must complete while this one's handoff waits.
      assert.equal(f.result(await f.call(client, otherConversation)).agent_id, otherAgent);
    } finally {
      release();
    }
    const recovered = f.result(await delayed);
    assert.equal(recovered.agent_id, delayedAgent);
    assert.equal(recovered.connection_epoch, authRetry ? 2 : 1);
  }
  assert.equal(f.result(await f.call(client, ticket.conversation_id)).agent_id, credential.agent_id);
  assert.equal(f.result(await f.call(client, f.secondTicket.conversation_id)).agent_id, f.secondCredential.agent_id);
});

test("host-metadata bridge rejects a first call without valid metadata", { timeout: 30000 }, async (t) => {
  const f = await metadataBridgeFixture(t);
  const client = await f.connect({ TSUNAGOU_HOST_META_KEY: "ai.opencode/sessionID" });
  const callRaw = (meta) => client.callTool({
    name: "context__project_read", arguments: {},
    ...(meta !== undefined ? { _meta: meta } : {}),
  });
  const errorOf = (response) => {
    assert.equal(response.isError, true, JSON.stringify(response.content));
    const text = response.content.find((item) => item.type === "text").text;
    assert.ok(!text.includes("agent-one") && !text.includes("sentinel"));
    return text;
  };

  // A first call that cannot prove its conversation must not redeem the
  // configured ticket or fall back to the explicit default session file.
  assert.match(errorOf(await callRaw(undefined)), /conversation_metadata_required/);
  assert.match(errorOf(await callRaw({})), /conversation_metadata_required/);
  assert.match(errorOf(await callRaw({ "ai.opencode/sessionID": "" })), /conversation_metadata_required/);
  assert.match(errorOf(await callRaw({ "ai.opencode/sessionID": 42 })), /conversation_metadata_required/);
  assert.match(errorOf(await callRaw({ "ai.opencode/sessionID": { id: "conversation-one" } })), /conversation_metadata_required/);

  // Credential selection now happens per request, so invalid metadata causes
  // no startup enrollment or other authentication request at all.
  assert.equal(f.calls.length, 0);
  assert.equal(loadSession(f.sessionFile), undefined);
  assert.equal(existsSync(f.ticketFile), true);

  // A valid metadata call still resolves the exact conversation credential.
  assert.equal(f.result(await f.call(client, ticket.conversation_id)).agent_id, credential.agent_id);
});

test("metadata bootstrap resumes its explicit pending journal after a lost response", { timeout: 30000 }, async (t) => {
  const f = await metadataBridgeFixture(t);
  let loseResponse = true;
  f.hooks.beforeEnroll = (_conversation, response) => {
    if (loseResponse) { loseResponse = false; response.destroy(); return true; }
  };
  let client = await f.connect({ TSUNAGOU_HOST_META_KEY: "ai.opencode/sessionID" });
  assert.equal((await f.call(client, ticket.conversation_id)).isError, true);
  assert.equal(loadSession(f.sessionFile), undefined);
  const pending = JSON.parse(readFileSync(`${f.sessionFile}.pending.json`, "utf8"));
  await client.close();
  client = await f.connect({ TSUNAGOU_HOST_META_KEY: "ai.opencode/sessionID" });
  assert.equal((await f.call(client, f.secondTicket.conversation_id)).isError, true);
  assert.equal(f.result(await f.call(client, ticket.conversation_id)).agent_id, credential.agent_id);
  const enrollments = f.calls.filter((call) => call.path.endsWith("agent.enroll"));
  assert.equal(enrollments.length, 2);
  assert.equal(enrollments[0].body.command_id, pending.envelope.command_id);
  assert.equal(enrollments[1].text, enrollments[0].text);
  assert.equal(existsSync(`${f.sessionFile}.pending.json`), false);
});

test("unconfigured metadata bridge never falls back to its bootstrap credential after observing metadata", { timeout: 30000 }, async (t) => {
  const f = await metadataBridgeFixture(t);
  const client = await f.connect();
  assert.equal(f.result(await f.call(client, ticket.conversation_id)).agent_id, credential.agent_id);
  const callsBefore = f.calls.length;
  for (const meta of [undefined, {}, { "ai.opencode/sessionID": "" }, { "ai.opencode/sessionID": 42 }, { threadId: ticket.conversation_id }]) {
    const response = await client.callTool({ name: "context__project_read", arguments: {}, ...(meta ? { _meta: meta } : {}) });
    assert.equal(response.isError, true);
    assert.match(response.content.find((item) => item.type === "text").text, /conversation_metadata_required/);
  }
  assert.equal(f.calls.length, callsBefore);
  assert.equal(f.result(await f.call(client, ticket.conversation_id)).agent_id, credential.agent_id);
});
