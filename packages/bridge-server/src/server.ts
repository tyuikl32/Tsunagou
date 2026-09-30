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
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { CredentialHandoff, loadSession, type PersistedSession, type SessionCredential, type TicketFile } from "./credential-handoff.js";
import { readPrivateJson, writePrivateJson } from "./private-file.js";
import { withPrivateFileLock } from "./private-file-lock.js";

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

function commandSchema(name: string, includeCommandId = false): Tool["inputSchema"] {
  const here = dirname(fileURLToPath(import.meta.url));
  const relative = `schemas/commands/${name.replaceAll(".", "/")}.schema.json`;
  for (const root of [join(here, "..", "protocol"), join(here, "..", "..", "..", "protocol")]) {
    const path = join(root, relative);
    if (existsSync(path)) {
      const schema = JSON.parse(readFileSync(path, "utf-8")) as Tool["inputSchema"];
      if (includeCommandId) schema.properties = { ...schema.properties, command_id: {
        type: "string", description: "Optional envelope idempotency key. The bridge removes it from the business payload.",
      } };
      return schema;
    }
  }
  throw new Error("command_schema_unavailable");
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
  desktopWake: boolean;
  hostMetaKey: string;
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
    desktopWake: env("TSUNAGOU_DESKTOP_WAKE") === "1",
    hostIdCandidates: env(
      "TSUNAGOU_HOST_ID_ENV",
      "CODEX_SESSION_ID,CODEX_THREAD_ID,CODEX_CONVERSATION_ID,CODEX_ROLLOUT_ID,CODEX_AGREEMENT_ID",
    ).split(",").map((name) => name.trim()).filter(Boolean),
    // Set by `agent connect` for hosts (OpenCode) that deliver the
    // conversation id per tool call in MCP `_meta` instead of exporting it as
    // an environment variable. When declared, every tool call must carry a
    // fresh non-empty string id; the bridge never falls back to another
    // conversation's private credential.
    hostMetaKey: env("TSUNAGOU_HOST_META_KEY"),
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
  { name: "task__begin", command_kind: "task.begin", description: "Start a task in one operation, or recover the same running attempt after reconnect. Read the current task revision first.", inputSchema: commandSchema("task.begin") },
  { name: "task__create", command_kind: "task.create", description: "Create a task plan; empty execution_scope is a non-file task. Only explicit required_contract_ids block execution.", inputSchema: commandSchema("task.create") },
  { name: "task__ready", command_kind: "task.ready", description: "Mark a draft task ready for publication (main-authority only).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__publish", command_kind: "task.publish", description: "Publish a ready task so workers can claim it (main-authority only).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__update_plan", command_kind: "task.update_plan", description: "Update an unstarted plan or its explicit contract dependencies.", inputSchema: commandSchema("task.update_plan") },
  { name: "task__edge_add", command_kind: "task.edge.add", description: "Add a blocking dependency between tasks (main-authority only).", inputSchema: { type: "object", required: ["source_task_id", "target_task_id"], properties: { source_task_id: { type: "string" }, target_task_id: { type: "string" }, kind: { type: "string" } }, additionalProperties: false } },
  { name: "task__edge_remove", command_kind: "task.edge.remove", description: "Remove a blocking dependency between tasks (main-authority only).", inputSchema: { type: "object", required: ["source_task_id", "target_task_id"], properties: { source_task_id: { type: "string" }, target_task_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__progress", command_kind: "task.progress", description: "Record progress on a running attempt (execution command).", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, summary: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "task__block", command_kind: "task.block", description: "Mark a task blocked with a reason.", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, reason_code: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__cancel_request", command_kind: "task.cancel_request", description: "Request cancellation of a task (main-authority only).", inputSchema: { type: "object", required: ["task_id", "reason"], properties: { task_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__cancel_ack", command_kind: "task.cancel_ack", description: "Acknowledge cancellation after stopping the owned attempt.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "reason"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, reason: { type: "string" }, stop_evidence: { type: "object" } }, additionalProperties: false } },
  { name: "task__fail", command_kind: "task.fail", description: "Mark the owned attempt failed with explicit evidence.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "reason"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, stop_evidence: { type: "object" } }, additionalProperties: false } },
  { name: "task__recover", command_kind: "task.recover", description: "Recover an orphaned or blocked attempt (main-authority only).", inputSchema: { type: "object", required: ["task_id", "expected_attempt_id", "disposition"], properties: { task_id: { type: "string" }, expected_attempt_id: { type: "string" }, disposition: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__scope_request", command_kind: "task.scope.request", description: "Request a task scope expansion as the current owner.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "requested_scope", "reason"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, requested_scope: { type: "object" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__scope_resolve", command_kind: "task.scope.resolve", description: "Approve or reject a pending task scope request (main-authority only).", inputSchema: { type: "object", required: ["scope_request_id", "choice"], properties: { scope_request_id: { type: "string" }, choice: { type: "string" }, approved_scope: { type: "object" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__submit", command_kind: "task.submit", description: "Submit the owned running attempt; workspace results and resource release are automatic.", inputSchema: commandSchema("task.submit") },
  { name: "task__self_accept", command_kind: "task.self_accept", description: "Self-accept a result when task policy permits it.", inputSchema: { type: "object", required: ["task_id", "result_id", "result_digest"], properties: { task_id: { type: "string" }, result_id: { type: "string" }, result_digest: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "workspace__select", command_kind: "workspace.select", description: "Choose a task workspace policy once before execution; main prepares physical Git paths.", inputSchema: commandSchema("workspace.select") },
  { name: "workspace__integrate", command_kind: "workspace.integrate", description: "Create a Main-owned local integration request from a worker result; this never pushes.", inputSchema: { type: "object", required: ["source_result_ref", "target_repository_id", "target_baseline_digest", "plan_digest", "reason"], properties: { source_result_ref: { type: "string" }, target_repository_id: { type: "string" }, target_baseline_digest: { type: "string" }, plan_digest: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__review_accept", command_kind: "task.review.accept", description: "Accept a submitted task result as the designated reviewer.", inputSchema: { type: "object", required: ["task_id", "result_id", "result_digest", "slot_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, result_id: { type: "string" }, result_digest: { type: "string" }, slot_id: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "task__review_request_changes", command_kind: "task.review.request_changes", description: "Request changes to a submitted task result as the designated reviewer.", inputSchema: { type: "object", required: ["task_id", "result_id", "result_digest", "slot_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, result_id: { type: "string" }, result_digest: { type: "string" }, slot_id: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "cognition__report", command_kind: "cognition.report", description: "Submit an explicit cognition report (claims, assumptions, uncertainties). The contract versions you were working from are filled in from your last project read, so what the report was based on can be pointed at later.", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, claims: { type: "array", items: { type: "object", required: ["subject_key"], properties: { subject_key: { type: "string" }, subject: { type: "string" }, claim_type: { type: "string" }, equality_key: { type: "string" }, value: {}, evidence_refs: { type: "array", items: { type: "string" } } } } }, assumptions: { type: "array", items: { type: "string" } }, uncertainties: { type: "array", items: { type: "string" } }, input_revisions: { type: "object" } } } },
  { name: "discrepancy__create", command_kind: "discrepancy.create", description: "Create a visible cognition discrepancy from existing reports.", inputSchema: { type: "object", required: ["subject_ref", "report_refs", "severity", "summary"], properties: { subject_ref: { type: "string" }, report_refs: { type: "array", items: { type: "string" } }, severity: { type: "string" }, summary: { type: "string" }, participants: { type: "array" }, affected_actions: { type: "array" } }, additionalProperties: false } },
  { name: "discrepancy__advance", command_kind: "discrepancy.advance", description: "Advance a discrepancy into clarification or negotiation.", inputSchema: { type: "object", required: ["discrepancy_id", "status"], properties: { discrepancy_id: { type: "string" }, status: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "discrepancy__resolve", command_kind: "discrepancy.resolve", description: "Resolve a discrepancy by consensus, dismissal or explicit override (main-authority only).", inputSchema: { type: "object", required: ["discrepancy_id", "kind"], properties: { discrepancy_id: { type: "string" }, kind: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "contract__propose", command_kind: "contract.propose", description: "Propose a contract with explicit slot and agent_id participants.", inputSchema: commandSchema("contract.propose") },
  { name: "contract__accept", command_kind: "contract.accept", description: "Accept a specific contract proposal digest as a participant slot.", inputSchema: { type: "object", required: ["proposal_id", "participant_slot", "proposal_digest"], properties: { proposal_id: { type: "string" }, participant_slot: { type: "string" }, proposal_digest: { type: "string" } }, additionalProperties: false } },
  { name: "contract__accept_proxy", command_kind: "contract.accept_proxy", description: "Accept a contract slot through an explicit main-authority proxy.", inputSchema: { type: "object", required: ["proposal_id", "participant_slot_id", "proposal_digest"], properties: { proposal_id: { type: "string" }, participant_slot_id: { type: "string" }, proposal_digest: { type: "string" }, proxy_policy_ref: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "contract__reject", command_kind: "contract.reject", description: "Reject a proposed contract as its participating agent.", inputSchema: { type: "object", required: ["proposal_id", "proposal_digest", "reason"], properties: { proposal_id: { type: "string" }, proposal_digest: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array" } }, additionalProperties: false } },
  { name: "contract__withdraw", command_kind: "contract.withdraw", description: "Withdraw a still-proposed contract created by this agent.", inputSchema: { type: "object", required: ["proposal_id", "reason"], properties: { proposal_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "durability__reconcile", command_kind: "durability.reconcile", description: "Retry a failed checkpoint materialization after the project is completed (main-authority only).", inputSchema: { type: "object", required: ["reason"], properties: { scope_refs: { type: "array", items: { type: "string" } }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "inbox__claim", command_kind: "inbox.claim", description: "Claim this agent's inbox summaries; fetch a message to read its full payload.", inputSchema: commandSchema("inbox.claim") },
  { name: "inbox__fetch", command_kind: "inbox.fetch", description: "Read a received message's full payload, reply link and response obligations by message_id.", inputSchema: commandSchema("inbox.fetch") },
  { name: "inbox__presented", command_kind: "inbox.presented", description: "Record a presentation statement with optional evidence metadata; this does not verify evidence strength.", inputSchema: commandSchema("inbox.presented") },
  { name: "inbox__ack", command_kind: "inbox.ack", description: "Acknowledge a received delivery; this does not fulfill its response obligation.", inputSchema: commandSchema("inbox.ack") },
  { name: "message__send", command_kind: "message.send", description: "Send a message to one agent. To reply, set in_reply_to to the received message_id.", inputSchema: commandSchema("message.send", true) },
  { name: "message__respond", command_kind: "message.respond", description: "Fulfill a received response obligation using the message_id of an already-sent linked reply.", inputSchema: commandSchema("message.respond") },
  { name: "context__project_read", command_kind: "context.project_read", description: "Read this agent's identity, role, scope capabilities, owned and open tasks with revisions, execution scopes and dependencies needed to begin. The contracts each owned task depends on and the versions in force are read back with it.", inputSchema: { type: "object", additionalProperties: false } },
  { name: "project__configure", command_kind: "project.configure", description: "Enable or disable project-level automatic worker wake for future coordination plans (main-authority only).", inputSchema: { type: "object", required: ["policy_patch", "reason"], properties: { policy_patch: { type: "object", properties: { auto_wake_multi_agent: { type: "boolean" } }, additionalProperties: false }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "decision__propose", command_kind: "user_decision.propose", description: "Propose a decision that requires user input (main-authority only).", inputSchema: { type: "object", required: ["kind", "proposal_ref", "choices", "summary"], properties: { kind: { type: "string" }, proposal_ref: { type: "string" }, choices: { type: "array", items: { type: "object" } }, summary: { type: "string" }, proposal_digest: { type: "string" }, expected_revisions: { type: "object" } }, additionalProperties: false } },
  { name: "project__completion_propose", command_kind: "project.completion.propose.main", description: "Propose project completion for user confirmation (main-authority only).", inputSchema: { type: "object", required: ["objective_ref"], properties: { objective_ref: { type: "string" }, outstanding_summary: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, expected_project_revision: { type: "integer" } }, additionalProperties: false } },
  { name: "coordination__plan", command_kind: "coordination.plan", description: "Create Main-owned task assignments and durable inbox messages.", inputSchema: commandSchema("coordination.plan") },
  { name: "coordination__takeover", command_kind: "coordination.takeover", description: "Explicitly let Main take over a worker assignment after recording the reason (main-authority only).", inputSchema: { type: "object", required: ["assignment_id", "takeover_reason"], properties: { assignment_id: { type: "string" }, takeover_reason: { type: "string" } }, additionalProperties: false } },
];

class HttpTransport {
  public constructor(private readonly baseUrl: string, private readonly projectId?: string) {}

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
        ...(this.projectId ? { "tsunagou-project-id": this.projectId } : {}),
      },
      body: JSON.stringify(envelope),
    });
    const body = (await response.json().catch(() => ({}))) as {
      command_hash?: string;
      result?: unknown;
      detail?: { code?: string; blockers?: unknown[] };
    };
    if (!response.ok) {
      const code = body.detail?.code ?? `http_${response.status}`;
      const failure = new Error(`tsunagou_error:${code}`);
      // Keep the daemon's structured detail (violations / allowed / next_steps / holders)
      // so the agent learns *what* to fix, not just that it failed. This bridge surfaces
      // the detail itself, so the code stays clean for the guidance lookup below.
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

type RoutedConfig = ReturnType<typeof config> & {
  conversationId?: string;
  projectId?: string;
  desktopEndpoint?: string;
};

// Remember only the metadata transport mode, never a conversation credential.
// Once a legacy fixed config proves it is a metadata host, later calls cannot
// fall back to its shared bootstrap file by omitting the conversation id.
let observedHostMetaKey: string | undefined;

function configurationForRequest(request: CallToolRequest): RoutedConfig {
  const routingDir = env("TSUNAGOU_ROUTING_DIR");
  if (!routingDir) {
    const fixed = config();
    const metaKey = fixed.hostMetaKey || observedHostMetaKey || (request.params._meta?.["ai.opencode/sessionID"] !== undefined
      ? "ai.opencode/sessionID" : "threadId");
    const rawIdentity = request.params._meta?.[metaKey];
    const identity = typeof rawIdentity === "string" && rawIdentity ? rawIdentity : undefined;
    if ((fixed.hostMetaKey || observedHostMetaKey || metaKey !== "threadId") && !identity) {
      throw new Error("conversation_metadata_required");
    }
    if (metaKey !== "threadId" && identity) observedHostMetaKey = metaKey;
    const manifest = join(fixed.projectRoot, ".tsunagou", "project.json");
    const projectId = fixed.projectRoot && existsSync(manifest)
      ? JSON.parse(readFileSync(manifest, "utf8")).project_id as string : undefined;
    if (identity && metaKey !== "threadId") {
      const binding = hash("conversation_id:" + identity);
      let sessionFile = join(fixed.stateDir, "sessions", "bridge-session-" + binding.slice(0, 32) + ".json");
      if (fixed.sessionFile) {
        // A shared OpenCode configuration can point at the first conversation's
        // bootstrap file. Reuse it only for its proven owner, including a saved
        // pending request whose credential response was lost before restart.
        const prior = loadSession(fixed.sessionFile);
        const pending = readPrivateJson(`${fixed.sessionFile}.pending.json`) as
          { conversation_binding_digest?: unknown } | undefined;
        const ticket = fixed.ticketFile && existsSync(fixed.ticketFile) ? readTicketFile(fixed.ticketFile) : undefined;
        const owner = prior?.conversation_binding_digest ?? prior?.host_conversation_id_digest
          ?? pending?.conversation_binding_digest ?? (ticket ? hash("conversation_id:" + ticket.conversation_id) : undefined);
        if (owner === binding) sessionFile = fixed.sessionFile;
      }
      return { ...fixed, hostMetaKey: metaKey, sessionFile, projectId, conversationId: identity };
    }
    return { ...fixed, projectId, conversationId: identity };
  }
  const rawIdentity = request.params._meta?.threadId;
  const identity = typeof rawIdentity === "string" && rawIdentity ? rawIdentity : undefined;
  // Shared MCP processes may serve many chats. Their process environment must
  // never pick an identity for a request whose host metadata is absent.
  if (!identity) throw new Error("host_request_identity_required");
  const path = join(routingDir, hash(identity) + ".json");
  if (!existsSync(path)) throw new Error("not_enrolled:run_agent_connect");
  let route: Record<string, unknown>;
  try { route = JSON.parse(readFileSync(path, "utf8")); }
  catch { throw new Error("private_route_invalid"); }
  if (route.format_version !== 1 || route.conversation_id !== identity) throw new Error("host_route_identity_mismatch");
  for (const key of ["project_id", "project_root", "daemon_state_dir", "ticket_file", "session_file", "state_dir"]) {
    if (typeof route[key] !== "string" || !route[key]) throw new Error("private_route_invalid");
  }
  return {
    httpUrl: "", daemonStateDir: route.daemon_state_dir as string,
    ticketFile: route.ticket_file as string, sessionFile: route.session_file as string,
    stateDir: route.state_dir as string, projectRoot: route.project_root as string,
    projectId: route.project_id as string, conversationId: identity,
    hostIdCandidates: [], hostMetaKey: "", desktopWake: true,
    desktopEndpoint: process.env.CODEX_APP_TOOLS_PIPE_PATH || (route.endpoint as string | undefined),
  };
}

async function executeTool(cfg: RoutedConfig, kind: string, payload: Record<string, unknown>, commandId: string, restoreOnly = false): Promise<unknown> {
  let ticket = cfg.ticketFile && existsSync(cfg.ticketFile) ? readTicketFile(cfg.ticketFile) : undefined;
  const expectedBinding = cfg.conversationId ? hash("conversation_id:" + cfg.conversationId) : undefined;
  const hostIdentity = cfg.conversationId ? { digest: expectedBinding!, envName: "_meta.threadId" } : readHostIdentity(cfg.hostIdCandidates);
  if (cfg.conversationId && ticket && ticket.conversation_id !== cfg.conversationId) {
    if (!cfg.hostMetaKey) throw new Error("host_conversation_mismatch");
    // A project-shared metadata bridge must leave another conversation's
    // ticket for that conversation, while still using its own saved session.
    ticket = undefined;
  }
  const ticketBinding = ticket ? hash("conversation_id:" + ticket.conversation_id) : undefined;
  const fileIdentity = hostIdentity?.digest ?? ticketBinding;
  const sessionFile = cfg.sessionFile ?? (fileIdentity
    ? join(cfg.stateDir, "sessions", "bridge-session-" + fileIdentity.slice(0, 32) + ".json") : undefined);
  if (!sessionFile) throw new Error("not_enrolled:no_ticket_or_session_file");
  const prior = loadSession(sessionFile);
  const conversationBindingDigest = expectedBinding ?? ticketBinding ?? prior?.conversation_binding_digest ?? fileIdentity;
  if (!conversationBindingDigest) throw new Error("conversation_identity_required_for_session_file");
  // No global session cache: each call routes first, then loads only its private
  // credential. Handoff's mutex/journal fences concurrent rotation and replay.
  const hostDigest = hostIdentity?.digest ?? prior?.host_conversation_id_digest ?? ticketBinding;
  const endpoint = cfg.desktopWake ? cfg.desktopEndpoint ?? process.env.CODEX_APP_TOOLS_PIPE_PATH : undefined;
  const refresh = endpoint ? {
    provider: "codex_desktop_app" as const, endpoint, host_generation: hash(endpoint),
  } : undefined;
  const baseUrl = readDaemonUrl(cfg.daemonStateDir) ?? cfg.httpUrl;
  if (!baseUrl) throw new Error("daemon_endpoint_not_configured");
  const handoff = new CredentialHandoff({
    baseUrl, projectId: cfg.projectId, protocolVersion: PROTOCOL_VERSION, schemaBundleDigest: SCHEMA_BUNDLE_DIGEST,
    sessionFile, conversationBindingDigest, hostDigest,
  });
  const recover = async (forceReconnect = false): Promise<PersistedSession> => {
    const current = await handoff.recover({
      ticket, ticketFile: cfg.ticketFile || undefined,
      forceReconnect,
      baseline: buildBaseline({
        hostDigest, projectDigest: readProjectDigest(cfg.projectRoot), tools: TOOLS,
        continuityRefs: prior ? continuityRefs(prior.host_conversation_id_digest, hostDigest)
          : ticket ? ["ticket:bound_conversation"] : undefined,
      }),
      hostBindingRefresh: refresh,
    });
    if (!current) throw new Error("not_enrolled:no_ticket_or_session_file");
    return current;
  };
  let session = await recover();
  if (refresh && session.host_binding_generation !== refresh.host_generation) session = await recover();
  if (refresh && cfg.conversationId && env("TSUNAGOU_ROUTING_DIR")) {
    const routeFile = join(env("TSUNAGOU_ROUTING_DIR"), hash(cfg.conversationId) + ".json");
    await withPrivateFileLock(routeFile, () => {
      const route = JSON.parse(readFileSync(routeFile, "utf8"));
      const saved = loadSession(sessionFile);
      if (route.conversation_id === cfg.conversationId && saved?.host_binding_generation === refresh.host_generation
          && route.endpoint !== refresh.endpoint) writePrivateJson(routeFile, { ...route, endpoint: refresh.endpoint });
    });
  }
  if (restoreOnly) return undefined;
  const transport = new HttpTransport(baseUrl, cfg.projectId);
  let result: unknown;
  try {
    result = await transport.dispatch(kind, payload, session, commandId);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!message.includes("authentication_failed") && !message.includes("stale_connection_epoch")
        && !message.includes("session_not_found")) throw error;
    session = await recover(true);
    result = await transport.dispatch(kind, payload, session, commandId);
  }
  return result;
}

let restoringBindings = false;
async function restoreDesktopBindings(): Promise<void> {
  const directory = env("TSUNAGOU_ROUTING_DIR");
  const endpoint = env("CODEX_APP_TOOLS_PIPE_PATH");
  if (!directory || !endpoint || !existsSync(directory) || restoringBindings) return;
  restoringBindings = true;
  try {
    // A shared bridge is a credential transport for already enrolled chats.
    // Restore their endpoint before a wake needs it; no task/inbox is read and
    // this is not evidence that their LLMs have started or processed anything.
    for (const name of readdirSync(directory)) {
      if (!/^[a-f0-9]{64}\.json$/.test(name)) continue;
      try {
        const route = JSON.parse(readFileSync(join(directory, name), "utf8"));
        if (typeof route.conversation_id !== "string" || hash(route.conversation_id) + ".json" !== name
            || typeof route.session_file !== "string") continue;
        const prior = loadSession(route.session_file);
        if (!prior || prior.host_binding_generation === hash(endpoint)) continue;
        const cfg = configurationForRequest({ method: "tools/call", params: {
          name: "context__project_read", _meta: { threadId: route.conversation_id },
        } });
        await executeTool(cfg, "context.project_read", {}, randomUUID(), true);
      } catch {
        // One stopped project must not block others; the next real call can
        // retry its pending credential exchange after that daemon returns.
        process.stderr.write("[tsunagou-bridge] binding_restore_pending\n");
      }
    }
  } finally {
    restoringBindings = false;
  }
}

async function main(): Promise<void> {
  const server = new Server(
    { name: "tsunagou", version: "0.1.0" },
    {
      capabilities: { tools: {} },
      instructions: "Read context__project_read and inbox on each coordination turn. "
        + "Use task__begin before work, task__submit for delivery, task__block before waiting. "
        + "Main handles routine worker requests within existing authorization; only major decisions require the user.",
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
      const cfg = configurationForRequest(request);
      const args = { ...((request.params.arguments ?? {}) as Record<string, unknown>) };
      const commandId = typeof args.command_id === "string" && args.command_id.trim() ? args.command_id.trim() : randomUUID();
      delete args.command_id;
      // A report has to say which contract versions it was based on. The versions this
      // session actually read are remembered from context.project_read below, so the
      // model never has to repeat them (see declareContracts).
      if (tool.command_kind === "cognition.report") declareContracts(args, "input_revisions");
      const result = await executeTool(cfg, tool.command_kind, args, commandId);
      void restoreDesktopBindings();
      if (tool.command_kind === "context.project_read") rememberContracts(result);
      return { content: [{ type: "text" as const, text: JSON.stringify(result) }] };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const detail = (error as { detail?: unknown } | null | undefined)?.detail;
      // Only our typed errors reach the model, never raw filesystem/network data.
      const safe = /^(?:tsunagou_error:|[a-z][a-z0-9_]*(?::[a-z0-9_]+)?$)/.test(message)
        ? message : "bridge_request_failed";
      return { content: [{ type: "text" as const, text: JSON.stringify(buildToolError(safe, detail)) }], isError: true };
    }
  });
  await server.connect(new StdioServerTransport());
  void restoreDesktopBindings();
  process.stderr.write("[tsunagou-bridge] ready; credentials are selected per request\n");
}

main().catch(() => {
  process.stderr.write("[tsunagou-bridge] startup_failed\n");
  process.exit(1);
});
