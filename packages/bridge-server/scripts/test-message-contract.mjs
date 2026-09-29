import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

test("the running MCP lists the canonical message payload schemas", async () => {
  // An isolated transport with no real route/session: listTools needs no
  // daemon and must not refresh any user conversation in the background.
  const env = Object.fromEntries(Object.entries(process.env).filter(([name]) => !/^(TSUNAGOU_|CODEX_)/.test(name)));
  const transport = new StdioClientTransport({ command: process.execPath,
    args: [fileURLToPath(new URL("../dist/server.js", import.meta.url))], env, stderr: "pipe" });
  const client = new Client({ name: "message-schema-test", version: "0.1.0" }, { capabilities: {} });
  try {
    await client.connect(transport);
    const { tools } = await client.listTools();
    for (const name of ["message.send", "message.respond", "inbox.claim", "inbox.fetch", "inbox.presented", "inbox.ack"]) {
      const tool = tools.find((row) => row.name === name.replaceAll(".", "__"));
      assert.ok(tool, `${name} is missing`);
      const relative = `schemas/commands/${name.replaceAll(".", "/")}.schema.json`;
      const expected = JSON.parse(readFileSync(new URL(`../../../protocol/${relative}`, import.meta.url), "utf8"));
      const actual = structuredClone(tool.inputSchema);
      if (name === "message.send") {
        assert.equal(actual.properties.command_id.type, "string");
        assert.ok(!actual.required.includes("command_id"));
        delete actual.properties.command_id;
      }
      assert.deepEqual(actual, expected, `${name} diverged from the canonical schema`);
    }
  } finally {
    await client.close();
  }
});
