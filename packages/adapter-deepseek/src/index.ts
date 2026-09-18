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

export const adapterKind = "deepseek" as const;

export interface DeepSeekEvidenceInput extends HostProbeInput {
  readonly baseline?: Partial<Record<BaselineCapability, { status: "supported" | "unsupported" | "unknown"; strength?: CapabilityStrength; evidence?: string }>>;
}

export class DeepSeekAdapter implements HostAdapter {
  public readonly kind = adapterKind;
  private readonly renderer = new ContextRenderer();
  private lastEvent?: HostLifecycleEvent;

  public getIdentity(input: HostProbeInput): HostIdentity | undefined {
    if (input.host_kind !== adapterKind || !input.host_conversation_id_digest) return undefined;
    return { installation_id: input.adapter_installation_id, host_kind: adapterKind, host_conversation_id_digest: input.host_conversation_id_digest };
  }

  public async probeCapabilities(input: HostProbeInput): Promise<readonly ConformanceCheck[]> {
    const evidence = input as DeepSeekEvidenceInput;
    return BASELINE_CAPABILITIES.map((name) => ({ name, ...(evidence.baseline?.[name] ?? { status: "unknown" as const }) }));
  }

  public renderContext(_input: HostProbeInput, sections: readonly ContextSection[]): string {
    return this.renderer.render(sections).text;
  }

  public observeLifecycle(_input: HostProbeInput, event: HostLifecycleEvent): void {
    this.lastEvent = event;
  }

  public lifecycle(): HostLifecycleEvent | undefined {
    return this.lastEvent;
  }
}

export const deepseekAdapter: HostAdapter = new DeepSeekAdapter();

export const createDeepSeekInstallationPlan = (installationId: string, profileRef: string, action: InstallationPlan["action"]): InstallationPlan =>
  createInstallationPlan(adapterKind, installationId, profileRef, action);
