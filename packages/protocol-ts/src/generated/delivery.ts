// Generated from protocol/schemas/queries/credential-delivery.schema.json; do not edit.
// Source digest: sha256:d8f28cd42f456b068037a117808d602d5e945f5aa5a5424fe6c1aa16ee42a59b; generator: query-v1

export interface CredentialDelivery {
  receipt_id: string;
  delivery_ref: string;
  delivery_status: "pending" | "delivered" | "consumed" | "revoked" | "expired";
  created_at: string;
  expires_at: string;
  delivered_at: string | null;
  recovery_expires_at: string | null;
  consumed_at: string | null;
  revoked_at: string | null;
}
