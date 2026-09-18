import type { CommandEnvelope } from "@tsunagou/protocol-ts";

export interface HostIdentity {
  installation_id: string;
  host_kind: string;
  host_conversation_id_digest: string;
}

export interface BridgeTransport {
  send<T>(envelope: CommandEnvelope): Promise<T>;
}

export function createBridge(transport: BridgeTransport) {
  return { transport };
}
