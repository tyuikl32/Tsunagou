import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { createConnectPlugin } from "./connect.js";

async function tool(runtime) {
  let registered;
  await createConnectPlugin(runtime).setup({ tool: { transform: async (fn) => fn({ add(value) { registered = value; } }) } });
  return async (args, ctx = { sessionID: "real-session" }) => JSON.parse((await registered.execute(args, ctx)).content[0].text);
}

test("reject model arguments and unavailable identity before launching", async () => {
  const call = await tool({});
  for (const args of [{ identity: "other" }, { project: "elsewhere" }, [], null]) {
    assert.equal((await call(args)).error, "tsunagou_connect_invalid_arguments");
  }
  assert.equal((await call({}, {})).error, "tsunagou_host_identity_unavailable");
});

test("fixed CLI invocation receives host identity, sanitized env and UTF-8; result is allowlisted", async () => {
  const dir = mkdtempSync(join(tmpdir(), "tsunagou-中文 "));
  try {
    const script = join(dir, "cli.cjs");
    writeFileSync(script, `
      const assert = require('node:assert/strict');
      assert.deepEqual(process.argv.slice(2), ['agent','join','--adapter','opencode']);
      assert.equal(process.env.TSUNAGOU_HOST_CONVERSATION_ID, 'real-session');
      assert.equal(process.env.PYTHONIOENCODING, 'utf-8');
      for(const k of ['CODEX_THREAD_ID','DSH_SESSION_ID','OPENCODE_SESSION_ID','TSUNAGOU_PROJECT_ROOT']) assert.equal(process.env[k], undefined);
      console.log(JSON.stringify({status:'enrolled', project_id:'项目', agent_id:'agent', role:'main', secret:'NEVER ECHO', host_ready:true}));
    `);
    const call = await tool({ command: process.execPath, args: [script], env: {
      TSUNAGOU_HOST_CONVERSATION_ID: "fake", TSUNAGOU_PROJECT_ROOT: "wrong",
      CODEX_THREAD_ID: "fake", DSH_SESSION_ID: "fake", OPENCODE_SESSION_ID: "fake", PYTHONIOENCODING: "cp936",
    } });
    const result = await call({});
    assert.equal(result.status, "enrolled");
    assert.equal(result.project_id, "项目");
    assert.equal(result.host_ready, false);
    assert.equal(result.secret, undefined);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("raw process diagnostics and untrusted error text never reach the model", async () => {
  for (const source of [
    "console.error('PRIVATE'); console.log(JSON.stringify({error:'PRIVATE /path secret'})); process.exit(1)",
    "console.log(JSON.stringify({error:'enrollment_not_pending'})); process.exit(1)",
    "console.log('PRIVATE not json'); process.exit(1)",
  ]) {
    const call = await tool({ command: process.execPath, args: ["-e", source, "--"] });
    const result = await call({});
    assert.equal(result.status, "error");
    assert.ok(!JSON.stringify(result).includes("PRIVATE"));
    assert.equal(result.error, source.includes("enrollment_not_pending") ? "enrollment_not_pending" : "tsunagou_connect_failed");
  }
});
