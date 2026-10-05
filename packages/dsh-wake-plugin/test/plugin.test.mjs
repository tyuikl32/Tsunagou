/**
 * Simulated checks for the Tsunagou wake plugin.
 *
 * These are host doubles: no DSH process, no Desktop, no network. They prove the
 * plugin's own contract — authentication, binding, request-id derivation, and
 * which host calls it makes — and nothing about the real host's behaviour.
 *
 * Run: node --test test/
 */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  apply,
  createStatusHandler,
  createWakeHandler,
  internals,
  isLoopback,
  readConfig,
  reminderText,
  requestIdFor,
  secretMatches,
  testing,
} from "../index.js";

const KEY = "test-key-not-a-real-secret";
const KEY_ENV = "TSUNAGOU_WAKE_KEY";

const BINDING = Object.freeze({
  project_id: "proj-1",
  agent_id: "agent-1",
  session_id: "session-aaaaaaaa-1111-2222-3333-444444444444",
});
const MESSAGE_ID = "msg-0001";

/* ------------------------------------------------------------------ *
 * harness doubles
 * ------------------------------------------------------------------ */

/**
 * Build a host double.
 *
 * @param options - `{ promptError, secret, inspectMissing }` overrides.
 * @returns `{ deps, calls, routes }`.
 */
function host(options = {}) {
  const calls = { prompt: [], inspect: [], resolve: 0, registered: [] };
  const deps = {
    sessionController: {
      async inspect(sessionId) {
        calls.inspect.push(sessionId);
        if (options.inspectMissing === true) {
          const error = new Error("session not found");
          error.code = "session/not-found";
          throw error;
        }
        return { meta: { id: sessionId } };
      },
      async prompt(request, signal) {
        calls.prompt.push({ request, signal });
        if (options.promptError !== undefined) throw options.promptError;
        return { accepted: true };
      },
    },
    credentials: {
      async resolve(ref) {
        calls.resolve += 1;
        assert.equal(ref, KEY_ENV);
        const value = options.secret === undefined ? KEY : options.secret;
        return value === null ? undefined : { value, source: "test" };
      },
    },
    agents: {
      get: (id) => (options.live === undefined ? undefined : options.live(id)),
    },
    logger: { info() {}, warn() {} },
    keyEnv: KEY_ENV,
    bindings: [BINDING],
  };
  return { deps, calls };
}

/**
 * Request doubles created by the current test. Their delivery loop must be
 * stopped before the test ends, or it would keep the event loop alive.
 */
const pending = [];

afterEach(() => {
  for (const request of pending.splice(0)) request.settled = true;
});

/**
 * A minimal node request double.
 *
 * Emits the body the way node:http does, because the plugin reads it with
 * `on('data')`/`on('end')` rather than by async iteration.
 */
function req({ body, token = KEY, address = "127.0.0.1", method = "POST", contentType = "application/json" } = {}) {
  const payload = Buffer.from(typeof body === "string" ? body : JSON.stringify(body ?? {}), "utf8");
  const listeners = new Map();
  const fake = {
    settled: false,
    method,
    headers: {
      ...(contentType === null ? {} : { "content-type": contentType }),
      ...(token === null ? {} : { authorization: `Bearer ${token}` }),
    },
    socket: { remoteAddress: address },
    on(event, listener) {
      const list = listeners.get(event) ?? [];
      list.push(listener);
      listeners.set(event, list);
      return fake;
    },
  };
  const emit = (event, argument) => {
    for (const listener of listeners.get(event) ?? []) listener(argument);
  };
  // Deliver once the handler has actually subscribed: it resolves the bearer
  // secret before it reads the body, so a fixed tick is not reliable.
  const deliver = () => {
    if (fake.settled) return;
    if ((listeners.get("end") ?? []).length > 0) {
      emit("data", payload);
      emit("end");
      return;
    }
    setTimeout(deliver, 1);
  };
  setTimeout(deliver, 0);
  pending.push(fake);
  return fake;
}

/** A minimal node response double. */
function res() {
  const state = { status: undefined, headers: undefined, body: undefined, ended: false };
  return {
    state,
    writeHead(status, headers) {
      state.status = status;
      state.headers = headers;
    },
    end(body) {
      state.ended = true;
      state.body = body;
    },
    get json() {
      return state.body === undefined ? undefined : JSON.parse(state.body);
    },
  };
}

const body = { ...BINDING };
const wakeBody = { ...BINDING, message_id: MESSAGE_ID };

/* ------------------------------------------------------------------ *
 * pure helpers
 * ------------------------------------------------------------------ */

test("request id is stable for one identity tuple and namespaced", () => {
  const first = requestIdFor(wakeBody);
  const second = requestIdFor({ ...wakeBody });
  assert.equal(first, second);
  assert.equal(first, "tsunagou-wake-v1:" + first.slice("tsunagou-wake-v1:".length));
  assert.match(first, /^tsunagou-wake-v1:[0-9a-f]{64}$/u);
});

test("request id covers every identity field, including agent and session", () => {
  const base = requestIdFor(wakeBody);
  for (const field of ["project_id", "agent_id", "session_id", "message_id"]) {
    const changed = requestIdFor({ ...wakeBody, [field]: "different" });
    assert.notEqual(changed, base, `${field} must affect the request id`);
  }
});

test("reminder carries only the fixed text plus project and message identity", () => {
  const text = reminderText(wakeBody);
  assert.ok(text.startsWith(internals.REMINDER), "fixed text comes first and is unmodified");
  assert.ok(text.includes(`project_id: ${BINDING.project_id}`));
  assert.ok(text.includes(`message_id: ${MESSAGE_ID}`));
  // No business payload, no caller-controlled content, no agent/session echo.
  assert.ok(!text.includes(BINDING.session_id));
  assert.ok(!text.includes(BINDING.agent_id));
});

test("loopback detection accepts only loopback peers", () => {
  for (const address of ["127.0.0.1", "::1", "::ffff:127.0.0.1", "::127.0.0.1"]) {
    assert.equal(isLoopback(address), true, address);
  }
  for (const address of ["192.168.1.5", "10.0.0.1", "0.0.0.0", "::ffff:192.168.1.5", "example.com", undefined, "", "127.0.0.2"]) {
    assert.equal(isLoopback(address), false, String(address));
  }
});

test("secret comparison accepts an exact match only", () => {
  assert.equal(secretMatches("abc", "abc"), true);
  assert.equal(secretMatches("abc", "abd"), false);
  assert.equal(secretMatches("abc", "abcd"), false);
  assert.equal(secretMatches("", ""), false, "empty never authenticates");
  assert.equal(secretMatches(undefined, "abc"), false);
  assert.equal(secretMatches("abc", undefined), false);
});

test("config validation rejects an unusable key source or binding list", () => {
  assert.throws(() => readConfig(null), /config object is required/u);
  assert.throws(() => readConfig({}), /bindings/u);
  assert.throws(() => readConfig({ bindings: "none" }), /bindings/u);
  assert.throws(() => readConfig({ keyEnv: "not a name", bindings: [BINDING] }), /keyEnv/u);
  assert.throws(() => readConfig({ bindings: [] }), /non-empty/u);
  assert.throws(() => readConfig({ bindings: [{ project_id: "p", agent_id: "a" }] }), /session_id/u);
  assert.throws(() => readConfig({ bindings: [{ project_id: "p", agent_id: "a", session_id: "" }] }), /session_id/u);
  // A binding list alone is valid: the key source has a documented default.
  const ok = readConfig({ bindings: [BINDING] });
  assert.equal(ok.keyEnv, KEY_ENV, "default key source is the documented env name");
  assert.deepEqual(ok.bindings, [BINDING]);
});

/* ------------------------------------------------------------------ *
 * status endpoint
 * ------------------------------------------------------------------ */

test("status reports an unloaded but persisted session without activating it", async () => {
  const { deps, calls } = host();
  const r = res();
  await createStatusHandler(deps)(req({ body }), r);
  assert.equal(r.state.status, 200);
  assert.deepEqual(r.json, {
    ok: true,
    project_id: BINDING.project_id,
    agent_id: BINDING.agent_id,
    session_id: BINDING.session_id,
    exists: true,
    loaded: false,
    state: "unloaded",
    queueable: true,
  });
  assert.deepEqual(calls.prompt, [], "status must never submit");
  assert.deepEqual(calls.inspect, [BINDING.session_id]);
});

test("status distinguishes idle from running for a loaded session", async () => {
  for (const [status, expected] of [["idle", "idle"], ["running", "running"]]) {
    const { deps } = host({ live: (id) => (id === BINDING.session_id ? { id, status } : undefined) });
    const r = res();
    await createStatusHandler(deps)(req({ body }), r);
    assert.equal(r.json.loaded, true);
    assert.equal(r.json.state, expected);
  }
});

test("status reports an absent session as unknown without treating a get miss as absence", async () => {
  const { deps, calls } = host({ inspectMissing: true });
  const r = res();
  await createStatusHandler(deps)(req({ body }), r);
  assert.equal(r.json.exists, false);
  assert.equal(r.json.state, "unknown");
  assert.equal(r.json.queueable, false);
  assert.equal(calls.inspect.length, 1, "a loaded-agent miss must fall through to the read-only inspect");
});

/* ------------------------------------------------------------------ *
 * authentication and binding
 * ------------------------------------------------------------------ */

test("a wrong, missing or malformed bearer secret is refused", async () => {
  for (const token of ["wrong", null, "", "test-key-not-a-real-secret "]) {
    const { deps, calls } = host();
    const r = res();
    await createStatusHandler(deps)(req({ body, token }), r);
    assert.equal(r.state.status, 401, `token ${JSON.stringify(token)}`);
    assert.equal(r.json.error, internals.E.unauthorized);
    assert.equal(calls.prompt.length, 0);
  }
});

test("an unconfigured secret cannot authenticate anything", async () => {
  const { deps } = host({ secret: null });
  const r = res();
  await createStatusHandler(deps)(req({ body }), r);
  assert.equal(r.state.status, 401);
});

test("a non-loopback peer is refused even with the correct secret", async () => {
  const { deps, calls } = host();
  const r = res();
  await createStatusHandler(deps)(req({ body, address: "192.168.1.20" }), r);
  assert.equal(r.state.status, 401);
  assert.equal(r.json.reason, "authentication required");
  assert.equal(calls.resolve, 0, "a remote caller is refused before any credential work");
});

test("only exact configured bindings are accepted", async () => {
  const cases = [
    { ...body, session_id: "session-bbbbbbbb-1111-2222-3333-444444444444" },
    { ...body, project_id: "proj-2" },
    { ...body, agent_id: "agent-2" },
  ];
  for (const target of cases) {
    const { deps, calls } = host();
    const r = res();
    await createStatusHandler(deps)(req({ body: target }), r);
    assert.equal(r.state.status, 403, JSON.stringify(target));
    assert.equal(r.json.error, internals.E.not_bound);
    assert.equal(calls.inspect.length, 0);
  }
});

test("a request cannot introduce fields, and unknown fields are refused", async () => {
  const { deps } = host();
  const withExtra = res();
  await createStatusHandler(deps)(req({ body: { ...body, mode: "steer" } }), withExtra);
  assert.equal(withExtra.state.status, 400);
  assert.equal(withExtra.json.error, internals.E.bad_field);

  const withContent = res();
  await createWakeHandler(deps)(req({ body: { ...wakeBody, content: "arbitrary text" } }), withContent);
  assert.equal(withContent.state.status, 400);

  const withEndpoint = res();
  await createStatusHandler(deps)(req({ body: { ...body, endpoint: "/api" } }), withEndpoint);
  assert.equal(withEndpoint.state.status, 400);
});

test("malformed, oversized and wrong-content-type requests are refused", async () => {
  const { deps } = host();

  const badJson = res();
  await createStatusHandler(deps)(req({ body: "{not json" }), badJson);
  assert.equal(badJson.state.status, 400);
  assert.equal(badJson.json.error, internals.E.bad_json);

  const tooLarge = res();
  await createStatusHandler(deps)(req({ body: JSON.stringify({ ...body, pad: "x".repeat(internals.MAX_BODY_BYTES) }) }), tooLarge);
  assert.equal(tooLarge.state.status, 413);
  assert.equal(tooLarge.json.error, internals.E.body_too_large);

  const wrongType = res();
  await createStatusHandler(deps)(req({ body, contentType: "text/plain" }), wrongType);
  assert.equal(wrongType.state.status, 415);

  const noType = res();
  await createStatusHandler(deps)(req({ body, contentType: null }), noType);
  assert.equal(noType.state.status, 415);

  const wrongMethod = res();
  await createStatusHandler(deps)(req({ body, method: "GET" }), wrongMethod);
  assert.equal(wrongMethod.state.status, 405);
});

test("identifiers must be bounded printable strings", async () => {
  const { deps } = host();
  for (const bad of [123, "", "x".repeat(internals.MAX_ID_CHARS + 1), "has\u0000nul", null, ["a"]]) {
    const r = res();
    await createStatusHandler(deps)(req({ body: { ...body, project_id: bad } }), r);
    assert.equal(r.state.status, 400, JSON.stringify(bad));
    assert.equal(r.json.error, internals.E.bad_field);
  }
});

/* ------------------------------------------------------------------ *
 * wake endpoint
 * ------------------------------------------------------------------ */

test("wake submits exactly one queued prompt and reports acceptance only", async () => {
  const { deps, calls } = host();
  const r = res();
  await createWakeHandler(deps)(req({ body: wakeBody }), r);
  assert.equal(r.state.status, 202);
  assert.deepEqual(r.json, { ok: true, accepted: true, request_id: requestIdFor(wakeBody) });
  assert.equal(calls.prompt.length, 1);
  const [{ request, signal }] = calls.prompt;
  assert.equal(request.mode, "queue", "queue is the only mode this plugin may use");
  assert.equal(request.sessionId, BINDING.session_id);
  assert.equal(request.requestId, requestIdFor(wakeBody));
  assert.deepEqual(request.content, [{ type: "text", text: reminderText(wakeBody) }]);
  assert.deepEqual(Object.keys(request).sort(), ["content", "mode", "requestId", "sessionId"]);
  assert.ok(signal instanceof AbortSignal);
  assert.equal(signal.aborted, false);
});

test("acceptance never claims a turn started or work completed", async () => {
  const { deps } = host();
  const r = res();
  await createWakeHandler(deps)(req({ body: wakeBody }), r);
  const keys = Object.keys(r.json).sort();
  assert.deepEqual(keys, ["accepted", "ok", "request_id"]);
  for (const forbidden of ["started", "completed", "turn", "message_id", "delivered"]) {
    assert.ok(!keys.includes(forbidden), `must not report ${forbidden}`);
  }
});

test("a retry of the same message reuses one request id and one body", async () => {
  const { deps, calls } = host({ live: (id) => (id === BINDING.session_id ? { id, status: "running" } : undefined) });
  const handler = createWakeHandler(deps);
  const first = res();
  await handler(req({ body: wakeBody }), first);
  const second = res();
  await handler(req({ body: wakeBody }), second);
  assert.equal(calls.prompt.length, 2, "the plugin itself does not suppress a retry");
  assert.equal(calls.prompt[0].request.requestId, calls.prompt[1].request.requestId);
  assert.deepEqual(calls.prompt[0].request.content, calls.prompt[1].request.content);
  assert.equal(first.json.request_id, second.json.request_id);
});

test("concurrent submissions for one message carry an identical request id", async () => {
  const { deps, calls } = host({ live: (id) => (id === BINDING.session_id ? { id, status: "running" } : undefined) });
  const handler = createWakeHandler(deps);
  const responses = await Promise.all([0, 1, 2].map(() => {
    const r = res();
    return handler(req({ body: wakeBody }), r).then(() => r);
  }));
  assert.equal(calls.prompt.length, 3, "de-duplication is the host's job; the plugin forwards every attempt");
  const ids = new Set(calls.prompt.map((call) => call.request.requestId));
  assert.equal(ids.size, 1, "all concurrent attempts share one request id");
  for (const r of responses) assert.equal(r.json.request_id, requestIdFor(wakeBody));
});

test("a missing session is refused and never submitted", async () => {
  const { deps, calls } = host({ inspectMissing: true });
  const r = res();
  await createWakeHandler(deps)(req({ body: wakeBody }), r);
  assert.equal(r.state.status, 404);
  assert.equal(r.json.error, internals.E.not_found);
  assert.equal(calls.prompt.length, 0, "no substitute session may be created or prompted");
});

test("host failure codes are surfaced with their real cause", async () => {
  const cases = [
    ["session/not-found", 404, internals.E.not_found],
    ["session/agent-busy", 409, internals.E.subagent],
    ["session/writer-held", 409, internals.E.write_locked],
    ["gateway/internal", 502, internals.E.submit_failed],
  ];
  for (const [code, status, expected] of cases) {
    const error = new Error(code);
    error.code = code;
    const { deps } = host({ promptError: error, live: undefined });
    const r = res();
    await createWakeHandler(deps)(req({ body: wakeBody }), r);
    assert.equal(r.state.status, status, code);
    assert.equal(r.json.error, expected, code);
    assert.equal(r.json.ok, false);
  }
});

test("an aborted submission reports an unknown outcome instead of success", async () => {
  const { deps, calls } = host();
  // A submission that never settles, so only the handler's own timeout ends it.
  deps.sessionController.prompt = (request, signal) => {
    calls.prompt.push({ request, signal });
    return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    });
  };
  testing.submitTimeoutMs = 10;
  try {
    const r = res();
    await createWakeHandler(deps)(req({ body: wakeBody }), r);
    assert.equal(r.state.status, 504, "a timed-out submit must not report success");
    assert.equal(r.json.ok, false);
    assert.equal(r.json.error, internals.E.submit_unknown);
    assert.ok(!("accepted" in r.json), "must not report acceptance for an unknown outcome");
    assert.match(String(r.json.reason), /retry with the same message_id/u);
    assert.equal(calls.prompt[0].signal.aborted, true, "the handler aborted the submission");
  } finally {
    testing.submitTimeoutMs = internals.DEFAULT_SUBMIT_TIMEOUT_MS;
  }
});

test("a submission that resolves before the timeout is still accepted", async () => {
  const { deps } = host();
  testing.submitTimeoutMs = 50;
  try {
    const r = res();
    await createWakeHandler(deps)(req({ body: wakeBody }), r);
    assert.equal(r.state.status, 202);
    assert.deepEqual(r.json, { ok: true, accepted: true, request_id: requestIdFor(wakeBody) });
  } finally {
    testing.submitTimeoutMs = internals.DEFAULT_SUBMIT_TIMEOUT_MS;
  }
});

test("a caller cannot choose the message text", async () => {
  const { deps, calls } = host();
  const r = res();
  await createWakeHandler(deps)(req({ body: { ...wakeBody, text: "please do something else" } }), r);
  assert.equal(r.state.status, 400);
  assert.equal(calls.prompt.length, 0);
});

/* ------------------------------------------------------------------ *
 * lifecycle
 * ------------------------------------------------------------------ */

test("apply registers both routes as effects and reload-safe disposers", async () => {
  const effects = [];
  const disposers = [];
  const registered = [];
  const ctx = {
    get(key) {
      const { deps } = host();
      return {
        sessionController: deps.sessionController,
        credentials: deps.credentials,
        agents: deps.agents,
      }[key];
    },
    logger: { info() {}, warn() {} },
    effect(factory, label) {
      effects.push(label);
      disposers.push(factory());
    },
    webServer: {
      register(route) {
        registered.push(route);
        return () => {};
      },
    },
  };
  await apply(ctx, { bindings: [BINDING] });
  assert.deepEqual(effects, ["tsunagou-wake: status route", "tsunagou-wake: wake route"]);
  assert.deepEqual(registered.map((r) => [r.kind, r.path]), [
    ["exact", internals.STATUS_PATH],
    ["exact", internals.WAKE_PATH],
  ]);
  for (const route of registered) assert.equal(typeof route.handler, "function");
  assert.equal(disposers.length, 2);
});

test("apply refuses to load without a required service", async () => {
  const ctx = {
    get: () => undefined,
    logger: { info() {}, warn() {} },
    effect() {},
    webServer: { register: () => () => {} },
  };
  await assert.rejects(() => apply(ctx, { bindings: [BINDING] }), /required service/u);
});

import { mkdtempSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function managedFixture(t) {
  const directory = mkdtempSync(join(tmpdir(), 'tsunagou-wake-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = join(directory, 'managed.json');
  const key = 'a'.repeat(48);
  const write = (bindings = [BINDING], secret = key) => writeFileSync(file,
    JSON.stringify({ format_version: 1, key: secret, bindings }));
  write();
  return { file, directory, key, write };
}

test('managed credentials and bindings refresh together without credential service', async (t) => {
  const f = managedFixture(t);
  const { deps, calls } = host();
  deps.managedFile = f.file;
  const call = async (token) => {
    const r = res();
    await createWakeHandler(deps)(req({ body: wakeBody, token }), r);
    return r;
  };
  assert.equal((await call(f.key)).state.status, 202);
  f.write([], 'b'.repeat(48));
  assert.equal((await call(f.key)).state.status, 401);
  assert.equal((await call('b'.repeat(48))).state.status, 403);
  f.write([BINDING], 'b'.repeat(48));
  assert.equal((await call('b'.repeat(48))).state.status, 202);
  assert.equal(calls.resolve, 0);
  assert.equal(calls.prompt.length, 2);
});

test('invalid managed data cannot fall back to legacy credentials/bindings', async (t) => {
  const f = managedFixture(t);
  const { deps, calls } = host();
  deps.managedFile = f.file;
  for (const contents of ['{', '{}', JSON.stringify({ format_version: 2, key: f.key, bindings: [BINDING] }),
    JSON.stringify({ format_version: 1, key: f.key, bindings: [{ project_id: 'p' }] })]) {
    writeFileSync(f.file, contents);
    const r = res();
    await createWakeHandler(deps)(req({ body: wakeBody }), r);
    assert.equal(r.state.status, 500);
    assert.equal(r.state.body.includes(f.file), false);
    assert.equal(r.state.body.includes(f.key), false);
  }
  assert.equal(calls.resolve, 0);
  assert.equal(calls.prompt.length, 0);
  assert.throws(() => readConfig({ managedFile: 'relative.json', bindings: [BINDING] }), /absolute/);
});

test('managed activation publishes actual bound port and disposal preserves newer owner', async (t) => {
  const f = managedFixture(t);
  f.write([]);
  const { deps } = host();
  const disposers = [];
  const ctx = { get: (key) => deps[key], logger: deps.logger,
    effect: (factory) => disposers.push(factory()),
    webServer: { host: '127.0.0.1', port: 23456,
      register: () => () => {} } };
  await apply(ctx, { managedFile: f.file });
  const runtimeFile = join(f.directory, 'runtime.json');
  const runtime = JSON.parse(readFileSync(runtimeFile));
  assert.equal(runtime.endpoint, 'http://127.0.0.1:23456');
  assert.equal(runtime.contract_version, 1);
  assert.equal(runtime.pid, process.pid);
  assert.equal(JSON.stringify(runtime).includes(f.key), false);
  writeFileSync(runtimeFile, JSON.stringify({ ...runtime, instance_id: 'new-owner' }));
  disposers.at(-1)();
  assert.equal(existsSync(runtimeFile), true);
  writeFileSync(runtimeFile, JSON.stringify(runtime));
  disposers.at(-1)();
  assert.equal(existsSync(runtimeFile), false);
  ctx.webServer.host = '0.0.0.0';
  await assert.rejects(() => apply(ctx, { managedFile: f.file }), /loopback/);
  assert.equal(existsSync(runtimeFile), false);
});
