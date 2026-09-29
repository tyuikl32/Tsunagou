/**
 * Tsunagou bridge: a stdio MCP server a real host session (Codex) loads to reach
 * the local Tsunagou command server over HTTP.
 *
 * This is the runnable half of the bridge contract the TS SDK only *describes*:
 * ``bridge-sdk`` exports the ``BridgeTransport`` interface and client-side
 * primitives, but no executable server. This file implements that transport for
 * the flat ``POST /api/v1/commands/{command_kind}`` entrypoint and turns the
 * business commands into typed MCP tools, while keeping the session credential
 * inside the transport (never in a command envelope or prompt).
 *
 * Enrollment is a real one-time-ticket redemption: the bridge reads the private
 * ticket file the CLI wrote, redeems it through the T-principal path, and keeps
 * only the resulting session bearer/epoch out of the request payloads it sends.
 * Every admission baseline row is backed by an actual observation — a host
 * identity digest read from the host's environment, the tool set actually
 * registered here, a project root actually listed, and resume continuity actually
 * observed against a previously persisted digest. No row is self-asserted.
 */

import { createHash, randomUUID } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { CredentialHandoff, loadSession, type PersistedSession, type SessionCredential, type TicketFile } from "./credential-handoff.js";

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type CallToolRequest,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";

const OPERATIONAL_CAPABILITIES = [
  "task.lifecycle",
  "cognition.report",
  "contract.participation",
  "inbox.pull_fetch_ack",
  "response.structured",
  "recovery.idempotent_reconnect",
  "delivery.deduplicate",
] as const;

const PROTOCOL_VERSION = "1.0";

/**
 * Keep the bridge and daemon on the same protocol bundle without embedding a
 * second, manually maintained digest in the bridge source. A packaged bridge
 * may set TSUNAGOU_SCHEMA_BUNDLE_DIGEST; a source checkout can read the shared
 * registry directly. Missing resources are a startup error rather than a
 * silently stale bridge.
 */
function readSchemaBundleDigest(): string {
  const configured = process.env.TSUNAGOU_SCHEMA_BUNDLE_DIGEST;
  if (configured) return configured;
  const here = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(here, "..", "protocol", "registry", "commands.json"),
    join(process.cwd(), "protocol", "registry", "commands.json"),
    join(here, "..", "..", "..", "protocol", "registry", "commands.json"),
  ];
  for (const candidate of candidates) {
    if (!existsSync(candidate)) continue;
    const raw = JSON.parse(readFileSync(candidate, "utf-8")) as { schema_bundle_digest?: unknown };
    if (typeof raw.schema_bundle_digest === "string" && raw.schema_bundle_digest) {
      return raw.schema_bundle_digest;
    }
  }
  throw new Error("schema_bundle_digest_unavailable:set TSUNAGOU_SCHEMA_BUNDLE_DIGEST or provide protocol/registry/commands.json");
}

const SCHEMA_BUNDLE_DIGEST = readSchemaBundleDigest();

function workspaceSchema(name: "prepare" | "result"): Tool["inputSchema"] {
  const here = dirname(fileURLToPath(import.meta.url));
  const relative = `schemas/commands/workspace/${name}.schema.json`;
  for (const root of [join(here, "..", "protocol"), join(here, "..", "..", "..", "protocol")]) {
    const path = join(root, relative);
    if (existsSync(path)) return JSON.parse(readFileSync(path, "utf-8")) as Tool["inputSchema"];
  }
  throw new Error("workspace_schema_unavailable");
}

/**
 * Where the agent should go next, for the codes that arrive as a bare code.
 *
 * Only codes whose next step is *not* obvious belong here. A refusal that already
 * carries structured detail from the daemon (an out-of-scope rejection brings its
 * own violations and next_steps) must not be duplicated or overwritten here.
 */
const ENROLLMENT_GUIDANCE = [
  "enrollment is driven by the user in the hosting window: ask them to re-run `tsunagou agent connect`",
  "never construct, copy or paste a ticket or session token yourself",
] as const;

const ERROR_GUIDANCE: Readonly<Record<string, readonly string[]>> = {
  not_enrolled: ENROLLMENT_GUIDANCE,
  invalid_ticket_file: ENROLLMENT_GUIDANCE,
  invalid_ticket_role: ENROLLMENT_GUIDANCE,
  invalid_or_consumed_enrollment_ticket: ENROLLMENT_GUIDANCE,
  enrollment_identity_mismatch: ENROLLMENT_GUIDANCE,
  conversation_already_attached: ENROLLMENT_GUIDANCE,
  host_conversation_identity_mismatch: ENROLLMENT_GUIDANCE,
  conversation_identity_required_for_session_file: ENROLLMENT_GUIDANCE,
  stale_connection_epoch: ENROLLMENT_GUIDANCE,
  session_not_found: ENROLLMENT_GUIDANCE,
  stale_or_blocked_preflight: [
    "re-run preflight so evidence and blockers are recollected",
    "if the blocker is an unaccepted contract: compare the current contract digest, then accept or withdraw it",
  ],
  attempt_not_running: [
    "this attempt is no longer open: record the workspace result *before* submitting; for further work, claim a fresh attempt",
  ],
  contract_not_accepted: [
    "a contract this task depends on is not settled: read the current revision and accept it, or reject it and escalate the disagreement to the main agent",
  ],
  supersede_target_not_current: [
    "the contract you tried to replace is no longer in play: re-read the current contract before proposing a revision",
  ],
  supersede_already_pending: [
    "another revision of that contract is already in play: settle or withdraw that one before proposing a different successor",
  ],
  response_schema_violation: [
    "the answer does not satisfy the response contract: send every required field and quote the exact proposal digest you are answering",
  ],
  task_scope_denied: [
    "the action is outside the task's declared execution scope",
    "request a wider scope, or stay inside the current one",
  ],
  workspace_scope_denied: [
    "a reported path is outside this workspace's prepared scope: request a wider scope, or report only paths inside it",
  ],
  workspace_task_scope_denied: [
    "the requested root is not one this task declared: pick a root from the task's execution scope",
  ],
  workspace_changed_paths_mismatch: [
    "you reported a path the daemon's own scan did not observe: report only paths the observation confirms",
  ],
  workspace_patch_artifact_mismatch: [
    "the patch artifact does not match the observed change: re-record the patch, or drop patch_artifact_ref and let the daemon record it",
  ],
  uncommitted_result_requires_patch_artifact: [
    "an uncommitted change needs a patch artifact: pass patch_artifact_ref, or commit the change",
  ],
  resource_lease_expired: [
    "the execution lease expired and this attempt was fenced: re-claim the task and take a fresh lease",
  ],
  resource_conflict: [
    "the path is held by another attempt's lease: wait for release, or use another path",
    "never write outside your own lease",
  ],
  capability_denied: ["your role lacks this capability: hand it to the main agent or the user"],
  principal_kind_denied: ["this command belongs to another principal kind: check who is meant to call it"],
  idempotency_conflict: ["the same command_id was reused with different arguments: use a new command_id"],
  unknown_payload_field: ["the request carries a field the command does not accept: re-send per the tool schema"],
  unknown_tool: ["no such tool: list the tools once and use a name from that list"],
  handler_not_registered: ["declared but not implemented on this daemon: do not retry, report it"],
  project_lock_unavailable: ["another process holds the project lock: retry after a short wait"],
  contract_revision_conflict: [
    "the contract versions you declared are not the ones in force: call context__project_read to read them, then run preflight again if you have not started, or bring this attempt's work up to date and submit again if you have — this refusal closed nothing, the attempt, its lease and its files are untouched",
  ],
};

/**
 * Contract versions this session actually read, per task.
 *
 * The start boundary compares a declaration against the versions in force, so the
 * declaration has to come from a read the agent really did. Remembering the read here
 * keeps the model out of the loop: preflight carries what was last read, and a stale
 * read is refused until the agent reads again.
 */
const contractsInForce = new Map<string, string[]>();

function declareContracts(args: Record<string, unknown>, field = "expected_revisions"): void {
  const taskId = args.task_id;
  if (typeof taskId !== "string") return;
  const revisions = contractsInForce.get(taskId);
  if (revisions === undefined) return;
  const existing = args[field];
  if (existing !== undefined && existing !== null && (typeof existing !== "object" || Array.isArray(existing))) {
    // A legacy single-token caller keeps its shape; the check is driven by the
    // declaration, so leaving it alone simply means no contract gate here.
    return;
  }
  args[field] = { ...(existing as Record<string, unknown> | undefined), contract: revisions };
}

function rememberContracts(result: unknown): void {
  const tasks = (result as { contracts?: { tasks?: unknown } } | null | undefined)?.contracts?.tasks;
  if (!Array.isArray(tasks)) return;
  for (const item of tasks) {
    const entry = item as { task_id?: unknown; in_force?: unknown };
    if (typeof entry.task_id !== "string") continue;
    contractsInForce.set(
      entry.task_id,
      Array.isArray(entry.in_force) ? entry.in_force.filter((value): value is string => typeof value === "string") : [],
    );
  }
}

function buildToolError(message: string, detail?: unknown): Record<string, unknown> {
  const code = message.replace(/^tsunagou_[a-z_]*error:/, "");
  const payload: Record<string, unknown> = { error: message, code };
  if (detail !== undefined && typeof detail === "object" && detail !== null) {
    Object.assign(payload, detail as Record<string, unknown>);
  }
  const guidance = ERROR_GUIDANCE[code];
  // The daemon's own next_steps are more specific than anything kept here.
  if (guidance !== undefined && payload.next_steps === undefined) payload.next_steps = guidance;
  return payload;
}

interface ToolSpec {
  name: string;
  command_kind: string;
  description: string;
  inputSchema: Tool["inputSchema"];
}

/**
 * The generic stdio bridge has no host reverse-wake transport of its own. Keep
 * this explicit in diagnostics until a host adapter supplies verified evidence;
 * registering the status/ready tools below does not claim that a wake occurred.
 */
const BRIDGE_WAKE_CAPABILITY = {
  status: "unsupported" as const,
  evidence: "stdio_bridge_host_wake_transport_unavailable",
};

function hash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function env(name: string, fallback = ""): string {
  const value = process.env[name];
  return value !== undefined && value !== "" ? value : fallback;
}

function config(): {
  httpUrl: string;
  daemonStateDir: string;
  ticketFile: string;
  sessionFile?: string;
  projectRoot: string;
  stateDir: string;
  hostIdCandidates: string[];
} {
  const stateDir = env("TSUNAGOU_STATE_DIR", join(homedir(), ".tsunagou"));
  const projectRoot = env("TSUNAGOU_PROJECT_ROOT");
  return {
    httpUrl: env("TSUNAGOU_HTTP_URL", "http://127.0.0.1:8000").replace(/\/+$/, ""),
    daemonStateDir: env("TSUNAGOU_DAEMON_STATE_DIR", projectRoot ? join(projectRoot, ".tsunagou", "local") : ""),
    ticketFile: env("TSUNAGOU_TICKET_FILE"),
    sessionFile: process.env.TSUNAGOU_SESSION_FILE || undefined,
    projectRoot,
    stateDir,
    hostIdCandidates: env(
      "TSUNAGOU_HOST_ID_ENV",
      "CODEX_SESSION_ID,CODEX_THREAD_ID,CODEX_CONVERSATION_ID,CODEX_ROLLOUT_ID,CODEX_AGREEMENT_ID",
    ).split(",").map((name) => name.trim()).filter(Boolean),
  };
}

function readDaemonUrl(stateDir: string): string | undefined {
  if (!stateDir) return undefined;
  const manifest = join(stateDir, "endpoint.json");
  if (!existsSync(manifest)) return undefined;
  try {
    const raw = JSON.parse(readFileSync(manifest, "utf-8")) as { url?: unknown };
    return typeof raw.url === "string" && raw.url ? raw.url.replace(/\/+$/, "") : undefined;
  } catch {
    return undefined;
  }
}

function readHostIdentity(candidates: string[]): { digest: string; envName: string } | undefined {
  for (const name of candidates) {
    const value = process.env[name];
    if (value !== undefined && value !== "") {
      return { digest: hash(`${name}:${value}`), envName: name };
    }
  }
  return undefined;
}

function readTicketFile(path: string): TicketFile {
  const raw = JSON.parse(readFileSync(path, "utf-8")) as TicketFile;
  if (
    typeof raw.installation_id !== "string" || !raw.installation_id
    || typeof raw.conversation_id !== "string" || !raw.conversation_id
    || typeof raw.secret !== "string" || !raw.secret
  ) {
    throw new Error("invalid_ticket_file");
  }
  if (raw.requested_role !== undefined && raw.requested_role !== "worker" && raw.requested_role !== "main") {
    throw new Error("invalid_ticket_role");
  }
  return raw;
}

function readProjectDigest(projectRoot: string): string | undefined {
  if (!projectRoot || !existsSync(projectRoot)) return undefined;
  const names = readdirSync(projectRoot).sort().join("\n");
  return hash(`project_root:${resolve(projectRoot)}\n${names}`);
}

/** List the typed tools actually registered below, as admission evidence. */
function toolEvidence(tools: readonly ToolSpec[]): string {
  return `tools:${tools.length}:${tools.map((tool) => tool.name).join(",")}`;
}

/**
 * Build the enrollment baseline. Every "supported" row carries a concrete
 * observation; a row we cannot prove today is left "unknown" with no refs.
 */
function buildBaseline(opts: {
  hostDigest: string | undefined;
  projectDigest: string | undefined;
  continuityRefs: string[] | undefined;
  tools: readonly ToolSpec[];
}): Record<string, unknown> {
  const supported = (refs: string[]) => ({ status: "supported", strength: "observed", evidence_refs: refs });
  const unknown = () => ({ status: "unknown" });
  const rows: Record<string, unknown> = {
    "identity.session_isolation": opts.hostDigest ? supported([`host_digest:${opts.hostDigest}`]) : unknown(),
    "identity.continuity_evidence": opts.continuityRefs ? supported(opts.continuityRefs) : unknown(),
    "context.project_read": opts.projectDigest ? supported([`project_root_digest:${opts.projectDigest}`]) : unknown(),
    "command.typed_tools": supported([toolEvidence(opts.tools)]),
  };
  for (const name of OPERATIONAL_CAPABILITIES) {
    rows[name] = unknown();
  }
  return { baseline: rows };
}

const TOOLS: readonly ToolSpec[] = [
  { name: "task__create", command_kind: "task.create", description: "Create, ready and publish a task in this coordination scope (main-authority only).", inputSchema: { type: "object", required: ["title", "objective"], properties: { title: { type: "string" }, objective: { type: "string" }, parent_task_id: { type: "string" }, blocks: { type: "array", items: { type: "string" } }, execution_scope: { type: "object" } }, additionalProperties: false } },
  { name: "task__ready", command_kind: "task.ready", description: "Mark a draft task ready for publication (main-authority only).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__publish", command_kind: "task.publish", description: "Publish a ready task so workers can claim it (main-authority only).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__update_plan", command_kind: "task.update_plan", description: "Update a task plan before an attempt starts (main-authority only).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, title: { type: "string" }, objective: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__edge_add", command_kind: "task.edge.add", description: "Add a blocking dependency between tasks (main-authority only).", inputSchema: { type: "object", required: ["source_task_id", "target_task_id"], properties: { source_task_id: { type: "string" }, target_task_id: { type: "string" }, kind: { type: "string" } }, additionalProperties: false } },
  { name: "task__edge_remove", command_kind: "task.edge.remove", description: "Remove a blocking dependency between tasks (main-authority only).", inputSchema: { type: "object", required: ["source_task_id", "target_task_id"], properties: { source_task_id: { type: "string" }, target_task_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__claim", command_kind: "task.claim", description: "Claim a task for this agent (preparation, not execution).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" } }, additionalProperties: false } },
  { name: "task__resume", command_kind: "task.resume", description: "Resume a previously claimed task (preparation, not execution).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, expected_execution_epoch: { type: "integer" }, expected_revisions: { type: "object" } }, additionalProperties: false } },
  { name: "task__preflight", command_kind: "task.preflight", description: "Run a preflight check on a claimed task attempt (preparation, not execution).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, expected_revisions: { type: "object" } }, additionalProperties: false } },
  { name: "task__start", command_kind: "task.start", description: "Begin executing a claimed task after preflight; issues the execution grant for this attempt.", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, preflight_id: { type: "string" }, expected_execution_epoch: { type: "integer" } }, additionalProperties: false } },
  { name: "task__progress", command_kind: "task.progress", description: "Record progress on a running attempt (execution command).", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, summary: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "task__block", command_kind: "task.block", description: "Mark a task blocked with a reason.", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, reason_code: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__cancel_request", command_kind: "task.cancel_request", description: "Request cancellation of a task (main-authority only).", inputSchema: { type: "object", required: ["task_id", "reason"], properties: { task_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__cancel_ack", command_kind: "task.cancel_ack", description: "Acknowledge cancellation after stopping the owned attempt.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "reason"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, reason: { type: "string" }, stop_evidence: { type: "object" } }, additionalProperties: false } },
  { name: "task__fail", command_kind: "task.fail", description: "Mark the owned attempt failed with explicit evidence.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "reason"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, stop_evidence: { type: "object" } }, additionalProperties: false } },
  { name: "task__recover", command_kind: "task.recover", description: "Recover an orphaned or blocked attempt (main-authority only).", inputSchema: { type: "object", required: ["task_id", "expected_attempt_id", "disposition"], properties: { task_id: { type: "string" }, expected_attempt_id: { type: "string" }, disposition: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__scope_request", command_kind: "task.scope.request", description: "Request a task scope expansion as the current owner.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "requested_scope", "reason"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, requested_scope: { type: "object" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__scope_resolve", command_kind: "task.scope.resolve", description: "Approve or reject a pending task scope request (main-authority only).", inputSchema: { type: "object", required: ["scope_request_id", "choice"], properties: { scope_request_id: { type: "string" }, choice: { type: "string" }, approved_scope: { type: "object" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__submit", command_kind: "task.submit", description: "Submit the work for a started attempt (execution command).", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, summary: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, artifact_refs: { type: "array", items: { type: "string" } }, workspace_result_ref: { type: "string" }, expected_revisions: { type: "object" } } } },
  { name: "task__self_accept", command_kind: "task.self_accept", description: "Self-accept a result when task policy permits it.", inputSchema: { type: "object", required: ["task_id", "result_id", "result_digest"], properties: { task_id: { type: "string" }, result_id: { type: "string" }, result_digest: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "resource__intent", command_kind: "resource.intent", description: "Declare the resources required by a task attempt.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "resources"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, resources: { type: "array", items: { type: "object" } }, scope_digest: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "resource__acquire", command_kind: "resource.acquire", description: "Acquire the lease set for a declared resource intent.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "intent_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, intent_id: { type: "string" }, intent_revision: { type: "integer" }, scope_digest: { type: "string" } }, additionalProperties: false } },
  { name: "resource__release", command_kind: "resource.release", description: "Release resources held by a task attempt.", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "resource__renew", command_kind: "resource.renew", description: "Renew the active resource lease for a running attempt.", inputSchema: { type: "object", required: ["lease_set_id", "task_id", "attempt_id"], properties: { lease_set_id: { type: "string" }, task_id: { type: "string" }, attempt_id: { type: "string" }, scope_digest: { type: "string" } }, additionalProperties: false } },
  { name: "workspace__select", command_kind: "workspace.select", description: "Select an isolation driver for the task attempt.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "driver_kind"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, driver_kind: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, hard_constraints: { type: "array", items: { type: "string" } }, input_digest: { type: "string" }, risk_submission_ref: { type: "string" } }, additionalProperties: false } },
  { name: "workspace__prepare", command_kind: "workspace.prepare", description: "Prepare the selected workspace and record its baseline.", inputSchema: workspaceSchema("prepare") },
  { name: "workspace__result", command_kind: "workspace.result", description: "Record the resulting workspace manifest after execution.", inputSchema: workspaceSchema("result") },
  { name: "workspace__integrate", command_kind: "workspace.integrate", description: "Create a Main-owned local integration request from a worker result; this never pushes.", inputSchema: { type: "object", required: ["source_result_ref", "target_repository_id", "target_baseline_digest", "plan_digest", "reason"], properties: { source_result_ref: { type: "string" }, target_repository_id: { type: "string" }, target_baseline_digest: { type: "string" }, plan_digest: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__review_accept", command_kind: "task.review.accept", description: "Accept a submitted task result as the designated reviewer.", inputSchema: { type: "object", required: ["task_id", "result_id", "result_digest", "slot_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, result_id: { type: "string" }, result_digest: { type: "string" }, slot_id: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "task__review_request_changes", command_kind: "task.review.request_changes", description: "Request changes to a submitted task result as the designated reviewer.", inputSchema: { type: "object", required: ["task_id", "result_id", "result_digest", "slot_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, result_id: { type: "string" }, result_digest: { type: "string" }, slot_id: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "cognition__report", command_kind: "cognition.report", description: "Submit an explicit cognition report (claims, assumptions, uncertainties). The contract versions you were working from are filled in from your last project read, so what the report was based on can be pointed at later.", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, claims: { type: "array", items: { type: "object", required: ["subject_key"], properties: { subject_key: { type: "string" }, subject: { type: "string" }, claim_type: { type: "string" }, equality_key: { type: "string" }, value: {}, evidence_refs: { type: "array", items: { type: "string" } } } } }, assumptions: { type: "array", items: { type: "string" } }, uncertainties: { type: "array", items: { type: "string" } }, input_revisions: { type: "object" } } } },
  { name: "discrepancy__create", command_kind: "discrepancy.create", description: "Create a visible cognition discrepancy from existing reports.", inputSchema: { type: "object", required: ["subject_ref", "report_refs", "severity", "summary"], properties: { subject_ref: { type: "string" }, report_refs: { type: "array", items: { type: "string" } }, severity: { type: "string" }, summary: { type: "string" }, participants: { type: "array" }, affected_actions: { type: "array" } }, additionalProperties: false } },
  { name: "discrepancy__advance", command_kind: "discrepancy.advance", description: "Advance a discrepancy into clarification or negotiation.", inputSchema: { type: "object", required: ["discrepancy_id", "status"], properties: { discrepancy_id: { type: "string" }, status: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "discrepancy__resolve", command_kind: "discrepancy.resolve", description: "Resolve a discrepancy by consensus, dismissal or explicit override (main-authority only).", inputSchema: { type: "object", required: ["discrepancy_id", "kind"], properties: { discrepancy_id: { type: "string" }, kind: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "contract__propose", command_kind: "contract.propose", description: "Propose a coordination contract with required/optional participants, optionally replacing an existing one (supersedes_id) to revise it.", inputSchema: { type: "object", properties: { payload: { type: "object" }, participants_required: { type: "array" }, participants_optional: { type: "array" }, supersedes_id: { type: "string" } }, additionalProperties: false } },
  { name: "contract__accept", command_kind: "contract.accept", description: "Accept a specific contract proposal digest as a participant slot.", inputSchema: { type: "object", required: ["proposal_id", "participant_slot", "proposal_digest"], properties: { proposal_id: { type: "string" }, participant_slot: { type: "string" }, proposal_digest: { type: "string" } }, additionalProperties: false } },
  { name: "contract__accept_proxy", command_kind: "contract.accept_proxy", description: "Accept a contract slot through an explicit main-authority proxy.", inputSchema: { type: "object", required: ["proposal_id", "participant_slot_id", "proposal_digest"], properties: { proposal_id: { type: "string" }, participant_slot_id: { type: "string" }, proposal_digest: { type: "string" }, proxy_policy_ref: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "contract__reject", command_kind: "contract.reject", description: "Reject a proposed contract as its participating agent.", inputSchema: { type: "object", required: ["proposal_id", "proposal_digest", "reason"], properties: { proposal_id: { type: "string" }, proposal_digest: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array" } }, additionalProperties: false } },
  { name: "contract__withdraw", command_kind: "contract.withdraw", description: "Withdraw a still-proposed contract created by this agent.", inputSchema: { type: "object", required: ["proposal_id", "reason"], properties: { proposal_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "durability__reconcile", command_kind: "durability.reconcile", description: "Retry a failed checkpoint materialization after the project is completed (main-authority only).", inputSchema: { type: "object", required: ["reason"], properties: { scope_refs: { type: "array", items: { type: "string" } }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "inbox__claim", command_kind: "inbox.claim", description: "Claim this agent's inbox deliveries.", inputSchema: { type: "object", properties: { limit: { type: "integer" } }, additionalProperties: false } },
  { name: "inbox__fetch", command_kind: "inbox.fetch", description: "Fetch one inbox message by id.", inputSchema: { type: "object", required: ["message_id"], properties: { message_id: { type: "string" }, delivery_lease_id: { type: "string" } }, additionalProperties: false } },
  { name: "inbox__presented", command_kind: "inbox.presented", description: "Record that a delivery was presented with an evidence digest.", inputSchema: { type: "object", required: ["message_id"], properties: { message_id: { type: "string" }, evidence_digest: { type: "string" }, evidence_kind: { type: "string" } }, additionalProperties: false } },
  { name: "inbox__ack", command_kind: "inbox.ack", description: "Acknowledge a presented inbox delivery.", inputSchema: { type: "object", required: ["message_id"], properties: { message_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "message__send", command_kind: "message.send", description: "Send a message to another agent.", inputSchema: { type: "object", required: ["recipient_agent_id"], properties: { command_id: { type: "string", description: "Optional idempotency key. Reusing this id with different message input is rejected as a conflict." }, recipient_agent_id: { type: "string" }, kind: { type: "string" }, subject_ref: { type: "string" }, summary: { type: "string" }, payload: { type: "object" }, priority: { type: "integer" }, response_contract: { type: "object", properties: { required: { type: "boolean" }, schema: { type: "object" } } }, in_reply_to: { type: "string" } } } },
  { name: "message__respond", command_kind: "message.respond", description: "Fulfill a response obligation on a received message.", inputSchema: { type: "object", required: ["obligation_id", "response_message_id"], properties: { obligation_id: { type: "string" }, response_message_id: { type: "string" } }, additionalProperties: false } },
  { name: "context__project_read", command_kind: "context.project_read", description: "Read this agent's project context: identity, role, scope capabilities, owned tasks, and the contracts those tasks depend on (with the versions currently in force).", inputSchema: { type: "object", additionalProperties: false } },
  { name: "project__configure", command_kind: "project.configure", description: "Enable or disable project-level automatic worker wake for future coordination plans (main-authority only).", inputSchema: { type: "object", required: ["policy_patch", "reason"], properties: { policy_patch: { type: "object", properties: { auto_wake_multi_agent: { type: "boolean" } }, additionalProperties: false }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "decision__propose", command_kind: "user_decision.propose", description: "Propose a decision that requires user input (main-authority only).", inputSchema: { type: "object", required: ["kind", "proposal_ref", "choices", "summary"], properties: { kind: { type: "string" }, proposal_ref: { type: "string" }, choices: { type: "array", items: { type: "object" } }, summary: { type: "string" }, proposal_digest: { type: "string" }, expected_revisions: { type: "object" } }, additionalProperties: false } },
  { name: "project__completion_propose", command_kind: "project.completion.propose.main", description: "Propose project completion for user confirmation (main-authority only).", inputSchema: { type: "object", required: ["objective_ref"], properties: { objective_ref: { type: "string" }, outstanding_summary: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, expected_project_revision: { type: "integer" } }, additionalProperties: false } },
  { name: "coordination__plan", command_kind: "coordination.plan", description: "Create an atomic Main-owned assignment plan and durable wake attempts (main-authority only).", inputSchema: { type: "object", required: ["objective", "assignments"], properties: { objective: { type: "string" }, auto_wake: { type: "boolean" }, wake_deadline_seconds: { type: "number" }, assignments: { type: "array", items: { type: "object", required: ["assigned_worker_id", "title", "task_objective"], properties: { assigned_worker_id: { type: "string" }, title: { type: "string" }, task_objective: { type: "string" }, parent_task_id: { type: "string" }, blocks: { type: "array", items: { type: "string" } }, dependencies: { type: "array", items: { type: "string" } }, acceptance_conditions: { type: "object" }, workspace: { type: "object" }, resource_intent: { type: "object" }, execution_scope: { type: "object" } }, additionalProperties: false } } }, additionalProperties: false } },
  { name: "worker__ready", command_kind: "worker.ready", description: "Confirm that this worker was woken, presented its assignment and is ready to claim it (worker-only). This does not acquire a Lease.", inputSchema: { type: "object", required: ["assignment_id", "wake_attempt_id"], properties: { assignment_id: { type: "string" }, wake_attempt_id: { type: "string" } }, additionalProperties: false } },
  { name: "coordination__takeover", command_kind: "coordination.takeover", description: "Explicitly let Main take over a worker assignment after recording the reason (main-authority only).", inputSchema: { type: "object", required: ["assignment_id", "takeover_reason"], properties: { assignment_id: { type: "string" }, takeover_reason: { type: "string" } }, additionalProperties: false } },
];

class HttpTransport {
  public constructor(private readonly baseUrl: string) {}

  public async dispatch(
    kind: string,
    payload: Record<string, unknown>,
    session: SessionCredential,
    commandId?: string,
  ): Promise<unknown> {
    // Every MCP action is a new command by default. Callers that retry the same
    // action after an uncertain network result may pass the original command_id;
    // the daemon then provides the idempotency/conflict guarantee. Two deliberate
    // actions with identical payloads must remain two distinct commands.
    const envelope = {
      command_id: commandId?.trim() || randomUUID(),
      protocol_version: PROTOCOL_VERSION,
      schema_bundle_digest: SCHEMA_BUNDLE_DIGEST,
      payload,
    };
    const response = await fetch(`${this.baseUrl}/api/v1/commands/${kind}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${session.secret_token}`,
        "tsunagou-session-id": session.session_id,
        "tsunagou-connection-epoch": String(session.connection_epoch),
      },
      body: JSON.stringify(envelope),
    });
    const body = (await response.json().catch(() => ({}))) as {
      command_hash?: string;
      result?: unknown;
      detail?: { code?: string };
    };
    if (!response.ok) {
      const code = body.detail?.code ?? `http_${response.status}`;
      const failure = new Error(`tsunagou_error:${code}`);
      // Keep the daemon's structured detail (violations / allowed / next_steps)
      // so the agent learns *what* to fix, not just that it failed.
      (failure as Error & { detail?: unknown }).detail = body.detail;
      throw failure;
    }
    return body.result ?? {};
  }

}

/** A previously persisted digest lets us observe resume continuity honestly. */
function continuityRefs(previousDigest: string | undefined, currentDigest: string | undefined): string[] | undefined {
  if (previousDigest === undefined || currentDigest === undefined) return undefined;
  return previousDigest === currentDigest ? ["resume:same_digest"] : ["resume:changed_digest"];
}

async function main(): Promise<void> {
  const cfg = config();
  const hostIdentity = readHostIdentity(cfg.hostIdCandidates);
  let hostDigest = hostIdentity?.digest;
  const projectDigest = cfg.projectRoot ? readProjectDigest(cfg.projectRoot) : undefined;
  const transport = new HttpTransport(readDaemonUrl(cfg.daemonStateDir) ?? cfg.httpUrl);

  // The MCP process may outlive the CLI operation that writes its ticket or
  // session file.  Do not snapshot admission files only once at process boot:
  // Codex keeps a stdio bridge alive across `mcp add`/re-enrollment.
  let bootstrapTicket: TicketFile | undefined;
  // A bridge credential belongs to one host conversation. Never use a global
  // ~/.tsunagou/bridge-session.json: when Codex/OpenCode launches several
  // conversations from the same IDE, that file would silently make them one
  // worker. Explicit TSUNAGOU_SESSION_FILE remains supported for a caller
  // that deliberately provisions one private file per conversation.
  let conversationBindingDigest = hostDigest;
  let sessionFile = cfg.sessionFile ?? (
    conversationBindingDigest
      ? join(cfg.stateDir, "sessions", `bridge-session-${conversationBindingDigest.slice(0, 32)}.json`)
      : undefined
  );
  let session: PersistedSession | undefined = sessionFile ? loadSession(sessionFile) : undefined;
  let observedContinuity = continuityRefs(session?.host_conversation_id_digest, hostDigest);

  let recoveryError: string | undefined;
  async function attemptSessionRecovery(forceReconnect = false): Promise<void> {
    try {
      bootstrapTicket = cfg.ticketFile && existsSync(cfg.ticketFile)
        ? readTicketFile(cfg.ticketFile) : undefined;
      const ticketBinding = bootstrapTicket ? hash(`conversation_id:${bootstrapTicket.conversation_id}`) : undefined;
      if (!cfg.sessionFile && ticketBinding) {
        // When the host exposes stable identity, use the same pathname before
        // and after single-use ticket cleanup so restart can find the journal.
        const fileIdentity = hostIdentity?.digest ?? ticketBinding;
        sessionFile = join(cfg.stateDir, "sessions", `bridge-session-${fileIdentity.slice(0, 32)}.json`);
      }
      if (!sessionFile) {
        session = undefined;
        recoveryError = "not_enrolled:no_ticket_or_session_file";
        return;
      }
      const persisted = loadSession(sessionFile);
      conversationBindingDigest = ticketBinding ?? persisted?.conversation_binding_digest ?? hostDigest;
      hostDigest ??= persisted?.host_conversation_id_digest ?? ticketBinding;
      if (!conversationBindingDigest) throw new Error("conversation_identity_required_for_session_file");
      observedContinuity = persisted
        ? continuityRefs(persisted.host_conversation_id_digest, hostDigest)
        : bootstrapTicket ? ["ticket:bound_conversation"] : undefined;
      const handoff = new CredentialHandoff({
        baseUrl: readDaemonUrl(cfg.daemonStateDir) ?? cfg.httpUrl,
        protocolVersion: PROTOCOL_VERSION, schemaBundleDigest: SCHEMA_BUNDLE_DIGEST,
        sessionFile, conversationBindingDigest, hostDigest,
      });
      session = await handoff.recover({
        ticket: bootstrapTicket, ticketFile: cfg.ticketFile || undefined, forceReconnect,
        baseline: buildBaseline({ hostDigest, projectDigest, continuityRefs: observedContinuity, tools: TOOLS }),
      });
      recoveryError = undefined;
    } catch (error) {
      session = undefined;
      const message = error instanceof Error ? error.message : "credential_recovery_failed";
      recoveryError = /^[a-z][a-z0-9_:]{0,160}$/.test(message) ? message : "credential_recovery_failed";
      process.stderr.write(`[tsunagou-bridge] recovery failed: ${recoveryError}\n`);
    }
  }

  await attemptSessionRecovery();
  let recoveryPromise: Promise<void> | undefined;
  async function ensureSession(forceReconnect = false): Promise<void> {
    if (session !== undefined && !forceReconnect) return;
    recoveryPromise ??= attemptSessionRecovery(forceReconnect).finally(() => { recoveryPromise = undefined; });
    await recoveryPromise;
  }

  const server = new Server(
    { name: "tsunagou", version: "0.1.0" },
    {
      capabilities: { tools: {} },
      instructions: (
        "Tsunagou is the coordination authority. When a host turn is started "
        + "for coordination, call context__project_read first, then inbox__claim "
        + "and inbox__fetch/presented for the relevant delivery. Do not use shell "
        + "or infer project state when a typed Tsunagou tool is available."
      ),
    },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOLS.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request: CallToolRequest) => {
    const tool = TOOLS.find((candidate) => candidate.name === request.params.name);
    if (tool === undefined) {
      return { content: [{ type: "text" as const, text: JSON.stringify(buildToolError("unknown_tool")) }], isError: true };
    }
    try {
      await ensureSession();
      if (session === undefined) throw new Error(recoveryError ?? "not_enrolled:no_ticket_or_session_file");
      const args = { ...((request.params.arguments ?? {}) as Record<string, unknown>) };
      const commandId = typeof args.command_id === "string" ? args.command_id : undefined;
      if ("command_id" in args) {
        delete args.command_id;
      }
      if (tool.command_kind === "task.preflight" || tool.command_kind === "task.submit") declareContracts(args);
      if (tool.command_kind === "cognition.report") declareContracts(args, "input_revisions");
      let result: unknown;
      try {
        result = await transport.dispatch(tool.command_kind, args, session, commandId);
      } catch (error) {
        // A daemon restart or an external rebind can invalidate the in-memory
        // epoch while this stdio process remains alive. Re-read the private
        // session/ticket files and retry once before surfacing the error.
        const message = error instanceof Error ? error.message : String(error);
        if (!message.includes("authentication_failed") && !message.includes("stale_connection_epoch")
            && !message.includes("session_not_found")) throw error;
        session = undefined;
        await ensureSession(true);
        if (session === undefined) throw error;
        result = await transport.dispatch(tool.command_kind, args, session, commandId);
      }
      if (tool.command_kind === "context.project_read") rememberContracts(result);
      return { content: [{ type: "text" as const, text: JSON.stringify(result) }] };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const detail = (error as { detail?: unknown } | null | undefined)?.detail;
      return { content: [{ type: "text" as const, text: JSON.stringify(buildToolError(message, detail)) }], isError: true };
    }
  });

  const stdio = new StdioServerTransport();
  // Desensitized boot diagnostic for the wiring phase: env NAMES only, a hashed
  // host digest, and session status. Never a credential, ticket or token value.
  try {
    mkdirSync(cfg.stateDir, { recursive: true });
    writeFileSync(join(cfg.stateDir, "bridge-boot.json"), JSON.stringify({
      host_digest: hostDigest ?? null,
      matched_host_env: hostIdentity?.envName ?? null,
      baseline_status: session?.baseline_status ?? null,
      wake_capability: BRIDGE_WAKE_CAPABILITY,
      codex_env_names: Object.keys(process.env).filter((name) => /^CODEX/i.test(name)).sort(),
      tsunagou_env_names: Object.keys(process.env).filter((name) => name.startsWith("TSUNAGOU_")).sort(),
    }, null, 2) + "\n", "utf-8");
  } catch {
    // best-effort diagnostics must never break the bridge
  }
  await server.connect(stdio);
  process.stderr.write(`[tsunagou-bridge] host_digest=${hostDigest ?? "none"} session=${session?.baseline_status ?? "not_enrolled"} continuity=${observedContinuity?.join("+") ?? "unknown"}\n`);
}

main().catch((error) => {
  process.stderr.write(`[tsunagou-bridge] fatal: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
