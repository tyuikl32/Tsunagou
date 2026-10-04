/** OpenCode 2.x host tool: identity comes only from the current execution context. */
import { execFile } from "node:child_process";
import { isAbsolute } from "node:path";

const failure = (error) => ({ status: "error", error, host_ready: false });

export function createConnectPlugin(runtime) {
  return {
    id: "tsunagou.connect",
    async setup(api) {
      await api.tool.transform((registry) => registry.add({
        name: "tsunagou_connect",
        description: "Join this conversation to the project and role selected in the Tsunagou console. After enrollment, call context__project_read through native MCP in this same conversation to verify readiness.",
        options: { codemode: false },
        input: { type: "object", properties: {}, additionalProperties: false },
        async execute(args, ctx) {
          const result = await join(runtime, args, ctx);
          return { content: [{ type: "text", text: JSON.stringify(result) }] };
        },
      }));
    },
  };
}

async function join(runtime, args, ctx) {
  if (!args || typeof args !== "object" || Array.isArray(args) || Object.keys(args).length) {
    return failure("tsunagou_connect_invalid_arguments");
  }
  const identity = ctx?.sessionID;
  if (typeof identity !== "string" || !identity.trim() || identity.includes("\0")) {
    return failure("tsunagou_host_identity_unavailable");
  }
  if (!runtime || typeof runtime.command !== "string" || !isAbsolute(runtime.command)
      || !Array.isArray(runtime.args) || runtime.args.some((arg) => typeof arg !== "string")) {
    return failure("tsunagou_runtime_not_configured");
  }
  const env = { ...process.env, ...runtime.env };
  for (const key of Object.keys(env)) {
    if (/^(?:TSUNAGOU_|CODEX_|DSH_|OPENCODE_)/i.test(key) || /^ZCODE_SESSION_ID$/i.test(key)) delete env[key];
  }
  env.TSUNAGOU_HOST_CONVERSATION_ID = identity;
  env.PYTHONIOENCODING = "utf-8";
  if (runtime.routingDir) env.TSUNAGOU_ROUTING_DIR = runtime.routingDir;
  return new Promise((resolve) => {
    execFile(runtime.command, [...runtime.args, "agent", "join", "--adapter", "opencode"],
      { env, encoding: "utf8", timeout: 120_000, maxBuffer: 1024 * 1024, windowsHide: true },
      (error, stdout) => {
        let value;
        for (const line of (stdout || "").trim().split(/\r?\n/).reverse()) {
          try { value = JSON.parse(line); break; } catch { /* CLI progress is not a receipt. */ }
        }
        if (error || value?.status !== "enrolled") {
          const code = typeof value?.error === "string" && /^[a-z][a-z0-9_]*(?::[a-z0-9_:]*)?$/.test(value.error)
            ? value.error : "tsunagou_connect_failed";
          resolve(failure(code));
          return;
        }
        if (!["project_id", "agent_id"].every((key) => typeof value[key] === "string" && value[key])
            || !["worker", "main"].includes(value.role)) {
          resolve(failure("tsunagou_connect_invalid_receipt"));
          return;
        }
        resolve({ status: "enrolled", host_ready: false, project_id: value.project_id,
          agent_id: value.agent_id, role: value.role,
          next: "Call context__project_read through native MCP in this conversation; verify project, Agent and ready status." });
      });
  });
}
