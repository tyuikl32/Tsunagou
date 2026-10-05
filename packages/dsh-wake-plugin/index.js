/**
 * Tsunagou wake plugin for DeepSeek Harness Desktop.
 *
 * Wakes an already-existing DSH session from a local background caller so it
 * reads its own Tsunagou context and inbox. No window, focus, clipboard or
 * keystroke is touched.
 *
 * Two loopback-only endpoints on the host's own webServer:
 *   POST /tsunagou/wake/status  existence, load state, busy state
 *   POST /tsunagou/wake         admit the fixed read reminder
 *
 * The only write is `sessionController.prompt({ mode: 'queue' })`, so the host
 * owns resume, queueing and de-duplication. This plugin deliberately adds no
 * second de-duplication store, no scheduler, no retry driver, no arbitrary
 * message forwarding and no UI automation.
 *
 * Runtime imports are Node built-ins only. The Cordis context services arrive
 * as injected arguments (`apply(ctx, config)`), which is what keeps this file
 * loadable from a profile whose node_modules cannot resolve the harness's own
 * packages.
 */

import { createHash, timingSafeEqual, randomUUID } from "node:crypto";
import { readFileSync, writeFileSync, renameSync, unlinkSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";

/** Loader identity. */
export const name = "tsunagou-wake";

/**
 * Required services. `sessionController` is the only write path; `webServer`
 * serves the two routes; `credentials` resolves the bearer reference per
 * request; `agents` answers the loaded/busy half of status without activating
 * anything.
 */
export const inject = ["sessionController", "webServer", "credentials", "agents"];

const STATUS_PATH = "/tsunagou/wake/status";
const WAKE_PATH = "/tsunagou/wake";

/** Request bodies are one small JSON object; anything larger is not one. */
const MAX_BODY_BYTES = 8 * 1024;
/** Bound on every identifier a caller supplies. */
const MAX_ID_CHARS = 200;
/** submit timeout: an unknown outcome, never reported as success. */
const DEFAULT_SUBMIT_TIMEOUT_MS = 30_000;

/**
 * Test seam. Only the submit timeout is overridable, so the unknown-outcome
 * branch can be exercised without waiting 30 seconds. Reset it when done.
 */
export const testing = {
  submitTimeoutMs: DEFAULT_SUBMIT_TIMEOUT_MS,
};

/** Stable error vocabulary. */
const E = {
  method: "method_not_allowed",
  content_type: "unsupported_content_type",
  body_too_large: "body_too_large",
  bad_json: "invalid_json",
  bad_field: "invalid_field",
  unauthorized: "unauthorized",
  not_bound: "target_not_bound",
  not_found: "session_not_found",
  subagent: "session_subagent_owned",
  write_locked: "session_write_locked",
  submit_failed: "submit_failed",
  submit_unknown: "submit_unknown",
  internal: "internal_error",
};

/**
 * The fixed read reminder. The task body is never carried here: only the
 * verified project and message identity is appended, and business content
 * stays in Tsunagou.
 */
const REMINDER =
  "请读取你自己的 Tsunagou 项目上下文和收件箱，核对当前身份与指定项目，"
  + "按已有授权处理指定消息关联的待办，并通过 Tsunagou 回复结果。"
  + "不要代替用户确认项目完成。";

const REQUEST_ID_PREFIX = "tsunagou-wake-v1:";

/** Fields each endpoint accepts. No endpoint accepts content, mode or commands. */
const STATUS_FIELDS = Object.freeze(["project_id", "agent_id", "session_id"]);
const WAKE_FIELDS = Object.freeze(["project_id", "agent_id", "session_id", "message_id"]);

/* ------------------------------------------------------------------ *
 * pure helpers
 * ------------------------------------------------------------------ */

/**
 * Stable request id over the exact identity tuple.
 *
 * Same tuple always yields the same id and the same body, which is what lets a
 * retry reuse the host's de-duplication. The host compares request ids only —
 * it ignores content for an already-seen id — so this must never become
 * time-stamped or randomised.
 *
 * @param ids - project, agent, session, message.
 * @returns the branded request id string.
 */
export function requestIdFor(ids) {
  const tuple = [ids.project_id, ids.agent_id, ids.session_id, ids.message_id];
  return REQUEST_ID_PREFIX + createHash("sha256").update(JSON.stringify(tuple), "utf8").digest("hex");
}

/**
 * The one message body this plugin can submit.
 *
 * @param ids - verified project and message identity.
 * @returns the exact prompt text.
 */
export function reminderText(ids) {
  return `${REMINDER}\n\nproject_id: ${ids.project_id}\nmessage_id: ${ids.message_id}`;
}

/**
 * Whether an address is a loopback peer.
 *
 * The check is deliberately on the socket peer rather than on a header: a Host
 * header is caller-controlled and would not restrict anything.
 *
 * @param address - `req.socket.remoteAddress`.
 * @returns true for IPv4 loopback, IPv6 loopback, and IPv4-mapped loopback.
 */
export function isLoopback(address) {
  if (typeof address !== "string") return false;
  if (address === "::1" || address === "127.0.0.1") return true;
  // IPv4-mapped and IPv4-compatible forms: ::ffff:127.0.0.1, ::127.0.0.1
  const mapped = /^::(?:ffff:)?(\d{1,3}(?:\.\d{1,3}){3})$/u.exec(address);
  return mapped !== null && mapped[1] === "127.0.0.1";
}

/**
 * Compare a presented secret with the resolved one in constant time.
 *
 * @param presented - bearer value from the request.
 * @param expected - resolved secret.
 * @returns whether they match.
 */
export function secretMatches(presented, expected) {
  if (typeof presented !== "string" || typeof expected !== "string") return false;
  const a = Buffer.from(presented, "utf8");
  const b = Buffer.from(expected, "utf8");
  if (a.length !== b.length || a.length === 0) return false;
  return timingSafeEqual(a, b);
}

/** An identifier the caller supplied. */
function isId(value) {
  return typeof value === "string"
    && value.length > 0
    && value.length <= MAX_ID_CHARS
    && !/[\u0000-\u001f\u007f]/u.test(value);
}

/**
 * Validate one request body against its accepted field list.
 *
 * @param body - parsed JSON value.
 * @param fields - exact accepted field names.
 * @param ids - identifier fields that must be present and well-formed.
 * @returns the projected identifiers, or a failure code.
 */
function projectBody(body, fields, ids) {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return { error: E.bad_field };
  for (const key of Object.keys(body)) if (!fields.includes(key)) return { error: E.bad_field };
  const out = {};
  for (const key of ids) {
    if (body[key] === undefined) return { error: E.bad_field };
    if (!isId(body[key])) return { error: E.bad_field };
    out[key] = body[key];
  }
  return { ids: out };
}

/* ------------------------------------------------------------------ *
 * plugin
 * ------------------------------------------------------------------ */

/**
 * Validate the plugin config once at load.
 *
 * Bindings are read only from configuration; no request can extend them.
 *
 * @param config - the profile entry's config object.
 * @returns the frozen runtime config, or a throw naming the first problem.
 */
export function readConfig(config) {
  if (config === null || typeof config !== "object" || Array.isArray(config)) {
    throw new TypeError("tsunagou-wake: config object is required");
  }
  if (Object.hasOwn(config, "managedFile")) {
    if (typeof config.managedFile !== "string" || !isAbsolute(config.managedFile)) {
      throw new TypeError("tsunagou-wake: managedFile must be an absolute path");
    }
    return Object.freeze({ managedFile: config.managedFile });
  }
  const ref = config.keyEnv ?? "TSUNAGOU_WAKE_KEY";
  if (typeof ref !== "string" || !/^[A-Za-z_][A-Za-z0-9_]*$/u.test(ref)) {
    throw new TypeError("tsunagou-wake: keyEnv must be an environment-variable name");
  }
  if (!Array.isArray(config.bindings) || config.bindings.length === 0) {
    throw new TypeError("tsunagou-wake: bindings must be a non-empty array");
  }
  const bindings = config.bindings.map((entry, index) => {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      throw new TypeError(`tsunagou-wake: bindings[${index}] must be an object`);
    }
    for (const key of ["project_id", "agent_id", "session_id"]) {
      if (!isId(entry[key])) throw new TypeError(`tsunagou-wake: bindings[${index}].${key} must be a non-empty string`);
    }
    return Object.freeze({
      project_id: entry.project_id,
      agent_id: entry.agent_id,
      session_id: entry.session_id,
    });
  });
  return Object.freeze({ keyEnv: ref, bindings: Object.freeze(bindings) });
}

// Initialized by Tsunagou in a user-private directory, never by HTTP callers.
// Read one snapshot per request so secret and bindings rotate together.
function readManaged(path) {
  const value = JSON.parse(readFileSync(path, "utf8"));
  if (value?.format_version !== 1 || typeof value.key !== "string"
    || value.key.length < 32 || !Array.isArray(value.bindings)) {
    throw new Error("invalid managed configuration");
  }
  const bindings = value.bindings.length === 0 ? [] : readConfig({ bindings: value.bindings }).bindings;
  return { key: value.key, bindings };
}

function publishRuntime(ctx, managedFile) {
  const address = { address: ctx.webServer.host, port: ctx.webServer.port };
  if (address.address !== "127.0.0.1"
    || !Number.isInteger(address.port) || address.port < 1 || address.port > 65535) {
    throw new Error("tsunagou-wake: bound loopback server address is unavailable");
  }
  const host = "127.0.0.1";
  const runtimePath = join(dirname(managedFile), "runtime.json");
  const instance = randomUUID();
  const temporary = `${runtimePath}.${instance}.tmp`;
  const runtime = { format_version: 1, contract_version: 1, plugin_version: "0.1.0",
    endpoint: `http://${host}:${address.port}`, instance_id: instance, pid: process.pid };
  try {
    writeFileSync(temporary, JSON.stringify(runtime), { mode: 0o600, flag: "wx" });
    renameSync(temporary, runtimePath);
  } finally {
    try { unlinkSync(temporary); } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  return () => {
    try {
      if (JSON.parse(readFileSync(runtimePath, "utf8")).instance_id === instance) unlinkSync(runtimePath);
    } catch (error) { if (error.code !== "ENOENT") throw error; }
  };
}

/**
 * Register the two routes.
 *
 * @param ctx - the host context; only `webServer` is touched here.
 * @param config - raw profile config.
 */
export async function apply(ctx, config) {
  const settings = readConfig(config);
  const deps = {
    sessionController: ctx.get("sessionController"),
    credentials: ctx.get("credentials"),
    agents: ctx.get("agents"),
    logger: ctx.logger,
    keyEnv: settings.keyEnv,
    bindings: settings.bindings,
    managedFile: settings.managedFile,
  };
  for (const service of ["sessionController", "credentials", "agents"]) {
    if (deps[service] === undefined) {
      throw new Error(`tsunagou-wake: required service "${service}" is unavailable`);
    }
  }
  if (settings.managedFile) readManaged(settings.managedFile);
  // Effect-owned registration: a reload removes both routes before re-adding,
  // so a repeated load cannot collide on an already-registered path.
  ctx.effect(
    () => ctx.webServer.register({ kind: "exact", path: STATUS_PATH, handler: createStatusHandler(deps) }),
    "tsunagou-wake: status route",
  );
  ctx.effect(
    () => ctx.webServer.register({ kind: "exact", path: WAKE_PATH, handler: createWakeHandler(deps) }),
    "tsunagou-wake: wake route",
  );
  if (settings.managedFile) {
    ctx.effect(() => publishRuntime(ctx, settings.managedFile), "tsunagou-wake: runtime discovery");
  }
  ctx.logger?.info?.("tsunagou-wake: routes enabled");
}

/* ------------------------------------------------------------------ *
 * HTTP plumbing
 * ------------------------------------------------------------------ */

/**
 * Send one JSON response and end the exchange.
 *
 * @param res - node response.
 * @param status - HTTP status.
 * @param payload - JSON-serialisable body.
 */
function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  res.end(body);
}

/** A failed request: stable code plus a de-identified reason. */
function sendError(res, status, code, reason) {
  sendJson(res, status, { ok: false, error: code, reason });
}

/**
 * Read and parse a bounded JSON body. The caller's bytes are never logged.
 *
 * @param req - node request.
 * @returns parsed value, or a failure code.
 */
function readJsonBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    req.on("data", (chunk) => {
      if (settled) return;
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        finish({ error: E.body_too_large });
        return;
      }
      chunks.push(chunk);
    });
    req.on("error", () => finish({ error: E.bad_json }));
    req.on("end", () => {
      if (settled) return;
      try {
        finish({ body: JSON.parse(Buffer.concat(chunks).toString("utf8")) });
      } catch {
        finish({ error: E.bad_json });
      }
    });
  });
}

/**
 * Run the shared prefix: loopback, method, content type, bearer, body, binding.
 *
 * @param deps - plugin dependencies.
 * @param req - node request.
 * @param res - node response.
 * @param fields - accepted body fields.
 * @param ids - required identifier fields.
 * @returns the verified identifiers, or null once a response was sent.
 */
async function admit(deps, req, res, fields, ids) {
  if (!isLoopback(req.socket?.remoteAddress)) {
    // Identical refusal for remote and unauthenticated local callers.
    sendError(res, 401, E.unauthorized, "authentication required");
    return null;
  }
  if (req.method !== "POST") {
    sendError(res, 405, E.method, "POST only");
    return null;
  }
  const contentType = String(req.headers["content-type"] ?? "");
  if (!contentType.toLowerCase().startsWith("application/json")) {
    sendError(res, 415, E.content_type, "application/json required");
    return null;
  }
  const token = bearerOf(req.headers.authorization);
  let expected;
  let bindings;
  try {
    // Resolved per request so a rotated secret reaches the next call without a
    // restart, and so nothing is cached in this plugin.
    if (deps.managedFile) {
      const snapshot = readManaged(deps.managedFile);
      expected = snapshot.key;
      bindings = snapshot.bindings;
    } else {
      const resolved = await deps.credentials.resolve(deps.keyEnv);
      expected = resolved?.value;
      bindings = deps.bindings;
    }
  } catch {
    sendError(res, 500, E.internal, "credential resolution failed");
    return null;
  }
  if (!secretMatches(token, expected)) {
    sendError(res, 401, E.unauthorized, "authentication required");
    return null;
  }
  const read = await readJsonBody(req);
  if (read.error !== undefined) {
    const status = read.error === E.body_too_large ? 413 : 400;
    sendError(res, status, read.error, read.error === E.body_too_large ? "body too large" : "malformed JSON body");
    return null;
  }
  const projected = projectBody(read.body, fields, ids);
  if (projected.error !== undefined) {
    sendError(res, 400, projected.error, "body must contain exactly the documented identifier fields");
    return null;
  }
  const bound = bindings.some(
    (entry) => entry.project_id === projected.ids.project_id
      && entry.agent_id === projected.ids.agent_id
      && entry.session_id === projected.ids.session_id,
  );
  if (!bound) {
    // Configuration is the only place bindings come from.
    sendError(res, 403, E.not_bound, "target is not in the configured bindings");
    return null;
  }
  return projected.ids;
}

/**
 * Extract a bearer token without accepting any other scheme.
 *
 * @param header - the authorization header value.
 * @returns the token, or undefined.
 */
function bearerOf(header) {
  if (typeof header !== "string") return undefined;
  const match = /^Bearer (.+)$/u.exec(header);
  return match === null ? undefined : match[1];
}

/* ------------------------------------------------------------------ *
 * status
 * ------------------------------------------------------------------ */

/**
 * Observe one bound session without activating it.
 *
 * `agents.get` answers only the loaded half; a miss is never reported as
 * "absent" — it falls through to `inspect`, which reads durable storage.
 *
 * @param deps - plugin dependencies.
 * @param sessionId - verified session identity.
 * @returns `{ exists, loaded, busy }`.
 */
async function observeSession(deps, sessionId) {
  const live = deps.agents.get(sessionId);
  if (live !== undefined) {
    return { exists: true, loaded: true, busy: live.status === "running" };
  }
  try {
    await deps.sessionController.inspect(sessionId);
  } catch (error) {
    if (error?.code === "session/not-found") return { exists: false, loaded: false, busy: false };
    throw error;
  }
  return { exists: true, loaded: false, busy: false };
}

/**
 * Handler for POST /tsunagou/wake/status.
 *
 * @param deps - plugin dependencies.
 * @returns a node request handler.
 */
export function createStatusHandler(deps) {
  return async function statusHandler(req, res) {
    try {
      const ids = await admit(deps, req, res, STATUS_FIELDS, ["project_id", "agent_id", "session_id"]);
      if (ids === null) return;
      const observed = await observeSession(deps, ids.session_id);
      const state = !observed.exists ? "unknown" : !observed.loaded ? "unloaded" : observed.busy ? "running" : "idle";
      sendJson(res, 200, {
        ok: true,
        project_id: ids.project_id,
        agent_id: ids.agent_id,
        session_id: ids.session_id,
        exists: observed.exists,
        loaded: observed.loaded,
        state,
        // `queue` accepts a new turn whether the session is loaded and idle, or
        // loaded and running, or persisted-but-unloaded (the host resumes it).
        // The one case this cannot see is subagent ownership, which only the
        // wake call can report; see README "Status fields".
        queueable: observed.exists,
      });
    } catch {
      sendError(res, 500, E.internal, "status check failed");
    }
  };
}

/* ------------------------------------------------------------------ *
 * wake
 * ------------------------------------------------------------------ */

/** Map a host failure onto the stable error vocabulary. */
function submitFailure(error) {
  switch (error?.code) {
    case "session/not-found":
      return { status: 404, code: E.not_found, reason: "session does not exist" };
    case "session/agent-busy":
      return { status: 409, code: E.subagent, reason: "session is owned by subagent routing" };
    case "session/writer-held":
      return { status: 409, code: E.write_locked, reason: "another process holds the session write handle" };
    default:
      return { status: 502, code: E.submit_failed, reason: "host rejected the prompt" };
  }
}

/**
 * Handler for POST /tsunagou/wake.
 *
 * @param deps - plugin dependencies.
 * @returns a node request handler.
 */
export function createWakeHandler(deps) {
  return async function wakeHandler(req, res) {
    let ids;
    try {
      ids = await admit(deps, req, res, WAKE_FIELDS, ["project_id", "agent_id", "session_id", "message_id"]);
    } catch {
      sendError(res, 500, E.internal, "request admission failed");
      return;
    }
    if (ids === null) return;

    // Confirm the session exists before submitting, so a missing session is
    // reported as such instead of surfacing as a resume failure.
    try {
      const observed = await observeSession(deps, ids.session_id);
      if (!observed.exists) {
        sendError(res, 404, E.not_found, "session does not exist");
        return;
      }
    } catch (error) {
      const failure = submitFailure(error);
      sendError(res, failure.status, failure.code, failure.reason);
      return;
    }

    const requestId = requestIdFor(ids);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), testing.submitTimeoutMs);
    try {
      const result = await deps.sessionController.prompt(
        {
          requestId,
          sessionId: ids.session_id,
          mode: "queue",
          content: [{ type: "text", text: reminderText(ids) }],
        },
        controller.signal,
      );
      if (result?.accepted !== true) {
        sendError(res, 502, E.submit_failed, "host did not accept the prompt");
        return;
      }
      // `accepted` means admitted, or already admitted under this request id.
      // It does not mean a turn started or that any work completed.
      sendJson(res, 202, { ok: true, accepted: true, request_id: requestId });
    } catch (error) {
      if (controller.signal.aborted) {
        // The outcome is genuinely unknown. Report it as unknown; the caller may
        // retry with the same request id, which the host de-duplicates.
        deps.logger?.warn?.(`tsunagou-wake: submit timed out for request ${requestId}`);
        sendError(res, 504, E.submit_unknown, "submission outcome is unknown; retry with the same message_id");
        return;
      }
      const failure = submitFailure(error);
      sendError(res, failure.status, failure.code, failure.reason);
    } finally {
      clearTimeout(timer);
    }
  };
}

/* ------------------------------------------------------------------ *
 * exported for tests only
 * ------------------------------------------------------------------ */

export const internals = Object.freeze({
  E,
  STATUS_PATH,
  WAKE_PATH,
  REMINDER,
  MAX_BODY_BYTES,
  MAX_ID_CHARS,
  DEFAULT_SUBMIT_TIMEOUT_MS,
});
