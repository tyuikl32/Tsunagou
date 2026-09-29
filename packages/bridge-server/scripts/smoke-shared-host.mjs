// Runs against the real daemon prepared by test_onboarding_connect.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const config = JSON.parse(readFileSync(process.argv[2], "utf8"));
const identities = process.argv.slice(3).map((path) => JSON.parse(readFileSync(path, "utf8")));
const start = async (extraEnv = {}) => {
  const transport = new StdioClientTransport({ command: config.command, args: config.args,
    env: { ...process.env, ...config.env, ...extraEnv }, stderr: "pipe" });
  const client = new Client({ name: "shared-host-test", version: "0.1.0" }, { capabilities: {} });
  await client.connect(transport);
  return client;
};
const context = async (client, identity, args = {}) => {
  const result = await client.callTool({ name: "context__project_read", arguments: args,
    ...(identity ? { _meta: { threadId: identity.conversation_id } } : {}),
  });
  return { ...JSON.parse(result.content.find((item) => item.type === "text").text), failed: result.isError === true };
};
let client = await start();
try {
  const initial = await Promise.all(identities.map((identity) => context(client, identity)));
  assert.ok(initial.every((row) => !row.failed));
  assert.equal(new Set(initial.map((row) => row.agent_id)).size, identities.length);
  const missing = await context(client, undefined);
  assert.equal(missing.error, "host_request_identity_required");
  const unbound = await context(client, { conversation_id: "unregistered-host-fixture" });
  assert.equal(unbound.error, "not_enrolled:run_agent_connect");
  const bodySpoof = await context(client, identities[0], { conversation_id: identities[1].conversation_id });
  assert.equal(bodySpoof.failed, true);
  const attempts = await Promise.all(Array.from({ length: 20 }, (_, i) => context(client, identities[i % identities.length])));
  attempts.forEach((row, i) => {
    assert.equal(row.agent_id, initial[i % identities.length].agent_id);
    assert.deepEqual(row.session, initial[i % identities.length].session);
  });
  await client.close();
  client = await start();
  const restarted = await Promise.all(identities.map((identity) => context(client, identity)));
  restarted.forEach((row, i) => assert.deepEqual(row.session, initial[i].session));
  await client.close();
  // A restarted Desktop changes its pipe. Without any Worker call, the shared
  // bridge must refresh already-enrolled bindings so they can be woken.
  const nextEndpoint = "fixture-restarted-desktop-pipe";
  const generation = createHash("sha256").update(nextEndpoint).digest("hex");
  client = await start({ CODEX_APP_TOOLS_PIPE_PATH: nextEndpoint });
  const sessionFiles = process.argv.slice(3).map((path) => join(dirname(path), "bridge-session.json"));
  const deadline = Date.now() + 15000;
  while (!sessionFiles.every((path) => JSON.parse(readFileSync(path, "utf8")).host_binding_generation === generation)) {
    assert.ok(Date.now() < deadline, "background binding refresh did not finish");
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  const refreshed = await Promise.all(identities.map((identity) => context(client, identity)));
  refreshed.forEach((row, i) => {
    assert.equal(row.agent_id, initial[i].agent_id);
    assert.equal(row.session.connection_epoch, initial[i].session.connection_epoch + 1);
    assert.equal(row.host_binding.connection_epoch, row.session.connection_epoch);
  });
  process.stdout.write(JSON.stringify({ status: "passed", distinct_agents: identities.length,
    same_process_calls: attempts.length, restart_preserved_sessions: true, desktop_generation_restored_without_worker_call: true,
    contexts: initial.map(({ agent_id, role, session, host_binding }) => ({ agent_id, role, session, host_binding })),
  }) + "\n");
} finally {
  await client.close().catch(() => {});
}
