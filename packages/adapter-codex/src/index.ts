import {
  BASELINE_CAPABILITIES,
  ContextRenderer,
  type BaselineCapability,
  type CapabilityStrength,
  type ConformanceCheck,
  type ContextSection,
  type HostAdapter,
  type HostIdentity,
  type HostLifecycleEvent,
  type HostLifecycleObservation,
  type HostProbeInput,
  type HostWakeAdapter,
  type HostWakeCapability,
  type HostWakeRequest,
  type HostWakeResult,
  type HostEnhancements,
  createInstallationPlan,
  observeHostLifecycle,
  type InstallationPlan,
} from "@tsunagou/bridge-sdk";

export const adapterKind = "codex" as const;

export interface CodexEvidenceInput extends HostProbeInput {
  readonly baseline?: Partial<Record<BaselineCapability, {
    status: "supported" | "unsupported" | "unknown";
    strength?: CapabilityStrength;
    evidence?: string;
  }>>;
}

export type CodexLifecycleEvent = HostLifecycleEvent & {
  readonly source?: "codex_app_server" | "codex_cli";
};

/**
 * The adapter never calls a guessed Codex API. A real app-server integration
 * is injected only after a versioned probe has produced supported evidence.
 * The transport must return a sanitized turn digest, not the raw host ID.
 */
export interface CodexAppServerWakeTransport {
  requestTurn(
    input: HostProbeInput,
    prompt: string,
  ): Promise<{
    readonly host_turn_id_digest: string;
    readonly evidence: string;
    readonly accepted_at?: string;
  }>;
}

export interface CodexWakeOptions {
  readonly capability?: HostWakeCapability;
  readonly transport?: CodexAppServerWakeTransport;
}

const UNVERIFIED_WAKE_CAPABILITY: HostWakeCapability = {
  status: "unsupported",
  strength: "advisory",
  evidence: "codex_app_server_wake_unverified",
};

/** Keep the wake prompt as a reference-only nudge; task details stay in inbox. */
export function createCodexWakePrompt(request: HostWakeRequest): string {
  if (!request.wake_id || !request.task_id || !request.assignment_id) {
    throw new Error("invalid_wake_request");
  }
  return [
    "Tsunagou worker wake.",
    `wake_id=${request.wake_id}`,
    `task_id=${request.task_id}`,
    `assignment_id=${request.assignment_id}`,
    "Pull the assigned task from the Tsunagou inbox, then call worker.ready before requesting a Lease.",
  ].join("\n");
}

function toCheck(name: BaselineCapability, evidence: CodexEvidenceInput): ConformanceCheck {
  const result = evidence.baseline?.[name];
  return {
    name,
    status: result?.status ?? "unknown",
    strength: result?.strength,
    evidence: result?.evidence,
  };
}

export class CodexAdapter implements HostAdapter {
  public readonly kind = adapterKind;
  private readonly renderer = new ContextRenderer();
  private lastLifecycle?: HostLifecycleObservation;
  private readonly wakeOptions: CodexWakeOptions;

  public constructor(options: CodexWakeOptions = {}) {
    this.wakeOptions = options;
  }

  /** Structured wake port consumed by the daemon coordinator. */
  public get wakeAdapter(): HostWakeAdapter {
    return this;
  }

  /** Keep the old HostAdapter enhancement surface available to callers. */
  public get enhancements(): HostEnhancements {
    return { wake: async (input, request) => request === undefined ? this.wakeCapabilityResult(input) : this.wake(input, request) };
  }

  public getWakeCapability(input: HostProbeInput): HostWakeCapability {
    if (this.getIdentity(input) === undefined) return { status: "unknown" };
    const capability = this.wakeOptions.capability ?? UNVERIFIED_WAKE_CAPABILITY;
    if (capability.status === "supported" && !capability.evidence) {
      return { ...capability, status: "unknown", evidence: undefined };
    }
    return capability;
  }

  private wakeCapabilityResult(input: HostProbeInput): HostWakeResult {
    const capability = this.getWakeCapability(input);
    return {
      wake_id: "capability-check",
      status: capability.status === "supported" ? "rejected" : capability.status === "unsupported" ? "unsupported" : "failed",
      evidence: capability.evidence,
      reason: capability.status === "supported" ? "wake_request_required" : "host_wake_unverified",
    };
  }

  public async wake(input: HostProbeInput, request: HostWakeRequest): Promise<HostWakeResult> {
    if (!request.wake_id || !request.task_id || !request.assignment_id) throw new Error("invalid_wake_request");
    if (this.getIdentity(input) === undefined) {
      return { wake_id: request.wake_id, status: "rejected", reason: "adapter_host_mismatch_or_identity_missing" };
    }
    const capability = this.getWakeCapability(input);
    if (capability.status !== "supported") {
      return { wake_id: request.wake_id, status: capability.status === "unsupported" ? "unsupported" : "failed", evidence: capability.evidence, reason: "host_wake_not_supported" };
    }
    if (this.wakeOptions.transport === undefined) {
      return { wake_id: request.wake_id, status: "failed", evidence: capability.evidence, reason: "wake_transport_unconfigured" };
    }
    try {
      const response = await this.wakeOptions.transport.requestTurn(input, createCodexWakePrompt(request));
      if (!response.host_turn_id_digest || !response.evidence) {
        return { wake_id: request.wake_id, status: "failed", reason: "host_wake_evidence_required" };
      }
      return {
        wake_id: request.wake_id,
        status: "accepted",
        host_turn_id_digest: response.host_turn_id_digest,
        evidence: response.evidence,
        accepted_at: response.accepted_at,
      };
    } catch {
      // Do not forward host/library exception text: it can contain raw turn
      // identifiers or credentials. The daemon only needs a stable reason code.
      return {
        wake_id: request.wake_id,
        status: "failed",
        evidence: capability.evidence,
        reason: "host_wake_transport_failed",
      };
    }
  }

  public getIdentity(input: HostProbeInput): HostIdentity | undefined {
    if (input.host_kind !== adapterKind || !input.adapter_installation_id || !input.host_conversation_id_digest) return undefined;
    return {
      installation_id: input.adapter_installation_id,
      host_kind: adapterKind,
      host_conversation_id_digest: input.host_conversation_id_digest,
    };
  }

  public async probeCapabilities(input: HostProbeInput): Promise<readonly ConformanceCheck[]> {
    if (this.getIdentity(input) === undefined) {
      return BASELINE_CAPABILITIES.map((name) => ({ name, status: "unknown" as const }));
    }
    return BASELINE_CAPABILITIES.map((name) => toCheck(name, input as CodexEvidenceInput));
  }

  public renderContext(_input: HostProbeInput, sections: readonly ContextSection[]): string {
    return this.renderer.render(sections).text;
  }

  public observeLifecycle(_input: HostProbeInput, event: HostLifecycleEvent): void {
    if (_input.host_kind !== adapterKind) throw new Error("adapter_host_mismatch");
    this.lastLifecycle = observeHostLifecycle(_input, event);
  }

  public lifecycle(): HostLifecycleObservation | undefined {
    return this.lastLifecycle;
  }
}

export function createCodexAdapter(options: CodexWakeOptions = {}): CodexAdapter {
  return new CodexAdapter(options);
}

export const codexAdapter = createCodexAdapter();

export const createCodexInstallationPlan = (installationId: string, profileRef: string, action: InstallationPlan["action"]): InstallationPlan =>
  createInstallationPlan(adapterKind, installationId, profileRef, action);
