import type { CommandEnvelope } from "@tsunagou/protocol-ts";
import type { CommandKind } from "@tsunagou/protocol-ts";

export const BASELINE_CAPABILITIES = [
  "identity.session_isolation",
  "identity.continuity_evidence",
  "context.project_read",
  "command.typed_tools",
  "task.lifecycle",
  "cognition.report",
  "contract.participation",
  "inbox.pull_fetch_ack",
  "response.structured",
  "recovery.idempotent_reconnect",
  "delivery.deduplicate",
] as const;

export type BaselineCapability = (typeof BASELINE_CAPABILITIES)[number];
export type CapabilityStatus = "supported" | "unsupported" | "unknown";
export type CapabilityStrength = "advisory" | "observed" | "enforced";

export interface HostIdentity {
  installation_id: string;
  host_kind: string;
  host_conversation_id_digest: string;
}

export interface BridgeTransport {
  send<T>(envelope: CommandEnvelope, context?: TransportContext): Promise<T>;
}

export interface BridgeFailure {
  readonly code?: string;
  readonly status?: number;
  readonly retry_after_ms?: number;
}

export interface TransportContext {
  readonly sessionId: string;
  readonly connectionEpoch: number;
  /** Private bridge-to-daemon context. It is never put in a command envelope or prompt. */
  readonly authorization?: string;
}

export interface BridgeConnection {
  readonly sessionId: string;
  readonly connectionEpoch: number;
  readonly capabilities: ReadonlySet<string>;
}

export interface BridgeOptions {
  readonly connection: BridgeConnection;
  readonly maxRetries?: number;
  readonly retryDelayMs?: number;
  /** Called only inside the bridge when a transport request is made. */
  readonly credentialProvider?: () => string | undefined;
}

export interface ConformanceCheck {
  readonly name: BaselineCapability | string;
  readonly status: CapabilityStatus;
  readonly strength?: CapabilityStrength;
  readonly evidence?: string;
}

export interface ConformanceReport {
  readonly ready: boolean;
  readonly checks: readonly ConformanceCheck[];
  readonly missing: readonly BaselineCapability[];
}

export interface HostProbeInput {
  readonly adapter_installation_id: string;
  readonly host_kind: string;
  readonly host_version: string;
  readonly host_conversation_id?: string;
  /** Sanitized keyed digest produced by the host probe; raw IDs do not cross the adapter boundary. */
  readonly host_conversation_id_digest?: string;
  readonly lifecycle_event?: string;
}

export interface HostAdapter {
  readonly kind: string;
  getIdentity(input: HostProbeInput): HostIdentity | undefined;
  probeCapabilities(input: HostProbeInput): Promise<readonly ConformanceCheck[]>;
  installTools?(input: HostProbeInput): Promise<void>;
  renderContext?(input: HostProbeInput, sections: readonly ContextSection[]): string;
  observeLifecycle?(input: HostProbeInput, event: HostLifecycleEvent): void;
  readonly enhancements?: HostEnhancements;
}

export interface HostEnhancements {
  wake?: (input: HostProbeInput) => Promise<boolean>;
  gateTool?: (input: HostProbeInput, toolName: string) => Promise<"allowed" | "denied" | "unknown">;
  observeTool?: (input: HostProbeInput, toolName: string) => Promise<boolean>;
  launch?: (input: HostProbeInput) => Promise<boolean>;
  stop?: (input: HostProbeInput) => Promise<boolean>;
}

export interface HostLifecycleEvent {
  readonly kind: "resume" | "compact" | "new" | "clear" | "fork" | "stop" | "unknown";
  /** A probe-keyed digest. Raw host conversation IDs must stay inside the host integration. */
  readonly host_conversation_id_digest?: string;
}

export interface HostLifecycleObservation {
  readonly kind: HostLifecycleEvent["kind"];
  readonly identity_continuity: "same" | "changed" | "unknown";
  readonly consistent: boolean | undefined;
  readonly host_conversation_id_digest?: string;
}

export type SessionMode = "attach" | "managed_launch";

export interface EnrollmentTicket {
  readonly ticket_id: string;
  readonly principal_kind: "T";
  readonly mode: SessionMode;
  readonly adapter_kind: string;
  readonly expires_at: string;
}

export interface InstallationPlan {
  readonly installation_id: string;
  readonly host_kind: string;
  readonly profile_ref: string;
  readonly bridge_command: readonly string[];
  readonly action: "install" | "uninstall";
}

export function createInstallationPlan(hostKind: string, installationId: string, profileRef: string, action: InstallationPlan["action"]): InstallationPlan {
  if (!hostKind || !installationId || !profileRef || /token|secret|authorization/i.test(profileRef)) {
    throw new Error("invalid_non_secret_profile");
  }
  return {
    installation_id: installationId,
    host_kind: hostKind,
    profile_ref: profileRef,
    bridge_command: ["tsunagou", "bridge", action, "--profile-ref", profileRef],
    action,
  };
}

export function validateBridgeTicket(ticket: EnrollmentTicket, expectedMode: SessionMode): void {
  if (ticket.principal_kind !== "T") throw new Error("invalid_bridge_ticket_principal");
  if (ticket.mode !== expectedMode) throw new Error("bridge_mode_mismatch");
  if (!ticket.ticket_id || !ticket.adapter_kind) throw new Error("invalid_bridge_ticket");
}

export interface ContextSection {
  readonly name: string;
  readonly body: string;
  readonly sensitive?: boolean;
}

export interface InboxItem {
  readonly delivery_id: string;
  readonly message_id: string;
  readonly recipient_session_id: string;
  readonly body: string;
}

export interface InboxClaim {
  readonly delivery_id: string;
  readonly message_id: string;
  readonly recipient_session_id: string;
}

export interface InboxSource {
  claim(sessionId: string, cursor?: string): Promise<{ items: readonly InboxClaim[]; cursor?: string }>;
  fetch(sessionId: string, deliveryId: string): Promise<InboxItem>;
  presented(sessionId: string, deliveryId: string, evidenceDigest: string): Promise<void>;
  ack(sessionId: string, deliveryId: string): Promise<void>;
}

export interface LeaseRenewer {
  renew(sessionId: string, connectionEpoch: number): Promise<boolean>;
}

export interface McpToolDescriptor {
  readonly name: string;
  readonly command_kind: CommandKind;
  readonly input_schema: Readonly<Record<string, unknown>>;
}

export interface StdioForwarder {
  readonly sessionId: string;
  forward<T>(request: CommandEnvelope, send: (request: CommandEnvelope) => Promise<T>): Promise<T>;
}

/** Creates a per-session forwarder; credentials remain inside the bridge transport. */
export function createStdioForwarder(sessionId: string): StdioForwarder {
  return {
    sessionId,
    forward: (request, send) => send(request),
  };
}

export function createMcpTools(tools: readonly McpToolDescriptor[]): readonly McpToolDescriptor[] {
  const names = new Set<string>();
  const commands = new Set<string>();
  return tools.filter((tool) => {
    const lowerName = tool.name.toLowerCase();
    if (lowerName.includes("token") || lowerName.includes("secret")) return false;
    const expectedName = tool.command_kind.replaceAll(".", "__");
    if (tool.name !== expectedName) throw new Error("invalid_mcp_tool_name");
    if (names.has(tool.name) || commands.has(tool.command_kind)) throw new Error("duplicate_mcp_tool");
    names.add(tool.name);
    commands.add(tool.command_kind);
    return true;
  });
}

function canonicalize(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "undefined";
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalize(record[key])}`).join(",")}}`;
}

function commandFingerprint(envelope: CommandEnvelope, kind?: CommandKind): string {
  return canonicalize({
    kind: kind ?? null,
    protocol_version: envelope.protocol_version,
    schema_bundle_digest: envelope.schema_bundle_digest,
    payload: envelope.payload,
  });
}

function failureDetails(error: unknown): BridgeFailure {
  if (typeof error !== "object" || error === null) return {};
  const record = error as Record<string, unknown>;
  return {
    code: typeof record.code === "string" ? record.code : undefined,
    status: typeof record.status === "number" ? record.status : undefined,
    retry_after_ms: typeof record.retry_after_ms === "number" ? record.retry_after_ms : undefined,
  };
}

function isRetryableFailure(error: unknown): boolean {
  const failure = failureDetails(error);
  if (failure.status !== undefined) return failure.status === 429 || failure.status === 503;
  if (failure.code !== undefined) {
    return ["queue_capacity", "temporarily_unavailable", "ECONNRESET", "ETIMEDOUT", "EPIPE"].includes(failure.code);
  }
  return error instanceof Error && ["socket_closed", "connection_reset", "connection_timeout"].includes(error.message);
}

function sameCapabilities(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  return left.size === right.size && [...left].every((capability) => right.has(capability));
}

export function observeHostLifecycle(input: HostProbeInput, event: HostLifecycleEvent): HostLifecycleObservation {
  const previous = input.host_conversation_id_digest;
  const current = event.host_conversation_id_digest;
  const identity_continuity = previous === undefined || current === undefined
    ? "unknown"
    : previous === current ? "same" : "changed";
  const expected = event.kind === "resume" || event.kind === "compact"
    ? "same"
    : event.kind === "new" || event.kind === "clear" || event.kind === "fork"
      ? "changed"
      : undefined;
  return {
    kind: event.kind,
    identity_continuity,
    consistent: expected === undefined || identity_continuity === "unknown" ? undefined : identity_continuity === expected,
    host_conversation_id_digest: current,
  };
}

export class BridgeClient {
  private readonly completed = new Map<string, unknown>();
  private readonly commandFingerprints = new Map<string, string>();
  private readonly inFlight = new Map<string, Promise<unknown>>();
  private readonly fetchedDeliveries = new Map<string, InboxItem>();
  private readonly presentedDeliveries = new Set<string>();
  private readonly acknowledgedDeliveries = new Set<string>();
  private connectionState: BridgeConnection;
  private readonly maxRetries: number;
  private readonly retryDelayMs: number;
  private readonly credentialProvider?: () => string | undefined;

  public constructor(private readonly transport: BridgeTransport, options: BridgeOptions) {
    this.connectionState = options.connection;
    this.maxRetries = options.maxRetries ?? 2;
    this.retryDelayMs = options.retryDelayMs ?? 0;
    this.credentialProvider = options.credentialProvider;
  }

  public get connection(): BridgeConnection {
    return this.connectionState;
  }

  public reconnect(connection: BridgeConnection): boolean {
    if (connection.sessionId !== this.connectionState.sessionId || connection.connectionEpoch < this.connectionState.connectionEpoch) {
      throw new Error("stale_connection_epoch");
    }
    if (connection.connectionEpoch === this.connectionState.connectionEpoch) {
      if (!sameCapabilities(connection.capabilities, this.connectionState.capabilities)) {
        throw new Error("connection_epoch_conflict");
      }
      return false;
    }
    this.connectionState = connection;
    // A higher epoch must re-enter the authoritative transport so current
    // credentials and epoch fencing are checked before an idempotent replay.
    this.completed.clear();
    this.inFlight.clear();
    return true;
  }

  public async send<T>(envelope: CommandEnvelope, kind?: CommandKind): Promise<T> {
    if (kind !== undefined && !kind.includes(".")) {
      throw new Error("invalid_command_kind");
    }
    const fingerprint = commandFingerprint(envelope, kind);
    const existingFingerprint = this.commandFingerprints.get(envelope.command_id);
    if (existingFingerprint !== undefined && existingFingerprint !== fingerprint) {
      throw new Error("idempotency_conflict");
    }
    this.commandFingerprints.set(envelope.command_id, fingerprint);
    if (this.completed.has(envelope.command_id)) return this.completed.get(envelope.command_id) as T;
    const pending = this.inFlight.get(envelope.command_id);
    if (pending !== undefined) return pending as Promise<T>;
    const connection = this.connectionState;

    const operation = (async (): Promise<T> => {
      let lastError: unknown;
      for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
        if (this.connectionState !== connection) throw new Error("stale_connection_epoch");
        try {
          const result = await this.transport.send<T>(envelope, {
            sessionId: connection.sessionId,
            connectionEpoch: connection.connectionEpoch,
            authorization: this.credentialProvider?.(),
          });
          if (this.connectionState !== connection) throw new Error("stale_connection_epoch");
          this.completed.set(envelope.command_id, result);
          return result;
        } catch (error) {
          if (this.connectionState !== connection) throw new Error("stale_connection_epoch");
          lastError = error;
          if (!isRetryableFailure(error) || attempt >= this.maxRetries) break;
          const retryAfterMs = failureDetails(error).retry_after_ms ?? this.retryDelayMs;
          if (retryAfterMs > 0) {
            await new Promise((resolve) => setTimeout(resolve, retryAfterMs));
          }
        }
      }
      throw lastError instanceof Error ? lastError : new Error("bridge_send_failed");
    })();
    this.inFlight.set(envelope.command_id, operation);
    try {
      return await operation;
    } finally {
      if (this.inFlight.get(envelope.command_id) === operation) this.inFlight.delete(envelope.command_id);
    }
  }

  public conformance(capabilities: Readonly<Partial<Record<BaselineCapability, boolean | undefined>>>): ConformanceReport {
    const checks = BASELINE_CAPABILITIES.map((name) => ({
      name,
      status: capabilities[name] === true ? "supported" : capabilities[name] === false ? "unsupported" : "unknown",
      strength: capabilities[name] === true ? "observed" : undefined,
      evidence: undefined,
    })) satisfies readonly ConformanceCheck[];
    return {
      ready: checks.every((check) => check.status === "supported" && check.evidence !== undefined),
      checks,
      missing: checks.filter((check) => check.status !== "supported" || check.evidence === undefined).map((check) => check.name as BaselineCapability),
    };
  }

  public async pullInbox(source: InboxSource, cursor?: string): Promise<{ items: readonly InboxItem[]; pending_delivery_ids: readonly string[]; cursor?: string }> {
    const response = await source.claim(this.connectionState.sessionId, cursor);
    const claims = response.items.filter((item) => item.recipient_session_id === this.connectionState.sessionId);
    const items: InboxItem[] = [];
    const pendingDeliveryIds: string[] = [];
    for (const claim of claims) {
      if (this.acknowledgedDeliveries.has(claim.delivery_id)) continue;
      if (this.fetchedDeliveries.has(claim.delivery_id)) {
        pendingDeliveryIds.push(claim.delivery_id);
        continue;
      }
      const item = await source.fetch(this.connectionState.sessionId, claim.delivery_id);
      if (item.delivery_id !== claim.delivery_id || item.message_id !== claim.message_id || item.recipient_session_id !== this.connectionState.sessionId) {
        throw new Error("inbox_delivery_mismatch");
      }
      this.fetchedDeliveries.set(item.delivery_id, item);
      items.push(item);
    }
    return { items, pending_delivery_ids: pendingDeliveryIds, cursor: response.cursor };
  }

  public async markInboxPresented(source: InboxSource, deliveryId: string, evidenceDigest: string): Promise<boolean> {
    if (!this.fetchedDeliveries.has(deliveryId)) throw new Error("inbox_delivery_not_fetched");
    if (!evidenceDigest) throw new Error("presentation_evidence_required");
    if (this.presentedDeliveries.has(deliveryId)) return false;
    await source.presented(this.connectionState.sessionId, deliveryId, evidenceDigest);
    this.presentedDeliveries.add(deliveryId);
    return true;
  }

  public async ackInbox(source: InboxSource, deliveryId: string): Promise<boolean> {
    if (!this.presentedDeliveries.has(deliveryId)) throw new Error("inbox_delivery_not_presented");
    if (this.acknowledgedDeliveries.has(deliveryId)) return false;
    await source.ack(this.connectionState.sessionId, deliveryId);
    this.acknowledgedDeliveries.add(deliveryId);
    return true;
  }

  public async renewLease(renewer: LeaseRenewer): Promise<boolean> {
    return renewer.renew(this.connectionState.sessionId, this.connectionState.connectionEpoch);
  }
}

export class ContextRenderer {
  public render(sections: readonly ContextSection[], maxChars = 12_000): { text: string; truncated: boolean } {
    const visible = sections.filter((section) => !section.sensitive);
    let text = visible.map((section) => `## ${section.name}\n${section.body}`).join("\n\n");
    const truncated = text.length > maxChars;
    if (truncated) text = `${text.slice(0, Math.max(0, maxChars - 18))}\n[truncated]`;
    return { text, truncated };
  }
}

export function evaluateConformance(checks: readonly ConformanceCheck[]): ConformanceReport {
  const byName = new Map(checks.map((check) => [check.name, check]));
  const normalized = BASELINE_CAPABILITIES.map((name) => byName.get(name) ?? { name, status: "unknown" as const });
  const missing = normalized.filter((check) => check.status !== "supported" || !check.evidence).map((check) => check.name as BaselineCapability);
  return { ready: missing.length === 0, checks: normalized, missing };
}

export async function runConformance(adapter: HostAdapter, input: HostProbeInput): Promise<ConformanceReport> {
  return evaluateConformance(await adapter.probeCapabilities(input));
}

export function createBridge(transport: BridgeTransport, options: BridgeOptions): BridgeClient {
  return new BridgeClient(transport, options);
}
