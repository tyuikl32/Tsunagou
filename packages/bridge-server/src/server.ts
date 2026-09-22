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
import { existsSync, readdirSync, readFileSync, writeFileSync, mkdirSync, unlinkSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

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

interface SessionCredential {
  agent_id: string;
  session_id: string;
  connection_epoch: number;
  secret_token: string;
  reconnect_nonce: string;
  baseline_status: string;
}

interface PersistedSession extends SessionCredential {
  host_conversation_id_digest?: string;
  conversation_binding_digest?: string;
}

interface TicketFile {
  installation_id: string;
  conversation_id: string;
  secret: string;
  requested_role?: "worker" | "main";
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
  { name: "task__submit", command_kind: "task.submit", description: "Submit the work for a started attempt (execution command).", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, summary: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, artifact_refs: { type: "array", items: { type: "string" } }, workspace_result_ref: { type: "string" } } } },
  { name: "task__self_accept", command_kind: "task.self_accept", description: "Self-accept a result when task policy permits it.", inputSchema: { type: "object", required: ["task_id", "result_id", "result_digest"], properties: { task_id: { type: "string" }, result_id: { type: "string" }, result_digest: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "resource__intent", command_kind: "resource.intent", description: "Declare the resources required by a task attempt.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "resources"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, resources: { type: "array", items: { type: "object" } }, scope_digest: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "resource__acquire", command_kind: "resource.acquire", description: "Acquire the lease set for a declared resource intent.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "intent_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, intent_id: { type: "string" }, intent_revision: { type: "integer" }, scope_digest: { type: "string" } }, additionalProperties: false } },
  { name: "resource__release", command_kind: "resource.release", description: "Release resources held by a task attempt.", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "resource__renew", command_kind: "resource.renew", description: "Renew the active resource lease for a running attempt.", inputSchema: { type: "object", required: ["lease_set_id", "task_id", "attempt_id"], properties: { lease_set_id: { type: "string" }, task_id: { type: "string" }, attempt_id: { type: "string" }, scope_digest: { type: "string" } }, additionalProperties: false } },
  { name: "workspace__select", command_kind: "workspace.select", description: "Select an isolation driver for the task attempt.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "driver_kind"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, driver_kind: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, hard_constraints: { type: "array", items: { type: "string" } }, input_digest: { type: "string" }, risk_submission_ref: { type: "string" } }, additionalProperties: false } },
  { name: "workspace__prepare", command_kind: "workspace.prepare", description: "Prepare the selected workspace and record its baseline.", inputSchema: { type: "object", required: ["task_id", "attempt_id", "decision_id", "baseline"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, decision_id: { type: "string" }, input_digest: { type: "string" }, root_binding_refs: { type: "array", items: { type: "string" } }, repository_id: { type: "string" }, external_locator: { type: "string" }, baseline: { type: "object" } }, additionalProperties: false } },
  { name: "workspace__result", command_kind: "workspace.result", description: "Record the resulting workspace manifest after execution.", inputSchema: { type: "object", required: ["workspace_id", "task_id", "attempt_id", "baseline_digest"], properties: { workspace_id: { type: "string" }, task_id: { type: "string" }, attempt_id: { type: "string" }, baseline_digest: { type: "string" }, changed_paths: { type: "array", items: { type: "string" } }, commit_refs: { type: "array", items: { type: "string" } }, patch_artifact_ref: { type: "string" }, untracked_summary: { type: "array", items: { type: "object" } }, validation_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "task__review_accept", command_kind: "task.review.accept", description: "Accept a submitted task result as the designated reviewer.", inputSchema: { type: "object", required: ["task_id", "result_id", "result_digest", "slot_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, result_id: { type: "string" }, result_digest: { type: "string" }, slot_id: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "task__review_request_changes", command_kind: "task.review.request_changes", description: "Request changes to a submitted task result as the designated reviewer.", inputSchema: { type: "object", required: ["task_id", "result_id", "result_digest", "slot_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, result_id: { type: "string" }, result_digest: { type: "string" }, slot_id: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "cognition__report", command_kind: "cognition.report", description: "Submit an explicit cognition report (claims, assumptions, uncertainties).", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, claims: { type: "array", items: { type: "object", required: ["subject_key"], properties: { subject_key: { type: "string" }, subject: { type: "string" }, claim_type: { type: "string" }, equality_key: { type: "string" }, value: {}, evidence_refs: { type: "array", items: { type: "string" } } } } }, assumptions: { type: "array", items: { type: "string" } }, uncertainties: { type: "array", items: { type: "string" } } } } },
  { name: "discrepancy__create", command_kind: "discrepancy.create", description: "Create a visible cognition discrepancy from existing reports.", inputSchema: { type: "object", required: ["subject_ref", "report_refs", "severity", "summary"], properties: { subject_ref: { type: "string" }, report_refs: { type: "array", items: { type: "string" } }, severity: { type: "string" }, summary: { type: "string" }, participants: { type: "array" }, affected_actions: { type: "array" } }, additionalProperties: false } },
  { name: "discrepancy__advance", command_kind: "discrepancy.advance", description: "Advance a discrepancy into clarification or negotiation.", inputSchema: { type: "object", required: ["discrepancy_id", "status"], properties: { discrepancy_id: { type: "string" }, status: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "discrepancy__resolve", command_kind: "discrepancy.resolve", description: "Resolve a discrepancy by consensus, dismissal or explicit override (main-authority only).", inputSchema: { type: "object", required: ["discrepancy_id", "kind"], properties: { discrepancy_id: { type: "string" }, kind: { type: "string" }, reason: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "contract__propose", command_kind: "contract.propose", description: "Propose a coordination contract with required/optional participants.", inputSchema: { type: "object", properties: { payload: { type: "object" }, participants_required: { type: "array" }, participants_optional: { type: "array" } }, additionalProperties: false } },
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
  { name: "context__project_read", command_kind: "context.project_read", description: "Read this agent's project context: identity, role, scope capabilities and owned tasks.", inputSchema: { type: "object", additionalProperties: false } },
  { name: "decision__propose", command_kind: "user_decision.propose", description: "Propose a decision that requires user input (main-authority only).", inputSchema: { type: "object", required: ["kind", "proposal_ref", "choices", "summary"], properties: { kind: { type: "string" }, proposal_ref: { type: "string" }, choices: { type: "array", items: { type: "object" } }, summary: { type: "string" }, proposal_digest: { type: "string" }, expected_revisions: { type: "object" } }, additionalProperties: false } },
  { name: "project__completion_propose", command_kind: "project.completion.propose.main", description: "Propose project completion for user confirmation (main-authority only).", inputSchema: { type: "object", required: ["objective_ref"], properties: { objective_ref: { type: "string" }, outstanding_summary: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, expected_project_revision: { type: "integer" } }, additionalProperties: false } },
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
      throw new Error(`tsunagou_error:${code}`);
    }
    return body.result ?? {};
  }

  /** Redeem a one-time ticket: T-principal, no session headers, ticket as bearer. */
  public async enroll(ticket: TicketFile, baseline: Record<string, unknown>): Promise<SessionCredential> {
    const envelope = {
      command_id: randomUUID(),
      protocol_version: PROTOCOL_VERSION,
      schema_bundle_digest: SCHEMA_BUNDLE_DIGEST,
      payload: {
        installation_id: ticket.installation_id,
        conversation_evidence: { conversation_id: ticket.conversation_id },
        probe_payload: baseline,
      },
    };
    const response = await fetch(`${this.baseUrl}/api/v1/commands/agent.enroll`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${ticket.secret}` },
      body: JSON.stringify(envelope),
    });
    const body = (await response.json().catch(() => ({}))) as {
      result?: SessionCredential;
      detail?: { code?: string };
    };
    if (!response.ok || body.result === undefined) {
      const code = body.detail?.code ?? `http_${response.status}`;
      throw new Error(`tsunagou_enroll_error:${code}`);
    }
    return body.result;
  }

  /** Resume an already-attached session with a fresh one-time ticket (T principal). */
  public async rebind(ticket: TicketFile, targetAgentId: string, baseline: Record<string, unknown>): Promise<SessionCredential> {
    const envelope = {
      command_id: randomUUID(),
      protocol_version: PROTOCOL_VERSION,
      schema_bundle_digest: SCHEMA_BUNDLE_DIGEST,
      payload: {
        installation_id: ticket.installation_id,
        conversation_evidence: { conversation_id: ticket.conversation_id },
        target_agent_id: targetAgentId,
        probe_payload: baseline,
      },
    };
    const response = await fetch(`${this.baseUrl}/api/v1/commands/session.rebind`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${ticket.secret}` },
      body: JSON.stringify(envelope),
    });
    const body = (await response.json().catch(() => ({}))) as {
      result?: SessionCredential;
      detail?: { code?: string };
    };
    if (!response.ok || body.result === undefined) {
      const code = body.detail?.code ?? `http_${response.status}`;
      throw new Error(`tsunagou_rebind_error:${code}`);
    }
    return body.result;
  }

  /** Reconnect an attached session after a restart (D principal): prove we still
   *  hold the session credential at the expected epoch, and rotate token/nonce.
   *  No ticket is involved and no baseline is re-sent — this is a pure credential
   *  rotation, not a re-admission, so the session keeps its current status. */
  public async reconnect(session: SessionCredential): Promise<SessionCredential> {
    const envelope = {
      command_id: randomUUID(),
      protocol_version: PROTOCOL_VERSION,
      schema_bundle_digest: SCHEMA_BUNDLE_DIGEST,
      payload: {
        reconnect_nonce: session.reconnect_nonce,
        expected_connection_epoch: session.connection_epoch,
      },
    };
    const response = await fetch(`${this.baseUrl}/api/v1/commands/session.reconnect`, {
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
      result?: SessionCredential;
      detail?: { code?: string };
    };
    if (!response.ok || body.result === undefined) {
      const code = body.detail?.code ?? `http_${response.status}`;
      throw new Error(`tsunagou_reconnect_error:${code}`);
    }
    return body.result;
  }
}

function loadSession(path: string): PersistedSession | undefined {
  if (!existsSync(path)) return undefined;
  const raw = JSON.parse(readFileSync(path, "utf-8")) as PersistedSession;
  if (typeof raw.session_id !== "string" || typeof raw.secret_token !== "string") return undefined;
  return raw;
}

function saveSession(
  path: string, session: SessionCredential, hostDigest: string | undefined,
  conversationBindingDigest: string | undefined,
): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify({
    ...session,
    host_conversation_id_digest: hostDigest,
    conversation_binding_digest: conversationBindingDigest,
  }, null, 2) + "\n", "utf-8");
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

  const ticketPresent = cfg.ticketFile !== "" && existsSync(cfg.ticketFile);
  const bootstrapTicket = ticketPresent ? readTicketFile(cfg.ticketFile) : undefined;
  // A bridge credential belongs to one host conversation. Never use a global
  // ~/.tsunagou/bridge-session.json: when Codex/OpenCode launches several
  // conversations from the same IDE, that file would silently make them one
  // worker. Explicit TSUNAGOU_SESSION_FILE remains supported for a caller
  // that deliberately provisions one private file per conversation.
  const conversationBindingDigest = bootstrapTicket
    ? hash(`conversation_id:${bootstrapTicket.conversation_id}`)
    : hostDigest;
  const sessionFile = cfg.sessionFile ?? (
    conversationBindingDigest
      ? join(cfg.stateDir, "sessions", `bridge-session-${conversationBindingDigest.slice(0, 32)}.json`)
      : undefined
  );
  let session: PersistedSession | undefined = sessionFile ? loadSession(sessionFile) : undefined;
  if (bootstrapTicket && session && (
      session.conversation_binding_digest !== undefined
        ? session.conversation_binding_digest !== conversationBindingDigest
        : session.host_conversation_id_digest !== conversationBindingDigest
  )) {
    session = undefined;
  }
  let observedContinuity = continuityRefs(session?.host_conversation_id_digest, hostDigest);

  if (ticketPresent) {
    try {
      const ticket = bootstrapTicket!;
      // Codex does not expose its session id to spawned MCP servers (verified:
      // no CODEX_* env names are set), so the host conversation identity is the
      // ticket's bound conversation_id — a real host session id observed by the
      // orchestrator. It is not caller self-assertion: the ticket secret already
      // binds this exact conversation, and redeem_ticket rejects a forged id with
      // enrollment_identity_mismatch.
      hostDigest ??= hash(`conversation_id:${ticket.conversation_id}`);
      if (session !== undefined) {
        // Resume: compare the persisted digest to this launch's to observe
        // identity.continuity_evidence honestly (same digest across a resume).
        observedContinuity = continuityRefs(session.host_conversation_id_digest, hostDigest);
      } else if (hostDigest !== undefined) {
        // On first admission, the one-time ticket itself is bound to this
        // conversation identity. It is the continuity proof for this new
        // session; later launches use the persisted digest plus nonce/epoch.
        observedContinuity = ["ticket:bound_conversation"];
      }
      const baseline = buildBaseline({ hostDigest, projectDigest, continuityRefs: observedContinuity, tools: TOOLS });
      const credential = session !== undefined
        ? await transport.rebind(ticket, session.agent_id, baseline)
        : await transport.enroll(ticket, baseline);
      session = { ...credential, host_conversation_id_digest: hostDigest };
      if (sessionFile === undefined) throw new Error("conversation_identity_required_for_session_file");
      saveSession(sessionFile, credential, hostDigest, conversationBindingDigest);
      unlinkSync(cfg.ticketFile); // single-use: consume the private ticket after redemption
    } catch (error) {
      session = undefined;
      process.stderr.write(`[tsunagou-bridge] bootstrap failed: ${error instanceof Error ? error.message : String(error)}\n`);
    }
  } else if (session !== undefined) {
    try {
      // No ticket on restart: reconnect the persisted session (D principal) so the
      // credential rotates and the epoch advances — the bridge's own recovery path,
      // instead of silently reusing a possibly-stale credential. There is no new
      // env/ticket identity here, so the persisted host digest is carried forward.
      hostDigest ??= session.host_conversation_id_digest;
      if (hostDigest !== undefined && session.host_conversation_id_digest !== undefined
          && hostDigest !== session.host_conversation_id_digest) {
        throw new Error("host_conversation_identity_mismatch");
      }
      const credential = await transport.reconnect(session);
      session = { ...credential, host_conversation_id_digest: hostDigest };
      if (sessionFile === undefined) throw new Error("conversation_identity_required_for_session_file");
      saveSession(sessionFile, credential, hostDigest, session.conversation_binding_digest);
    } catch (error) {
      session = undefined;
      process.stderr.write(`[tsunagou-bridge] reconnect failed: ${error instanceof Error ? error.message : String(error)}\n`);
    }
  }

  const server = new Server({ name: "tsunagou", version: "0.1.0" }, { capabilities: { tools: {} } });

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOLS.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request: CallToolRequest) => {
    const tool = TOOLS.find((candidate) => candidate.name === request.params.name);
    if (tool === undefined) {
      return { content: [{ type: "text" as const, text: JSON.stringify({ error: "unknown_tool" }) }], isError: true };
    }
    try {
      if (session === undefined) {
        throw new Error("not_enrolled:no_ticket_or_session_file");
      }
      const args = { ...((request.params.arguments ?? {}) as Record<string, unknown>) };
      const commandId = typeof args.command_id === "string" ? args.command_id : undefined;
      if ("command_id" in args) {
        delete args.command_id;
      }
      const result = await transport.dispatch(tool.command_kind, args, session, commandId);
      return { content: [{ type: "text" as const, text: JSON.stringify(result) }] };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { content: [{ type: "text" as const, text: JSON.stringify({ error: message }) }], isError: true };
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
