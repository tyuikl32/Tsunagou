import { createServer } from "node:http";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const root = await mkdtemp(join(tmpdir(), "tsunagou-late-ticket-"));
const stateDir = join(root, "bridge-state");
const ticketFile = join(root, "ticket.json");
const sessionFile = join(root, "session.json");
await mkdir(stateDir, { recursive: true });

const credential = {
  agent_id: "late-agent",
  session_id: "late-session",
  connection_epoch: 1,
  secret_token: "late-secret",
  reconnect_nonce: "late-nonce",
  baseline_status: "ready",
};
const http = createServer(async (request, response) => {
  let body = "";
  for await (const chunk of request) body += chunk;
  response.setHeader("content-type", "application/json");
  if (request.url === "/api/v1/commands/agent.enroll") {
    response.end(JSON.stringify({ result: credential }));
    return;
  }
  if (request.url === "/api/v1/commands/context.project_read") {
    if (request.headers.authorization !== `Bearer ${credential.secret_token}`) {
      response.statusCode = 401;
      response.end(JSON.stringify({ detail: { code: "authentication_failed" } }));
      return;
    }
    response.end(JSON.stringify({ result: {
      project_id: "late-project", agent_id: credential.agent_id, role: "worker",
      main_agent_id: null, scope: { capabilities: [] }, tasks: [],
    } }));
    return;
  }
  response.statusCode = 404;
  response.end(JSON.stringify({ detail: { code: "not_found" } }));
});
await new Promise((resolveReady) => http.listen(0, "127.0.0.1", resolveReady));
const port = http.address().port;
const bridge = resolve("packages/bridge-server/dist/server.js");
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [bridge],
  env: {
    ...process.env,
    TSUNAGOU_HTTP_URL: `http://127.0.0.1:${port}`,
    TSUNAGOU_DAEMON_STATE_DIR: join(root, "missing-daemon-state"),
    TSUNAGOU_TICKET_FILE: ticketFile,
    TSUNAGOU_SESSION_FILE: sessionFile,
    TSUNAGOU_PROJECT_ROOT: root,
    TSUNAGOU_STATE_DIR: stateDir,
    TSUNAGOU_HOST_ID_ENV: "TSUNAGOU_TEST_HOST_ID",
    TSUNAGOU_TEST_HOST_ID: "late-host",
  },
  stderr: "pipe",
});
const client = new Client({ name: "late-ticket-smoke", version: "0.1.0" }, { capabilities: {} });
try {
  await client.connect(transport);
  await writeFile(ticketFile, JSON.stringify({
    installation_id: "late-installation",
    conversation_id: "late-conversation",
    secret: "late-ticket-secret",
  }) + "\n", "utf-8");
  const result = await client.callTool({ name: "context__project_read", arguments: {} });
  if (result.isError) throw new Error(result.content?.[0]?.text ?? "late_recovery_failed");
  const text = result.content?.find((item) => item.type === "text")?.text;
  const value = JSON.parse(text);
  if (value.agent_id !== credential.agent_id) throw new Error("late_identity_missing");
  process.stdout.write(JSON.stringify({ status: "passed", late_ticket_recovery: true, agent_id: value.agent_id }) + "\n");
} finally {
  await client.close().catch(() => {});
  await http.close();
  await rm(root, { recursive: true, force: true });
}
