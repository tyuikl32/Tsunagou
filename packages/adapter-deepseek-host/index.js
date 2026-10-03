/**
 * Host-side MCP client for DeepSeek Harness that carries the caller's identity.
 *
 * The stock `@deepseek-ai/dsh-mcp-client` spawns the bridge and calls
 * `client.callTool({ name, arguments })` - no `_meta`. The bridge can therefore not tell
 * which conversation is calling, and a conversation that borrows another conversation's
 * overlay reaches Tsunagou as that other conversation.
 *
 * This provider is the same shape of plugin, over the same stdio MCP server, with one
 * difference: every `tools/call` carries `_meta[<key>] = <the live session id>` taken from
 * the runtime's own execution context for that call. The value is read from
 * `exec.agent.session.id` at call time, so it cannot be supplied by the model, copied from
 * the overlay, or inferred from a process.
 *
 * Deliberately dependency-free: the profile's node_modules does not resolve the harness's
 * own packages, so the MCP handshake is done directly. It is initialize / tools/list /
 * tools/call, which is all this adapter needs.
 */

import { spawn } from "node:child_process";
import { isAbsolute } from "node:path";

export const name = "tsunagou-host-identity";
export const inject = ["tools"];

/** DeepSeek function-name contract from the stock client: at most 64 characters. */
const MAX_PUBLIC_NAME_LENGTH = 64;
const DEFAULT_META_KEY = "tsunagou.hostSessionId";
const CONNECT_TIMEOUT_MS = 120_000;
const MAX_CONNECT_OUTPUT = 1024 * 1024;
/** An invitation is one line of base64 plus a short prefix; anything longer is not one. */
const MAX_INVITE_LENGTH = 8192;

const contentOutput = {
  schema: {
    type: "object",
    properties: { content: { type: "array", items: {} } },
    required: ["content"],
    additionalProperties: false,
  },
  render(_args, value) { return value.content; },
};

function toolResult(value) {
  return { content: [{ type: "text", text: JSON.stringify(value) }] };
}

function connectFailure(error, exitCode) {
  return { status: "error", error, host_ready: false,
    ...(Number.isInteger(exitCode) ? { exit_code: exitCode } : {}),
    next: "Resolve this connection error before verifying context__project_read; do not report the conversation ready." };
}

/**
 * Identity, directory and CLI launch line for this call - the trusted half of every action.
 *
 * Both actions (join this project, and the cross-machine pair below) must run with *this*
 * conversation's identity and the directory the host gave it, and with none of the stale
 * host state that may be lying around in the process environment. The model supplies none
 * of it, so one function answers it for all of them.
 */
function cliContext(config, exec) {
  const identity = exec?.agent?.session?.id;
  const cwd = exec?.agent?.session?.header?.cwd;
  if (typeof identity !== "string" || !identity.trim() || identity.includes("\0")) {
    return { error: connectFailure("tsunagou_host_identity_unavailable") };
  }
  if (typeof cwd !== "string" || !isAbsolute(cwd) || cwd.includes("\0")) {
    return { error: connectFailure("tsunagou_project_directory_unavailable") };
  }
  const runtime = config.connect;
  if (typeof runtime?.command !== "string" || !isAbsolute(runtime.command)
      || !Array.isArray(runtime.args) || runtime.args.some((arg) => typeof arg !== "string")) {
    return { error: connectFailure("tsunagou_runtime_not_configured") };
  }
  const environment = { ...process.env, ...runtime.env };
  for (const key of Object.keys(environment)) {
    if (/^(?:TSUNAGOU_|CODEX_)/i.test(key)
        || /^(?:DSH_SESSION_ID|OPENCODE_SESSION_ID|ZCODE_SESSION_ID)$/i.test(key)) delete environment[key];
  }
  environment.DSH_SESSION_ID = identity;
  if (config.env?.TSUNAGOU_ROUTING_DIR) environment.TSUNAGOU_ROUTING_DIR = config.env.TSUNAGOU_ROUTING_DIR;
  return { cwd, environment, runtime };
}

/**
 * Run the installed CLI once and hand back its last JSON line.
 *
 * Resolves ``{code, result}`` on a normal exit, or ``{stopped}`` when the call was bounded
 * out (timeout, output limit, spawn failure). Never infers a result from partial output.
 */
function runCli(context, cliArgs) {
  return new Promise((resolve) => {
    let child;
    let timer;
    let settled = false;
    let stdout = "";
    let bytes = 0;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    const stop = (error) => {
      try { child?.kill(); } catch { /* a failed spawn has no process */ }
      finish({ stopped: error });
    };
    try {
      child = spawn(context.runtime.command, cliArgs, { cwd: context.cwd, env: context.environment,
        stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    } catch {
      finish({ stopped: "tsunagou_cli_spawn_failed" });
      return;
    }
    timer = setTimeout(() => stop("tsunagou_cli_timeout"), CONNECT_TIMEOUT_MS);
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      bytes += Buffer.byteLength(chunk);
      if (bytes > MAX_CONNECT_OUTPUT) stop("tsunagou_cli_output_limit");
      else stdout += chunk;
    });
    // Raw CLI stderr may include paths, session IDs, or credentials. Drain it,
    // but return only the CLI's bounded, explicitly selected public fields.
    child.stderr.on("data", (chunk) => {
      bytes += chunk.length;
      if (bytes > MAX_CONNECT_OUTPUT) stop("tsunagou_cli_output_limit");
    });
    child.on("error", () => finish({ stopped: "tsunagou_cli_spawn_failed" }));
    child.on("close", (code) => {
      if (settled) return;
      let result;
      for (const line of stdout.trim().split(/\r?\n/).reverse()) {
        try { result = JSON.parse(line); break; } catch { /* prior status lines are not the receipt */ }
      }
      finish({ code, result });
    });
  });
}

/** The CLI's own error code, or a generic one: never a message we did not choose. */
function publicError(result, fallback) {
  return typeof result?.error === "string" && /^[a-z][a-z0-9_]*(?::[a-z0-9_:]*)?$/.test(result.error)
    ? result.error : fallback;
}

/** The shared runner stops with a generic name; each tool answers in its own vocabulary. */
function stopCode(prefix, stopped) {
  return `${prefix}_${String(stopped).replace(/^tsunagou_cli_/, "")}`;
}

/** Run only the installed CLI, with identity and cwd obtained from this tool call. */
async function runOnboarding(config, args, exec) {
  if (args === undefined) args = {};
  if (!args || typeof args !== "object" || Array.isArray(args)
      || Object.keys(args).some((key) => key !== "role")
      || (Object.hasOwn(args, "role") && !["worker", "main"].includes(args.role))) {
    return connectFailure("tsunagou_connect_invalid_arguments");
  }
  const context = cliContext(config, exec);
  if (context.error) return context.error;
  const selection = await runCli(context, [...context.runtime.args, "agent", "pending", "--adapter", "deepseek"]);
  if (selection.stopped) return connectFailure(stopCode("tsunagou_connect", selection.stopped));
  const pending = selection.result;
  if (selection.code !== 0 || !["none", "pending"].includes(pending?.status)) {
    return connectFailure(publicError(pending, "tsunagou_connect_pending_failed"), selection.code);
  }
  const cliArgs = [...context.runtime.args];
  if (pending.status === "pending") {
    if (pending.state !== "pending") return connectFailure("enrollment_not_pending");
    if (pending.adapter !== "deepseek" || typeof pending.project_root !== "string"
        || !isAbsolute(pending.project_root) || pending.project_root.includes("\0")
        || typeof pending.project_id !== "string" || !pending.project_id
        || typeof pending.enrollment_id !== "string" || !/^[a-f0-9]{32}$/.test(pending.enrollment_id)) {
      return connectFailure("tsunagou_connect_invalid_selection");
    }
    cliArgs.push("--project-root", pending.project_root);
  }
  cliArgs.push("agent", "connect", "--adapter", "deepseek", "--profile", "desktop", "--no-register-host");
  if (pending.status === "pending") cliArgs.push("--pending-enrollment-id", pending.enrollment_id);
  if (args.role !== undefined) cliArgs.push("--role", args.role);

  const outcome = await runCli(context, cliArgs);
  if (outcome.stopped) return connectFailure(stopCode("tsunagou_connect", outcome.stopped));
  const result = outcome.result;
  if (outcome.code !== 0 || result?.status !== "enrolled") {
    return connectFailure(publicError(result, "tsunagou_connect_failed"), outcome.code);
  }
  if (!["project_id", "agent_id"].every((key) => typeof result[key] === "string" && result[key])
      || !["worker", "main"].includes(result.role)) {
    return connectFailure("tsunagou_connect_invalid_receipt");
  }
  if (pending.status === "pending" && result.project_id !== pending.project_id) {
    return connectFailure("onboarding_project_mismatch");
  }
  const connected = { status: "enrolled", host_ready: false,
    next: `Call ${publicName(config.serverName || "tsunagou", "context__project_read")} in this conversation and verify project, Agent and ready status.` };
  for (const key of ["project_id", "agent_id", "role"]) {
    if (typeof result[key] === "string") connected[key] = result[key];
  }
  const session = result.session;
  if (session && typeof session === "object") {
    connected.session = {};
    for (const key of ["status", "baseline_status"]) {
      if (typeof session[key] === "string") connected.session[key] = session[key];
    }
    if (Number.isInteger(session.connection_epoch)) connected.session.connection_epoch = session.connection_epoch;
  }
  return connected;
}

/**
 * The cross-machine pair: report this conversation's number, or import an invitation.
 *
 * A host cannot name a DeepSeek Harness conversation - only this conversation knows its own
 * id - so enrolment across machines goes: this side reports the number, the host issues an
 * invitation bound to it, and this side imports it. Both are one CLI run; nothing here
 * writes to Tsunagou itself, and the invitation (which carries the one-time ticket) is
 * passed through, never echoed back into the conversation.
 */
async function runRemote(config, args, exec) {
  if (args === undefined) args = {};
  const allowed = ["action", "invite", "machine"];
  if (!args || typeof args !== "object" || Array.isArray(args)
      || Object.keys(args).some((key) => !allowed.includes(key))
      || !["whoami", "import"].includes(args.action)) {
    return { status: "error", error: "tsunagou_remote_invalid_arguments", next: "Call this tool with action=whoami, or action=import plus the invitation text." };
  }
  const invite = typeof args.invite === "string" ? args.invite.trim() : "";
  const machine = typeof args.machine === "string" ? args.machine.trim() : "";
  if (args.action === "import" && (!invite || invite.length > MAX_INVITE_LENGTH || invite.includes("\0"))) {
    return { status: "error", error: "tsunagou_remote_invite_required", next: "Pass the invitation text the host sent, exactly as it was sent." };
  }
  const context = cliContext(config, exec);
  if (context.error) return context.error;
  const cliArgs = [...context.runtime.args, "agent"];
  if (args.action === "whoami") cliArgs.push("whoami", "--adapter", "deepseek");
  else {
    cliArgs.push("import", invite, "--workdir", context.cwd);
    if (machine) cliArgs.push("--machine", machine);
  }

  const outcome = await runCli(context, cliArgs);
  if (outcome.stopped) {
    return { status: "error", error: stopCode("tsunagou_remote", outcome.stopped),
      next: "Retry once the machine is responsive." };
  }
  const result = outcome.result;
  if (outcome.code !== 0 || (result?.status !== "ok" && result?.status !== "imported")) {
    return { status: "error", error: publicError(result, "tsunagou_remote_failed"),
      ...(Number.isInteger(outcome.code) ? { exit_code: outcome.code } : {}) };
  }
  if (args.action === "whoami") {
    if (typeof result.conversation_id !== "string" || !result.conversation_id) {
      return { status: "error", error: "tsunagou_remote_invalid_receipt" };
    }
    return { status: "ok", conversation_id: result.conversation_id,
      next: "Send this number to the person on the host; they will issue the invitation and send it back." };
  }
  if (typeof result.project_id !== "string" || !result.project_id) {
    return { status: "error", error: "tsunagou_remote_invalid_receipt" };
  }
  const imported = { status: "imported", project_id: result.project_id, role: result.role,
    next: "Reload this window, then call the project-read tool in this conversation to verify readiness." };
  for (const key of ["adapter", "url", "workspace"]) {
    if (typeof result[key] === "string") imported[key] = result[key];
  }
  if (result.host_registration && typeof result.host_registration === "object") {
    imported.host_registration = {};
    for (const key of ["status", "note"]) {
      if (typeof result.host_registration[key] === "string") imported.host_registration[key] = result.host_registration[key];
    }
  }
  return imported;
}

function registerConnect(ctx, config) {
  ctx.tools.register({
    name: "tsunagou_connect",
    description: "Join or recover this DSH conversation in its current Tsunagou project. Identity and directory come from the host. Omit role to preserve an existing role or join as worker; request main only when the user explicitly selected it. An enrolled result still requires context__project_read in this conversation to verify readiness.",
    parameters: { type: "object", properties: { role: { type: "string", enum: ["worker", "main"] } }, additionalProperties: false },
    output: contentOutput,
    async execute(args, exec) { return toolResult(await runOnboarding(config, args, exec)); },
  });
  ctx.tools.register({
    name: "tsunagou_remote",
    description: "Cross-machine enrolment. action=whoami reports this conversation's own number, which the person on the host needs before they can invite this machine (only this conversation knows its id). action=import takes the invitation text the host sent and joins this conversation to that host's project; afterwards reload the window and verify with the project-read tool.",
    parameters: {
      type: "object",
      properties: {
        action: { type: "string", enum: ["whoami", "import"] },
        invite: { type: "string", description: "For action=import: the invitation text the host sent, exactly as sent." },
        machine: { type: "string", description: "Optional name for this machine; defaults to the machine's own name." },
      },
      required: ["action"],
      additionalProperties: false,
    },
    output: contentOutput,
    async execute(args, exec) { return toolResult(await runRemote(config, args, exec)); },
  });
}

function publicName(serverName, rawName) {
  const value = `mcp__${serverName}__${rawName}`.replace(/[^A-Za-z0-9_-]/g, "_");
  return value.length <= MAX_PUBLIC_NAME_LENGTH ? value : value.slice(0, MAX_PUBLIC_NAME_LENGTH);
}

function textOf(content, fallback) {
  if (!Array.isArray(content)) return fallback;
  const parts = content.filter((b) => b && b.type === "text").map((b) => String(b.text ?? ""));
  return parts.length ? parts.join("\n") : fallback;
}

/** Minimal newline-delimited JSON-RPC client over the bridge's stdio. */
function connect(command, args, environment, onStderr) {
  const child = spawn(command, args, {
    env: { ...process.env, ...environment },
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  const pending = new Map();
  let nextId = 1;
  let buffer = "";
  let closed;
  const close = (error) => {
    closed = closed ?? -1;
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(error);
    }
    pending.clear();
  };

  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    buffer += chunk;
    let index = buffer.indexOf("\n");
    while (index !== -1) {
      const line = buffer.slice(0, index).trim();
      buffer = buffer.slice(index + 1);
      index = buffer.indexOf("\n");
      if (!line) continue;
      let message;
      try { message = JSON.parse(line); } catch { continue; }
      if (message.id === undefined) continue;
      const entry = pending.get(message.id);
      if (!entry) continue;
      pending.delete(message.id);
      clearTimeout(entry.timer);
      if (message.error) entry.reject(new Error(`mcp_error:${message.error.code ?? ""}:${message.error.message ?? ""}`));
      else entry.resolve(message.result);
    }
  });
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => onStderr(String(chunk)));
  child.on("exit", (code) => {
    closed = code ?? -1;
    close(new Error(`mcp_transport_closed:${closed}`));
  });
  // A spawn that never produced a process (missing command, no permission) emits `error`
  // on the child and, with no listener, takes the whole host process down with it.
  child.on("error", () => close(new Error("mcp_spawn_failed")));
  child.stdin.on("error", () => close(new Error("mcp_transport_write_failed")));

  const send = (method, params) => new Promise((resolve, reject) => {
    if (closed !== undefined) {
      reject(new Error(`mcp_transport_closed:${closed}`));
      return;
    }
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("mcp_request_timeout"));
    }, 60_000);
    pending.set(id, { resolve, reject, timer });
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
  });
  const notify = (method, params) => child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
  const dispose = () => { try { child.kill(); } catch { /* already gone */ } };
  return { send, notify, dispose };
}

async function registerMcp(ctx, config) {
  const metaKey = (config.env && config.env.TSUNAGOU_HOST_META_KEY) || process.env.TSUNAGOU_HOST_META_KEY || DEFAULT_META_KEY;
  const serverName = config.serverName || "tsunagou";
  const logger = ctx.logger;
  const connection = connect(config.command, config.args ?? [], config.env ?? {}, (chunk) => {
    logger?.info?.(`tsunagou-provider(${serverName}): ${chunk.trim()}`);
  });
  ctx.effect(() => connection.dispose, "tsunagou-host-identity.connection");

  const initialized = await connection.send("initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "tsunagou-host-identity", version: "0.1.0" },
  });
  connection.notify("notifications/initialized", {});

  // The stock client publishes the server's initialization instructions as a prompt
  // section; that text is where Tsunagou tells an agent to read its inbox and what its
  // role may do. Dropping it silently removed those boundaries from the host.
  const instructions = typeof initialized?.instructions === "string" ? initialized.instructions.trim() : "";
  if (instructions) {
    ctx.inject(["systemPrompt"], (inner) => {
      inner.systemPrompt.section({
        name: `mcp:${serverName}`,
        order: inner.systemPrompt.getSectionOrder("MCP_SERVERS"),
        interpolate: false,
        text: () => instructions,
      });
    });
  }
  logger?.info?.(`tsunagou-provider(${serverName}): instructions ${instructions ? `${instructions.length} chars` : "absent"}`);

  const listed = await connection.send("tools/list", {});
  const tools = Array.isArray(listed?.tools) ? listed.tools : [];
  logger?.info?.(`tsunagou-provider(${serverName}): ${tools.length} tools, identity key ${metaKey}`);

  for (const tool of tools) {
    const rawName = String(tool.name);
    ctx.tools.register({
      name: publicName(serverName, rawName),
      description: typeof tool.description === "string" ? tool.description : "",
      parameters: tool.inputSchema ?? { type: "object", properties: {} },
      output: contentOutput,
      async execute(args, exec) {
        const identity = exec?.agent?.session?.id;
        if (typeof identity !== "string" || !identity) {
          // Never fall back to the overlay's shared credential: without a proven caller
          // the bridge must refuse rather than answer as whoever owns this file.
          throw new Error(`tsunagou_host_identity_unavailable:${rawName}`);
        }
        const result = await connection.send("tools/call", {
          name: rawName,
          arguments: args && typeof args === "object" ? args : {},
          _meta: { [metaKey]: identity },
        });
        const content = Array.isArray(result?.content) ? result.content : [];
        const text = textOf(content, `tool ${rawName} returned no text`);
        if (result?.isError === true) throw new Error(text);
        return {
          content,
          ...(result?.structuredContent !== undefined ? { structuredContent: result.structuredContent } : {}),
        };
      },
    });
  }
}

export async function apply(ctx, config) {
  // Keep the native onboarding action available even when the bridge cannot
  // start. Registering it after initialize made recovery depend on MCP working.
  if (config.connect) registerConnect(ctx, config);
  try {
    await registerMcp(ctx, config);
  } catch (error) {
    if (!config.connect) throw error;
    ctx.logger?.warn?.("tsunagou-provider: MCP unavailable; tsunagou_connect remains available. Repair the configured bridge and reload the plugin before verifying host readiness.");
  }
}
