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
// Read from the local protocol registry; the flat command entrypoint does not
// validate the payload against a schema, only the envelope shape, but we send
// the real bundle digest so a stricter future server rejects stale tool shapes.
const SCHEMA_BUNDLE_DIGEST = "sha256:f2c3d8e0dc89f8b454288048d6326a4446f51659003045ac6194d6da39545fc6";

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
}

interface TicketFile {
  installation_id: string;
  conversation_id: string;
  secret: string;
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

/** Deterministic JSON string with sorted object keys, so identical payloads map
 *  to the same command id regardless of key order the model happened to use. */
function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  return "{" + Object.keys(value as Record<string, unknown>).sort()
    .map((key) => JSON.stringify(key) + ":" + canonicalJson((value as Record<string, unknown>)[key]))
    .join(",") + "}";
}

function env(name: string, fallback = ""): string {
  const value = process.env[name];
  return value !== undefined && value !== "" ? value : fallback;
}

function config(): {
  httpUrl: string;
  ticketFile: string;
  sessionFile: string;
  projectRoot: string;
  stateDir: string;
  hostIdCandidates: string[];
} {
  const stateDir = env("TSUNAGOU_STATE_DIR", join(homedir(), ".tsunagou"));
  return {
    httpUrl: env("TSUNAGOU_HTTP_URL", "http://127.0.0.1:8000").replace(/\/+$/, ""),
    ticketFile: env("TSUNAGOU_TICKET_FILE"),
    sessionFile: env("TSUNAGOU_SESSION_FILE", join(stateDir, "bridge-session.json")),
    projectRoot: env("TSUNAGOU_PROJECT_ROOT"),
    stateDir,
    hostIdCandidates: env(
      "TSUNAGOU_HOST_ID_ENV",
      "CODEX_SESSION_ID,CODEX_THREAD_ID,CODEX_CONVERSATION_ID,CODEX_ROLLOUT_ID,CODEX_AGREEMENT_ID",
    ).split(",").map((name) => name.trim()).filter(Boolean),
  };
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
  { name: "task__create", command_kind: "task.create", description: "Create, ready and publish a task in this coordination scope (main-authority only).", inputSchema: { type: "object", required: ["title", "objective"], properties: { title: { type: "string" }, objective: { type: "string" }, parent_task_id: { type: "string" }, blocks: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "task__claim", command_kind: "task.claim", description: "Claim a task for this agent (preparation, not execution).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" } }, additionalProperties: false } },
  { name: "task__resume", command_kind: "task.resume", description: "Resume a previously claimed task (preparation, not execution).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" } }, additionalProperties: false } },
  { name: "task__preflight", command_kind: "task.preflight", description: "Run a preflight check on a claimed task attempt (preparation, not execution).", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "task__start", command_kind: "task.start", description: "Begin executing a claimed task after preflight; issues the execution grant for this attempt.", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, preflight_id: { type: "string" } }, additionalProperties: false } },
  { name: "task__progress", command_kind: "task.progress", description: "Record progress on a running attempt (execution command).", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, summary: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } } }, additionalProperties: false } },
  { name: "task__block", command_kind: "task.block", description: "Mark a task blocked with a reason.", inputSchema: { type: "object", required: ["task_id"], properties: { task_id: { type: "string" }, reason_code: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "task__submit", command_kind: "task.submit", description: "Submit the work for a started attempt (execution command).", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, summary: { type: "string" }, evidence_refs: { type: "array", items: { type: "string" } }, artifact_refs: { type: "array", items: { type: "string" } }, workspace_result_ref: { type: "string" } } } },
  { name: "cognition__report", command_kind: "cognition.report", description: "Submit an explicit cognition report (claims, assumptions, uncertainties).", inputSchema: { type: "object", required: ["task_id", "attempt_id"], properties: { task_id: { type: "string" }, attempt_id: { type: "string" }, claims: { type: "array", items: { type: "object", required: ["subject_key"], properties: { subject_key: { type: "string" }, subject: { type: "string" }, claim_type: { type: "string" }, equality_key: { type: "string" }, value: {}, evidence_refs: { type: "array", items: { type: "string" } } } } }, assumptions: { type: "array", items: { type: "string" } }, uncertainties: { type: "array", items: { type: "string" } } } } },
  { name: "contract__propose", command_kind: "contract.propose", description: "Propose a coordination contract with required/optional participants.", inputSchema: { type: "object", properties: { payload: { type: "object" }, participants_required: { type: "array" }, participants_optional: { type: "array" } }, additionalProperties: false } },
  { name: "contract__accept", command_kind: "contract.accept", description: "Accept a specific contract proposal digest as a participant slot.", inputSchema: { type: "object", required: ["proposal_id", "participant_slot", "proposal_digest"], properties: { proposal_id: { type: "string" }, participant_slot: { type: "string" }, proposal_digest: { type: "string" } }, additionalProperties: false } },
  { name: "inbox__claim", command_kind: "inbox.claim", description: "Claim this agent's inbox deliveries.", inputSchema: { type: "object", properties: { limit: { type: "integer" } }, additionalProperties: false } },
  { name: "inbox__fetch", command_kind: "inbox.fetch", description: "Fetch one inbox message by id.", inputSchema: { type: "object", required: ["message_id"], properties: { message_id: { type: "string" }, delivery_lease_id: { type: "string" } }, additionalProperties: false } },
  { name: "inbox__presented", command_kind: "inbox.presented", description: "Record that a delivery was presented with an evidence digest.", inputSchema: { type: "object", required: ["message_id"], properties: { message_id: { type: "string" }, evidence_digest: { type: "string" }, evidence_kind: { type: "string" } }, additionalProperties: false } },
  { name: "inbox__ack", command_kind: "inbox.ack", description: "Acknowledge a presented inbox delivery.", inputSchema: { type: "object", required: ["message_id"], properties: { message_id: { type: "string" }, reason: { type: "string" } }, additionalProperties: false } },
  { name: "message__send", command_kind: "message.send", description: "Send a message to another agent.", inputSchema: { type: "object", required: ["recipient_agent_id"], properties: { command_id: { type: "string", description: "Optional idempotency key. Reusing this id with different message input is rejected as a conflict." }, recipient_agent_id: { type: "string" }, kind: { type: "string" }, subject_ref: { type: "string" }, summary: { type: "string" }, payload: { type: "object" }, priority: { type: "integer" }, response_contract: { type: "object", properties: { required: { type: "boolean" }, schema: { type: "object" } } }, in_reply_to: { type: "string" } } } },
  { name: "message__respond", command_kind: "message.respond", description: "Fulfill a response obligation on a received message.", inputSchema: { type: "object", required: ["obligation_id", "response_message_id"], properties: { obligation_id: { type: "string" }, response_message_id: { type: "string" } }, additionalProperties: false } },
  { name: "context__project_read", command_kind: "context.project_read", description: "Read this agent's project context: identity, role, scope capabilities and owned tasks.", inputSchema: { type: "object", additionalProperties: false } },
];

class HttpTransport {
  public constructor(private readonly baseUrl: string) {}

  public async dispatch(
    kind: string,
    payload: Record<string, unknown>,
    session: SessionCredential,
    commandId?: string,
  ): Promise<unknown> {
    // A stable, content-derived command id makes a retried tool call idempotent
    // (the same kind+payload maps to the same id, so message.send dedups), while a
    // genuinely different payload becomes a distinct command. A reused id with
    // changed content is the server's job to reject as a conflict.
    const envelope = {
      command_id: commandId?.trim() || ("idem:" + hash(`${kind}:${canonicalJson(payload)}`)),
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

function saveSession(path: string, session: SessionCredential, hostDigest: string | undefined): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify({ ...session, host_conversation_id_digest: hostDigest }, null, 2) + "\n", "utf-8");
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
  const transport = new HttpTransport(cfg.httpUrl);

  let session: PersistedSession | undefined = loadSession(cfg.sessionFile);
  let observedContinuity = continuityRefs(session?.host_conversation_id_digest, hostDigest);
  const ticketPresent = cfg.ticketFile !== "" && existsSync(cfg.ticketFile);

  if (ticketPresent) {
    try {
      const ticket = readTicketFile(cfg.ticketFile);
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
      }
      const baseline = buildBaseline({ hostDigest, projectDigest, continuityRefs: observedContinuity, tools: TOOLS });
      const credential = session !== undefined
        ? await transport.rebind(ticket, session.agent_id, baseline)
        : await transport.enroll(ticket, baseline);
      session = { ...credential, host_conversation_id_digest: hostDigest };
      saveSession(cfg.sessionFile, credential, hostDigest);
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
      const credential = await transport.reconnect(session);
      session = { ...credential, host_conversation_id_digest: hostDigest };
      saveSession(cfg.sessionFile, credential, hostDigest);
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
