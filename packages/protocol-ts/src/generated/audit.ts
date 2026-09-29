// Generated from protocol/schemas/queries/audit-page.schema.json; do not edit.
// Source digest: sha256:4ce893bab4133a37e5a422adbc089eea47121af614604126a5cdd36fc396b1ab; generator: query-v1

export interface AuditChange {
  subject_ref: string;
  change_kind: "created" | "updated" | "deleted";
  state_before: string | null;
  state_after: string | null;
  revision_before: number | null;
  revision_after: number | null;
  revision_source: "domain" | "audit_observation";
  created_at: string | null;
  updated_at: string | null;
}

export interface AuditEvent {
  event_id: string;
  event_seq: number;
  source_event_id: string;
  source_event_seq: number;
  project_id: string;
  lineage_id: string;
  schema_version: string;
  projection_version: string;
  actor_ref: string;
  actor_session_id: string | null;
  subject_ref: string;
  action: string;
  outcome: string;
  reason_code: string | null;
  evidence_refs: Array<string>;
  occurred_at: string | null;
  recorded_at: string | null;
  caused_by_command_id: string | null;
  revision_before: number | null;
  revision_after: number | null;
  evidence_level: "agent_asserted" | "host_observed" | "system_verified" | "user_confirmed" | null;
  changes: Array<AuditChange>;
  session_status: string | null;
  missing_admission: Array<string>;
}

export interface AuditPage {
  project_id: string;
  items: Array<AuditEvent>;
  next_cursor: string | null;
  projection_version: "v1";
  as_of_event_seq: number;
  snapshot_event_seq: number;
}
