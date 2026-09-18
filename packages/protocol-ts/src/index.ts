export type Revision = number;
export type Digest = string;
export type CommandPrincipal = "U" | "B" | "M" | "X" | "R" | "H" | "D" | "T";

export interface CommandEnvelope<TPayload = Record<string, unknown>> {
  command_id: string;
  protocol_version: string;
  schema_bundle_digest: Digest;
  payload: TPayload;
}

export type { CommandKind } from "./generated/commands.js";
