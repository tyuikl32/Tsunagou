// Generated from protocol/schemas/queries/checkpoint-verification.schema.json; do not edit.
// Source digest: sha256:d27582948655e2985553635e0c5f254df7679764f88e5698dc15313698838dae; generator: query-v1

export interface GitAnchor {
  ref_name: string;
  commit_oid: string;
}

export interface CheckpointVerification {
  digest: string;
  status: "verified";
  project_id: string | null;
  lineage_id: string;
  through_event_seq: number;
  created_at: string | null;
  verified_at: string | null;
  git_anchors: Array<GitAnchor>;
}
