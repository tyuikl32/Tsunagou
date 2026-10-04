import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { apply } from "../index.js";

const bridge = String.raw`
  let text = '';
  process.stdin.on('data', chunk => {
    text += chunk;
    let at;
    while ((at = text.indexOf('\n')) !== -1) {
      const request = JSON.parse(text.slice(0, at));
      text = text.slice(at + 1);
      if (request.id === undefined) continue;
      const result = request.method === 'initialize'
        ? { instructions: 'Preserve the project and role boundary.' }
        : request.method === 'tools/list'
        ? { tools: [{ name: 'context__project_read', inputSchema: { type: 'object' } }] }
        : { content: [{ type: 'text', text: JSON.stringify(request.params._meta) }] };
      process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: request.id, result }) + '\n');
    }
  });
`;

function host(t) {
  const root = mkdtempSync(join(tmpdir(), "tsunagou-provider-test-"));
  const tools = new Map();
  const sections = [];
  const disposers = [];
  const warnings = [];
  const ctx = {
    tools: { register(tool) { tools.set(tool.name, tool); } },
    effect(callback) { disposers.push(callback()); },
    inject(_services, callback) { callback({ systemPrompt: {
      getSectionOrder() { return 10; }, section(value) { sections.push(value); },
    } }); },
    logger: { info() {}, warn(value) { warnings.push(value); } },
  };
  t.after(() => { for (const dispose of disposers) dispose(); rmSync(root, { recursive: true, force: true }); });
  const exec = { agent: { session: { id: "fixture-original", header: { cwd: root } } } };
  const config = { command: process.execPath, args: ["-e", bridge],
    env: { TSUNAGOU_HOST_META_KEY: "tsunagou.hostSessionId", TSUNAGOU_ROUTING_DIR: join(root, "routes") } };
  const value = (result) => JSON.parse(result.content[0].text);
  return { root, tools, ctx, exec, config, sections, warnings, value };
}

test("legacy provider preserves MCP instructions and reads the current caller on every tool call", async (t) => {
  const f = host(t);
  await apply(f.ctx, f.config);
  assert.equal(f.tools.has("tsunagou_connect"), false);
  assert.equal(f.sections[0].text(), "Preserve the project and role boundary.");
  const tool = f.tools.get("mcp__tsunagou__context__project_read");
  assert.deepEqual(f.value(await tool.execute({}, f.exec)), { "tsunagou.hostSessionId": "fixture-original" });
  const fork = { agent: { session: { id: "fixture-fork", header: { cwd: f.root } } } };
  assert.deepEqual(f.value(await tool.execute({}, fork)), { "tsunagou.hostSessionId": "fixture-fork" });
  await assert.rejects(tool.execute({}, {}), /tsunagou_host_identity_unavailable/);
});

test("native connect uses trusted session/cwd, cleans stale host state and never reports helper readiness", async (t) => {
  const f = host(t);
  const cli = `
    const assert = require('node:assert/strict');
    assert.equal(process.cwd(), ${JSON.stringify(f.root)});
    assert.equal(process.env.DSH_SESSION_ID, 'fixture-original');
    assert.equal(process.env.TSUNAGOU_ROUTING_DIR, ${JSON.stringify(f.config.env.TSUNAGOU_ROUTING_DIR)});
    assert.equal(process.env.CODEX_THREAD_ID, undefined);
    assert.equal(process.env.TSUNAGOU_HOST_CONVERSATION_ID, undefined);
    assert.equal(process.env.TSUNAGOU_CONTROL_TOKEN, undefined);
    const args = process.argv.slice(1);
    if (args[1] === 'pending') {
      assert.deepEqual(args, ['agent', 'pending', '--adapter', 'deepseek']);
      console.log(JSON.stringify({status:'none'}));
      process.exit(0);
    }
    assert.deepEqual(args.slice(0, 7), ['agent', 'connect', '--adapter', 'deepseek', '--profile', 'desktop', '--no-register-host']);
    const role = args.includes('--role') ? args[args.indexOf('--role') + 1] : 'worker';
    console.log(JSON.stringify({status:'enrolled', project_id:'fixture-project', agent_id:'fixture-agent', role,
      session:{status:'ready',baseline_status:'ready',connection_epoch:3,secret_token:'hidden-token'},
      secret_token:'hidden-token',conversation_id:'hidden-session',bridge_config:'hidden-path'}));
  `;
  f.config.connect = { command: process.execPath, args: ["-e", cli, "--"],
    env: { CODEX_THREAD_ID: "stale-codex", TSUNAGOU_HOST_CONVERSATION_ID: "stale-session", TSUNAGOU_CONTROL_TOKEN: "hidden-token" } };
  await apply(f.ctx, f.config);
  assert.equal(f.tools.size, 3);
  const tool = f.tools.get("tsunagou_connect");
  for (const role of [undefined, "worker", "main"]) {
    const result = await tool.execute(role ? { role } : {}, f.exec);
    const value = f.value(result);
    assert.equal(value.status, "enrolled");
    assert.equal(value.host_ready, false);
    assert.equal(value.role, role ?? "worker");
    assert.equal(value.session.connection_epoch, 3);
    assert.match(value.next, /mcp__tsunagou__context__project_read/);
    assert.ok(!JSON.stringify(result).includes("hidden-"));
  }
});

test("native connect carries the CLI's pending project across an unrelated chat cwd", async (t) => {
  const f = host(t);
  const selected = join(f.root, "selected-project");
  const enrollment = "0123456789abcdef0123456789abcdef";
  f.config.connect = { command: process.execPath, args: ["-e", `
    const assert = require('node:assert/strict');
    assert.equal(process.cwd(), ${JSON.stringify(f.root)});
    assert.equal(process.env.DSH_SESSION_ID, 'fixture-original');
    const args = process.argv.slice(1);
    if (args[1] === 'pending') {
      console.log(JSON.stringify({status:'pending',state:'pending',adapter:'deepseek',
        project_id:'selected-project',project_root:${JSON.stringify(selected)},enrollment_id:${JSON.stringify(enrollment)}}));
    } else {
      assert.deepEqual(args, ['--project-root', ${JSON.stringify(selected)}, 'agent', 'connect', '--adapter',
        'deepseek', '--profile', 'desktop', '--no-register-host', '--pending-enrollment-id', ${JSON.stringify(enrollment)}]);
      console.log(JSON.stringify({status:'enrolled',project_id:'selected-project',agent_id:'fixture-agent',role:'worker'}));
    }
  `, "--"] };
  await apply(f.ctx, f.config);
  const result = f.value(await f.tools.get("tsunagou_connect").execute({}, f.exec));
  assert.equal(result.project_id, "selected-project");
  assert.equal(result.status, "enrolled");
});

test("native connect preserves Unicode paths through real Python CLI pipes under CP936", async (t) => {
  const probe = spawnSync("python", ["-c", "import sys; print(sys.executable)"], { encoding: "utf8" });
  assert.equal(probe.status, 0, "Python is required for the CLI encoding regression");
  const python = probe.stdout.trim();
  for (const dirname of ["selected-project", "中文项目", "中文 project with spaces"]) {
    await t.test(dirname, async (t) => {
      const f = host(t);
      const selected = join(f.root, dirname);
      const literal = JSON.stringify(selected).replace(/[^\x00-\x7f]/g,
        (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
      const cli = `
import json, sys
selected = ${literal}
args = sys.argv[1:]
if args == ['agent', 'pending', '--adapter', 'deepseek']:
    result = dict(status='pending', state='pending', adapter='deepseek',
                  project_id='selected-project', project_root=selected, enrollment_id='a' * 32)
elif args == ['--project-root', selected, 'agent', 'connect', '--adapter', 'deepseek',
              '--profile', 'desktop', '--no-register-host', '--pending-enrollment-id', 'a' * 32]:
    result = dict(status='enrolled', project_id='selected-project', agent_id='fixture-agent', role='worker')
else:
    print(json.dumps(dict(status='error', error='onboarding_project_mismatch')))
    sys.exit(4)
print(json.dumps(result, ensure_ascii=False))
`;
      f.config.connect = { command: python, args: ["-c", cli],
        env: { PYTHONIOENCODING: "cp936", PYTHONUTF8: "0" } };
      await apply(f.ctx, f.config);
      const result = f.value(await f.tools.get("tsunagou_connect").execute({}, f.exec));
      assert.equal(result.status, "enrolled", JSON.stringify(result));
      assert.equal(result.project_id, "selected-project");
      assert.equal(result.host_ready, false);
    });
  }
});

test("native connect fails closed for malformed pending selection and mismatched receipts", async (t) => {
  const f = host(t);
  f.config.connect = { command: process.execPath, args: ["-e", "", "--"] };
  await apply(f.ctx, f.config);
  const tool = f.tools.get("tsunagou_connect");
  for (const selection of [undefined, {status:'pending',state:'pending',project_root:'relative'},
    {status:'pending',state:'pending',adapter:'codex',project_root:f.root,project_id:'p',enrollment_id:'a'.repeat(32)}]) {
    f.config.connect.args[1] = `console.log(${JSON.stringify(JSON.stringify(selection ?? {}))})`;
    assert.match(f.value(await tool.execute({}, f.exec)).error, /tsunagou_connect_(?:pending_failed|invalid_selection)/);
  }
  f.config.connect.args[1] = `
    if (process.argv[2] === 'pending') {
      console.log(JSON.stringify({status:'pending',state:'pending',adapter:'deepseek',project_root:${JSON.stringify(f.root)},
        project_id:'expected-project',enrollment_id:'a'.repeat(32)}));
    } else {
      console.log(JSON.stringify({status:'enrolled',project_id:'wrong-project',agent_id:'a',role:'worker'}));
    }
  `;
  assert.equal(f.value(await tool.execute({}, f.exec)).error, "onboarding_project_mismatch");
  for (const state of ["claimed", "enrolled"]) {
    f.config.connect.args[1] = `
      const assert = require('node:assert/strict');
      assert.equal(process.argv[2], 'pending');
      console.log(JSON.stringify({status:'pending',state:${JSON.stringify(state)},adapter:'deepseek',
        project_root:${JSON.stringify(f.root)},project_id:'expected-project',enrollment_id:'a'.repeat(32)}));
    `;
    assert.equal(f.value(await tool.execute({}, f.exec)).error, "enrollment_not_pending");
  }
});

test("native connect rejects model identity, commands, unknown fields and missing host context before spawn", async (t) => {
  const f = host(t);
  f.config.connect = { command: process.execPath, args: ["-e", "process.exit(99)", "--"] };
  await apply(f.ctx, f.config);
  const tool = f.tools.get("tsunagou_connect");
  for (const args of [{ role: "user" }, { role: null }, { session_id: "forged" }, { cwd: f.root },
    { command: "arbitrary" }, { env: {} }, { token: "hidden-token" }, [], null]) {
    const value = f.value(await tool.execute(args, f.exec));
    assert.equal(value.error, "tsunagou_connect_invalid_arguments");
    assert.equal(value.exit_code, undefined);
  }
  assert.equal(f.value(await tool.execute({}, {})).error, "tsunagou_host_identity_unavailable");
  const missingCwd = { agent: { session: { id: "fixture-original" } } };
  assert.equal(f.value(await tool.execute({}, missingCwd)).error, "tsunagou_project_directory_unavailable");
});

test("native connect remains usable when MCP cannot spawn and returns sanitized CLI failures", async (t) => {
  const f = host(t);
  f.config.command = join(f.root, "missing-bridge-executable");
  f.config.connect = { command: process.execPath, args: ["-e", "console.log(JSON.stringify({status:'error',error:'daemon_launch_failed',secret_token:'hidden-token'})); process.exit(4)", "--"] };
  await apply(f.ctx, f.config);
  assert.equal(f.warnings.length, 1);
  assert.equal(f.tools.size, 2);
  const tool = f.tools.get("tsunagou_connect");
  const failed = f.value(await tool.execute({}, f.exec));
  assert.equal(failed.error, "daemon_launch_failed");
  assert.equal(failed.exit_code, 4);
  assert.ok(!JSON.stringify(failed).includes("hidden-token"));
  f.config.connect.command = join(f.root, "missing-cli-executable");
  assert.equal(f.value(await tool.execute({}, f.exec)).error, "tsunagou_connect_spawn_failed");
});

test("native connect bounds a stalled CLI without claiming enrollment", async (t) => {
  const f = host(t);
  f.config.connect = { command: process.execPath, args: ["-e", "setInterval(() => {}, 1000)", "--"] };
  await apply(f.ctx, f.config);
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const pending = f.tools.get("tsunagou_connect").execute({}, f.exec);
  t.mock.timers.tick(120_000);
  const timedOut = f.value(await pending);
  assert.equal(timedOut.error, "tsunagou_connect_timeout");
  assert.equal(timedOut.host_ready, false);
});

test("cross-machine tool reports this conversation's number with the host identity", async (t) => {
  const f = host(t);
  const cli = `
    const assert = require('node:assert/strict');
    assert.equal(process.env.DSH_SESSION_ID, 'fixture-original');
    assert.equal(process.env.TSUNAGOU_CONTROL_TOKEN, undefined);
    const args = process.argv.slice(1);
    assert.deepEqual(args, ['agent', 'whoami', '--adapter', 'deepseek']);
    console.log(JSON.stringify({status:'ok', adapter:'deepseek', conversation_id:'fixture-original',
      next:'send it to the host', secret_token:'hidden-token'}));
  `;
  f.config.connect = { command: process.execPath, args: ["-e", cli, "--"],
    env: { TSUNAGOU_CONTROL_TOKEN: "hidden-token" } };
  await apply(f.ctx, f.config);

  const tool = f.tools.get("tsunagou_remote");
  const result = await tool.execute({ action: "whoami" }, f.exec);
  const value = f.value(result);
  assert.equal(value.status, "ok");
  assert.equal(value.conversation_id, "fixture-original");
  assert.ok(!JSON.stringify(result).includes("hidden-token"));
  assert.ok(!JSON.stringify(result).includes("secret_token"));
});

test("cross-machine import passes the invitation to the CLI and never echoes it back", async (t) => {
  const f = host(t);
  const invite = "tsunagou-invite-v1:fixture-ticket";
  const cli = `
    const assert = require('node:assert/strict');
    const args = process.argv.slice(1);
    assert.deepEqual(args, ['agent', 'import', ${JSON.stringify(invite)}, '--workdir', ${JSON.stringify(f.root)}, '--machine', 'workstation-7']);
    console.log(JSON.stringify({status:'imported', project_id:'fixture-project', adapter:'deepseek',
      role:'worker', url:'http://10.0.0.5:2810', workspace:process.cwd(),
      host_registration:{status:'registered',note:'ok',receipt_file:'hidden-path'},
      secret_token:'hidden-token', next:'reload'}));
  `;
  f.config.connect = { command: process.execPath, args: ["-e", cli, "--"] };
  await apply(f.ctx, f.config);

  const tool = f.tools.get("tsunagou_remote");
  const result = await tool.execute({ action: "import", invite, machine: "workstation-7" }, f.exec);
  const value = f.value(result);
  assert.equal(value.status, "imported");
  assert.equal(value.project_id, "fixture-project");
  assert.equal(value.url, "http://10.0.0.5:2810");
  assert.deepEqual(Object.keys(value.host_registration).sort(), ["note", "status"]);
  const text = JSON.stringify(result);
  assert.ok(!text.includes(invite), "邀请是机密：不能把它回显进会话");
  assert.ok(!text.includes("hidden-token") && !text.includes("hidden-path"));
});

test("cross-machine tool refuses bad arguments and sanitizes CLI failures", async (t) => {
  const f = host(t);
  f.config.connect = { command: process.execPath,
    args: ["-e", "console.log(JSON.stringify({status:'error',error:'invite_expired',secret_token:'hidden-token'})); process.exit(4)", "--"] };
  await apply(f.ctx, f.config);
  const tool = f.tools.get("tsunagou_remote");

  for (const args of [{}, { action: "join" }, { action: "import" }, { action: "import", invite: "   " },
    { action: "whoami", token: "hidden-token" }, { action: "import", invite: "x".repeat(9000) }, [], null]) {
    const value = f.value(await tool.execute(args, f.exec));
    assert.equal(value.status, "error");
    assert.match(value.error, /^tsunagou_remote_/);
  }
  const failed = f.value(await tool.execute({ action: "whoami" }, f.exec));
  assert.equal(failed.error, "invite_expired");
  assert.equal(failed.exit_code, 4);
  assert.ok(!JSON.stringify(failed).includes("hidden-token"));
  assert.equal(f.value(await tool.execute({ action: "whoami" }, {})).error, "tsunagou_host_identity_unavailable");
});
