// CLI bootstrap verifier. This is not evidence that the original host has
// loaded MCP; connect reports that final host-context check separately.
import { readFileSync } from "node:fs";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const config = JSON.parse(readFileSync(process.argv[2], "utf8"));
const request = process.argv[3] ? JSON.parse(readFileSync(process.argv[3], "utf8")) : undefined;
const transport = new StdioClientTransport({
  command: config.command, args: config.args, env: { ...process.env, ...config.env }, stderr: "pipe",
});
const client = new Client({ name: "tsunagou-connect", version: "0.1.0" }, { capabilities: {} });
try {
  await client.connect(transport);
  const result = await client.callTool({ name: "context__project_read", arguments: {},
    ...(request ? { _meta: { threadId: request.conversation_id } } : {}),
  });
  const value = JSON.parse(result.content.find((item) => item.type === "text").text);
  if (result.isError) {
    process.stdout.write(JSON.stringify({ status: "error", error: value.error }) + "\n");
    process.exitCode = 1;
  } else {
    process.stdout.write(JSON.stringify({ project_id: value.project_id, agent_id: value.agent_id, role: value.role,
      session: value.session, host_binding: value.host_binding }) + "\n");
  }
} catch {
  process.stdout.write(JSON.stringify({ status: "error", error: "bridge_bootstrap_failed" }) + "\n");
  process.exitCode = 1;
} finally {
  await client.close().catch(() => {});
}
