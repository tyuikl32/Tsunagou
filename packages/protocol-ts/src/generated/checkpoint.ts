// Generated from protocol/schemas/queries/checkpoint-page.schema.json; do not edit.
// Source digest: sha256:640023b3c48e8fc5991116e1b7449279c03bd448482d9d471dd07d056480b400; generator: query-v1

export interface CheckpointPointer {
  digest: string;
  status: "sealed" | "verified";
  through_event_seq: number;
}

export interface CheckpointSummary {
  digest: string;
  parent_digest: string | null;
  project_id: string | null;
  lineage_id: string;
  through_event_seq: number;
  format_version: number;
  schema_bundle_digest: string;
  created_at: string | null;
  created_by: string | null;
  reason: string | null;
  projection_version: string;
  verified_at: string | null;
  status: "sealed" | "verified";
  artifact_digests: Array<string>;
}

export interface CheckpointPage {
  project_id: string;
  current: CheckpointPointer | null;
  items: Array<CheckpointSummary>;
  projection_version: "v1";
  as_of_event_seq: number;
}
