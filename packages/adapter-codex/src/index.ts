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
  type HostProbeInput,
  createInstallationPlan,
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
  readonly source: "codex_app_server" | "codex_cli";
};

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
  private lastLifecycle?: CodexLifecycleEvent;

  public getIdentity(input: HostProbeInput): HostIdentity | undefined {
    if (input.host_kind !== adapterKind || !input.host_conversation_id_digest) return undefined;
    return {
      installation_id: input.adapter_installation_id,
      host_kind: adapterKind,
      host_conversation_id_digest: input.host_conversation_id_digest,
    };
  }

  public async probeCapabilities(input: HostProbeInput): Promise<readonly ConformanceCheck[]> {
    return BASELINE_CAPABILITIES.map((name) => toCheck(name, input as CodexEvidenceInput));
  }

  public renderContext(_input: HostProbeInput, sections: readonly ContextSection[]): string {
    return this.renderer.render(sections).text;
  }

  public observeLifecycle(_input: HostProbeInput, event: HostLifecycleEvent): void {
    this.lastLifecycle = event as CodexLifecycleEvent;
  }

  public lifecycle(): CodexLifecycleEvent | undefined {
    return this.lastLifecycle;
  }
}

export function createCodexAdapter(): HostAdapter {
  return new CodexAdapter();
}

export const codexAdapter = createCodexAdapter();

export const createCodexInstallationPlan = (installationId: string, profileRef: string, action: InstallationPlan["action"]): InstallationPlan =>
  createInstallationPlan(adapterKind, installationId, profileRef, action);
