import { readFile, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import process from "node:process";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

function option(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || process.argv[index + 1] === undefined) throw new Error(`missing:${name}`);
  return process.argv[index + 1];
}

async function readConfig(path) {
  return JSON.parse(await readFile(resolve(path), "utf-8"));
}

async function connect(config, name) {
  const transport = new StdioClientTransport({
    command: config.command,
    args: config.args,
    env: config.env,
    cwd: config.cwd,
    stderr: "pipe",
  });
  const client = new Client({ name: `tsunagou-${name}-smoke`, version: "0.1.0" }, { capabilities: {} });
  await client.connect(transport);
  return { client, transport };
}

function parseTool(result) {
  if (result.isError) {
    const text = result.content?.find((item) => item.type === "text")?.text ?? "unknown_tool_error";
    throw new Error(text);
  }
  const text = result.content?.find((item) => item.type === "text")?.text;
  if (text === undefined) throw new Error("tool_result_without_text");
  return JSON.parse(text);
}

async function call(client, name, args = {}) {
  return parseTool(await client.callTool({ name, arguments: args }));
}

async function expectError(client, name, args, code) {
  const result = await client.callTool({ name, arguments: args });
  if (!result.isError) throw new Error(`expected_error:${name}`);
  const text = result.content?.find((item) => item.type === "text")?.text ?? "";
  if (!text.includes(code)) throw new Error(`wrong_error:${name}:${text}`);
}

class ContextOnly extends Error {}
class StopAfterStart extends Error {}

const projectRoot = resolve(option("--project-root"));
const mainConfig = await readConfig(option("--main-config"));
const workerConfig = await readConfig(option("--worker-config"));
const main = await connect(mainConfig, "main");
const worker = await connect(workerConfig, "worker");

try {
  const mainContext = await call(main.client, "context__project_read");
  const workerContext = await call(worker.client, "context__project_read");
  if (process.argv.includes("--context-only")) {
    process.stdout.write(JSON.stringify({ main: mainContext, worker: workerContext }, null, 2) + "\n");
    throw new ContextOnly();
  }
  if (process.argv.includes("--stale-check")) {
    await expectError(worker.client, "task__progress", {
      task_id: option("--task-id"),
      attempt_id: option("--attempt-id"),
      summary: "stale execution probe",
    }, "capability_denied");
    process.stdout.write(JSON.stringify({ status: "passed", stale_execution: "rejected" }) + "\n");
    throw new ContextOnly();
  }
  if (mainContext.role !== "main" || workerContext.role === "main") throw new Error("role_boundary_missing");

  const task = await call(main.client, "task__create", {
    title: "bridge smoke",
    objective: "write one file",
    execution_scope: {
      digest: "bridge-smoke-scope",
      resources: [{ kind: "path", root_id: "project", segments: [], mode: "exclusive_write" }],
    },
  });
  const workFile = `bridge-demo-${task.task_id}.mjs`;
  const userFile = `user-edit-${task.task_id}.txt`;
  await call(main.client, "task__ready", { task_id: task.task_id });
  await call(main.client, "task__publish", { task_id: task.task_id });
  const claimed = await call(worker.client, "task__claim", { task_id: task.task_id });
  await expectError(main.client, "task__submit", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    summary: "foreign submit probe",
  }, "capability_denied");

  const selection = await call(main.client, "workspace__select", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    driver_kind: "shared",
    evidence_refs: ["bridge-smoke:shared"],
    hard_constraints: [],
    input_digest: "bridge-smoke",
  });
  const intent = await call(worker.client, "resource__intent", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    reason: "bridge smoke",
    scope_digest: "bridge-smoke-scope",
    resources: [{ kind: "path", root_id: "project", segments: [workFile], mode: "exclusive_write" }],
  });
  const lease = await call(worker.client, "resource__acquire", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    intent_id: intent.intent_id,
    intent_revision: intent.revision,
    scope_digest: "bridge-smoke-scope",
  });

  await call(worker.client, "cognition__report", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    claims: [{ subject_key: "workspace.driver", claim_type: "literal", equality_key: "workspace.driver", value: "shared" }],
    assumptions: ["same project root"],
    uncertainties: [],
  });
  await call(main.client, "cognition__report", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    claims: [{ subject_key: "workspace.driver", claim_type: "literal", equality_key: "workspace.driver", value: "worktree" }],
    assumptions: [],
    uncertainties: ["worker may require shared"],
  });

  const contract = await call(main.client, "contract__propose", {
    payload: { task_id: task.task_id, driver: "shared" },
    participants_required: [
      { slot: "worker", agent_id: workerContext.agent_id },
      { slot: "main", agent_id: mainContext.agent_id },
    ],
  });
  await call(worker.client, "contract__accept", {
    proposal_id: contract.proposal_id,
    participant_slot: "worker",
    proposal_digest: contract.digest,
  });
  await call(main.client, "contract__accept", {
    proposal_id: contract.proposal_id,
    participant_slot: "main",
    proposal_digest: contract.digest,
  });

  const message = await call(worker.client, "message__send", {
    recipient_agent_id: mainContext.agent_id,
    kind: "bridge.smoke",
    subject_ref: task.task_id,
    summary: "worker is ready",
    payload: { attempt_id: claimed.attempt_id },
    response_contract: {
      required: true,
      schema: {
        type: "object",
        required: ["ack"],
        properties: { ack: { type: "boolean" } },
        additionalProperties: false,
      },
    },
  });
  const inbox = await call(main.client, "inbox__claim", { limit: 10 });
  if (!inbox.messages.some((item) => item.message_id === message.message_id)) throw new Error("message_not_delivered");
  const delivered = inbox.messages.find((item) => item.message_id === message.message_id);
  const obligation = delivered?.response_obligations?.[0];
  if (!obligation?.obligation_id) throw new Error("response_obligation_missing");
  await call(main.client, "inbox__presented", { message_id: message.message_id, evidence_digest: "bridge-smoke", evidence_kind: "mcp" });
  const response = await call(main.client, "message__send", {
    recipient_agent_id: workerContext.agent_id,
    kind: "bridge.smoke.response",
    subject_ref: task.task_id,
    summary: "main observed worker",
    payload: { ack: true },
    in_reply_to: message.message_id,
  });
  await call(main.client, "message__respond", {
    obligation_id: obligation.obligation_id,
    response_message_id: response.message_id,
  });
  await call(main.client, "inbox__ack", { message_id: message.message_id, reason: "observed" });

  const prepared = await call(worker.client, "workspace__prepare", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    decision_id: selection.decision_id,
    input_digest: "bridge-smoke",
    root_binding_refs: [],
    baseline: {},
  });
  const preflight = await call(worker.client, "task__preflight", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    evidence_refs: [`workspace:${prepared.workspace_id}`],
  });
  await call(worker.client, "task__start", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    preflight_id: preflight.preflight_id,
  });
  if (process.argv.includes("--stop-after-start")) {
    process.stdout.write(JSON.stringify({ status: "started", task_id: task.task_id, attempt_id: claimed.attempt_id }) + "\n");
    throw new StopAfterStart();
  }
  await writeFile(resolve(projectRoot, workFile), "export const value = 1;\n", "utf-8");
  await writeFile(resolve(projectRoot, userFile), "manual edit between baseline and result\n", "utf-8");
  const test = spawnSync(process.execPath, ["-e", `import(${JSON.stringify(`./${workFile}`)}).then(({value}) => { if (value !== 1) process.exit(1); })`], {
    cwd: projectRoot,
    encoding: "utf-8",
  });
  if (test.status !== 0) throw new Error(`worker_test_failed:${test.stderr ?? "unknown"}`);
  const result = await call(worker.client, "workspace__result", {
    workspace_id: prepared.workspace_id,
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    baseline_digest: prepared.baseline_digest,
    changed_paths: [workFile, userFile],
    commit_refs: [],
    untracked_summary: [],
    validation_refs: ["bridge-smoke:ok"],
  });
  if (result.baseline_conflict !== true) throw new Error("baseline_conflict_not_observed");
  const submitted = await call(worker.client, "task__submit", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    summary: "bridge smoke passed",
    workspace_result_ref: result.result_manifest_id,
  });
  const reviewed = await call(main.client, "task__review_accept", {
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    result_id: submitted.result_id,
    result_digest: submitted.digest,
    slot_id: "main",
    reason: "bridge smoke passed",
  });
  if (reviewed.status !== "completed") throw new Error(`review_status:${reviewed.status}`);

  const decision = await call(main.client, "decision__propose", {
    kind: "design.change",
    proposal_ref: task.task_id,
    choices: ["approved"],
    summary: "confirm bridge smoke scope",
  });
  const completion = await call(main.client, "project__completion_propose", {
    objective_ref: "project",
    outstanding_summary: "none",
    evidence_refs: [`task:${task.task_id}`, `result:${submitted.result_id}`],
    expected_project_revision: 1,
  });

  await expectError(main.client, "task__claim", { task_id: task.task_id }, "task_not_claimable");
  process.stdout.write(JSON.stringify({
    status: "passed",
    task_id: task.task_id,
    attempt_id: claimed.attempt_id,
    main_agent_id: mainContext.agent_id,
    worker_agent_id: workerContext.agent_id,
    lease_set_id: lease.lease_set_id,
    discrepancy_observed: true,
    baseline_conflict: result.baseline_conflict,
    test_executed: true,
    message_id: message.message_id,
    response_message_id: response.message_id,
    response_obligation: "responded",
    contract_id: contract.proposal_id,
    result_id: submitted.result_id,
    review_status: reviewed.status,
    user_decision: { decision_id: decision.decision_id, revision: decision.revision, proposal_digest: decision.proposal_digest },
    completion: { proposal_id: completion.proposal_id, revision: completion.revision, proposal_digest: completion.proposal_digest },
    foreign_execution_submit: "rejected",
  }, null, 2) + "\n");
} catch (error) {
  if (!(error instanceof ContextOnly) && !(error instanceof StopAfterStart)) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
} finally {
  await Promise.allSettled([main.client.close(), worker.client.close()]);
}
