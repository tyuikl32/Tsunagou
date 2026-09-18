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
  readonly host_conversation_id?: string;
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
  readonly message_id: string;
  readonly recipient_session_id: string;
  readonly body: string;
}

export interface InboxSource {
  pull(sessionId: string, cursor?: string): Promise<{ items: readonly InboxItem[]; cursor?: string }>;
  ack(sessionId: string, messageId: string): Promise<void>;
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
  return tools.filter((tool) => !tool.name.toLowerCase().includes("token") && !tool.name.toLowerCase().includes("secret"));
}

export class BridgeClient {
  private readonly seen = new Map<string, unknown>();
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

  public reconnect(connection: BridgeConnection): void {
    if (connection.sessionId !== this.connectionState.sessionId || connection.connectionEpoch <= this.connectionState.connectionEpoch) {
      throw new Error("stale_connection_epoch");
    }
    this.connectionState = connection;
  }

  public async send<T>(envelope: CommandEnvelope, kind?: CommandKind): Promise<T> {
    if (kind !== undefined && !kind.includes(".")) {
      throw new Error("invalid_command_kind");
    }
    const existing = this.seen.get(envelope.command_id);
    if (existing !== undefined) {
      return existing as T;
    }
    let lastError: unknown;
    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      try {
        const result = await this.transport.send<T>(envelope, {
          sessionId: this.connectionState.sessionId,
          connectionEpoch: this.connectionState.connectionEpoch,
          authorization: this.credentialProvider?.(),
        });
        this.seen.set(envelope.command_id, result);
        return result;
      } catch (error) {
        lastError = error;
        if (attempt < this.maxRetries && this.retryDelayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, this.retryDelayMs));
        }
      }
    }
    throw lastError instanceof Error ? lastError : new Error("bridge_send_failed");
  }

  public conformance(capabilities: Readonly<Partial<Record<BaselineCapability, boolean | undefined>>>): ConformanceReport {
    const checks = BASELINE_CAPABILITIES.map((name) => ({
      name,
      status: capabilities[name] === true ? "supported" : capabilities[name] === false ? "unsupported" : "unknown",
      strength: capabilities[name] === true ? "observed" : undefined,
      evidence: capabilities[name] === true ? `${this.connectionState.sessionId}:${this.connectionState.connectionEpoch}` : undefined,
    })) satisfies readonly ConformanceCheck[];
    return {
      ready: checks.every((check) => check.status === "supported" && check.evidence !== undefined),
      checks,
      missing: checks.filter((check) => check.status !== "supported").map((check) => check.name as BaselineCapability),
    };
  }

  public async pullInbox(source: InboxSource, cursor?: string): Promise<{ items: readonly InboxItem[]; cursor?: string }> {
    const response = await source.pull(this.connectionState.sessionId, cursor);
    const items = response.items.filter((item) => item.recipient_session_id === this.connectionState.sessionId);
    for (const item of items) {
      await source.ack(this.connectionState.sessionId, item.message_id);
    }
    return { items, cursor: response.cursor };
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
  const missing = normalized.filter((check) => check.status !== "supported").map((check) => check.name as BaselineCapability);
  return { ready: missing.length === 0 && normalized.every((check) => check.evidence !== undefined), checks: normalized, missing };
}

export async function runConformance(adapter: HostAdapter, input: HostProbeInput): Promise<ConformanceReport> {
  return evaluateConformance(await adapter.probeCapabilities(input));
}

export function createBridge(transport: BridgeTransport, options: BridgeOptions): BridgeClient {
  return new BridgeClient(transport, options);
}
