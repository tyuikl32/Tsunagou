#!/usr/bin/env node
/**
 * Minimal local caller for the Tsunagou wake plugin.
 *
 * This is a verification client, not a framework:
 *   - it reads the endpoint and bearer key from the environment,
 *   - it never reads or prints the key,
 *   - it sends only the documented identity fields.
 *
 * Usage:
 *   TSUNAGOU_WAKE_URL=http://127.0.0.1:19387 \
 *   TSUNAGOU_WAKE_KEY=<secret> \
 *   node example/client.mjs status --project-id P --agent-id A --session-id S
 *
 *   TSUNAGOU_WAKE_URL=http://127.0.0.1:19387 \
 *   TSUNAGOU_WAKE_KEY=<secret> \
 *   node example/client.mjs wake --project-id P --agent-id A --session-id S --message-id M
 *
 * Exit codes: 0 accepted/reported, 1 refused by the plugin, 2 usage/config error.
 */

const NAME = "[tsunagou-wake-example]";

/** Read one `--flag value` pair. */
function flag(args, name) {
  const at = args.indexOf(`--${name}`);
  if (at === -1) return undefined;
  const value = args[at + 1];
  return value === undefined || value.startsWith("--") ? undefined : value;
}

function usage(message) {
  process.stderr.write(`${NAME} ${message}\n`);
  process.stderr.write(`${NAME} usage: client.mjs <status|wake> --project-id P --agent-id A --session-id S [--message-id M]\n`);
  process.stderr.write(`${NAME} env: TSUNAGOU_WAKE_URL (e.g. http://127.0.0.1:19387), TSUNAGOU_WAKE_KEY\n`);
  process.exit(2);
}

const [command, ...args] = process.argv.slice(2);
if (command !== "status" && command !== "wake") usage("first argument must be status or wake");

const baseUrl = process.env.TSUNAGOU_WAKE_URL;
const secret = process.env.TSUNAGOU_WAKE_KEY;
if (typeof baseUrl !== "string" || baseUrl.length === 0) usage("TSUNAGOU_WAKE_URL is not set");
if (typeof secret !== "string" || secret.length === 0) usage("TSUNAGOU_WAKE_KEY is not set");

let origin;
try {
  origin = new URL(baseUrl);
} catch {
  usage(`TSUNAGOU_WAKE_URL is not a URL: ${baseUrl}`);
}
// The plugin only serves loopback; refuse to send the key anywhere else.
if (origin.protocol !== "http:" || origin.username || origin.password
  || (origin.hostname !== "127.0.0.1" && origin.hostname !== "[::1]")) {
  usage(`refusing to send the key to non-loopback host ${origin.hostname}`);
}

const ids = {
  project_id: flag(args, "project-id"),
  agent_id: flag(args, "agent-id"),
  session_id: flag(args, "session-id"),
};
for (const [key, value] of Object.entries(ids)) {
  if (value === undefined) usage(`--${key.replaceAll("_", "-")} is required`);
}
if (command === "wake") {
  ids.message_id = flag(args, "message-id");
  if (ids.message_id === undefined) usage("--message-id is required for wake");
}

const path = command === "status" ? "/tsunagou/wake/status" : "/tsunagou/wake";
const url = new URL(path, origin);

let response;
try {
  response = await fetch(url, {
    method: "POST",
    redirect: "error",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${secret}`,
    },
    body: JSON.stringify(ids),
    signal: AbortSignal.timeout(40_000),
  });
} catch (error) {
  // No result: never reported as success, and the same message id stays valid
  // for a retry.
  process.stdout.write(`${JSON.stringify({ ok: false, error: "transport_failed", reason: String(error?.message ?? error) })}\n`);
  process.exit(1);
}

const text = await response.text();
let payload;
try {
  payload = JSON.parse(text);
} catch {
  payload = { ok: false, error: "unreadable_response", status: response.status };
}
process.stdout.write(`${JSON.stringify({ http_status: response.status, ...payload })}\n`);

if (response.ok && payload.ok === true) {
  if (command === "wake") {
    // `accepted` means admitted (or already admitted under this request id).
    // It does not mean a turn started or that any work completed.
    process.stderr.write(`${NAME} accepted request_id=${payload.request_id}; verify execution through the session log, not through this call.\n`);
  }
  process.exit(0);
}
process.exit(1);
