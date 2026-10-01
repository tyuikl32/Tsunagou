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

export const name = "tsunagou-host-identity";
export const inject = ["tools"];

/** DeepSeek function-name contract from the stock client: at most 64 characters. */
const MAX_PUBLIC_NAME_LENGTH = 64;
const DEFAULT_META_KEY = "tsunagou.hostSessionId";

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
      if (message.error) entry.reject(new Error(`mcp_error:${message.error.code ?? ""}:${message.error.message ?? ""}`));
      else entry.resolve(message.result);
    }
  });
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => onStderr(String(chunk)));
  child.on("exit", (code) => {
    closed = code ?? -1;
    for (const [, entry] of pending) entry.reject(new Error(`mcp_transport_closed:${closed}`));
    pending.clear();
  });
  // A spawn that never produced a process (missing command, no permission) emits `error`
  // on the child and, with no listener, takes the whole host process down with it.
  child.on("error", (error) => {
    closed = closed ?? -1;
    const detail = String(error && error.message ? error.message : error);
    for (const [, entry] of pending) entry.reject(new Error(`mcp_spawn_failed:${detail}`));
    pending.clear();
  });

  const send = (method, params) => new Promise((resolve, reject) => {
    if (closed !== undefined) {
      reject(new Error(`mcp_transport_closed:${closed}`));
      return;
    }
    const id = nextId++;
    pending.set(id, { resolve, reject });
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
  });
  const notify = (method, params) => child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
  const dispose = () => { try { child.kill(); } catch { /* already gone */ } };
  return { send, notify, dispose };
}

export async function apply(ctx, config) {
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
      output: {
        schema: {
          type: "object",
          properties: { content: { type: "array", items: {} } },
          required: ["content"],
          additionalProperties: false,
        },
        render(_args, value) { return value.content; },
      },
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
