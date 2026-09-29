import { createHash, randomUUID } from "node:crypto";
import { existsSync, unlinkSync } from "node:fs";
import { createPrivateJson, readPrivateJson, writePrivateJson } from "./private-file.js";
import { withPrivateFileLock } from "./private-file-lock.js";

export interface SessionCredential {
  agent_id: string;
  session_id: string;
  connection_epoch: number;
  secret_token: string;
  reconnect_nonce: string;
  baseline_status: string;
  receipt_id?: string;
  delivery_ref?: string;
  delivery_status?: string;
  created_at?: string | null;
  expires_at?: string | null;
  delivered_at?: string | null;
  recovery_expires_at?: string | null;
  consumed_at?: string | null;
  revoked_at?: string | null;
}

export interface PersistedSession extends SessionCredential {
  host_conversation_id_digest?: string;
  conversation_binding_digest?: string;
  credential_command_id?: string;
  credential_auth_binding_digest?: string;
  credential_ticket_digest?: string;
  delivery_ack_pending?: boolean;
}

export interface TicketFile {
  installation_id: string;
  conversation_id: string;
  secret: string;
  requested_role?: "worker" | "main";
}

type CredentialKind = "agent.enroll" | "session.rebind" | "session.reconnect";
interface PendingRequest {
  version: 1;
  kind: CredentialKind;
  conversation_binding_digest: string;
  host_conversation_id_digest?: string;
  auth_binding_digest: string;
  ticket_digest?: string;
  expected_agent_id?: string;
  envelope: {
    command_id: string;
    protocol_version: string;
    schema_bundle_digest: string;
    payload: Record<string, unknown>;
  };
}

function hash(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

export function ticketDigest(ticket: TicketFile): string {
  return hash([ticket.installation_id, ticket.conversation_id, ticket.secret]);
}

function object(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

function nonempty(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** Explicitly select fields: a safe consumed receipt is NOT a credential. */
export function parseCredential(value: unknown): SessionCredential {
  const raw = object(value);
  if (raw?.recovery_action === "reconnect_required"
      || raw?.delivery_status === "consumed" || raw?.delivery_status === "expired") {
    throw new Error("credential_delivery_unavailable:reconnect_required");
  }
  if (!raw || !nonempty(raw.agent_id) || !nonempty(raw.session_id)
      || !Number.isSafeInteger(raw.connection_epoch) || Number(raw.connection_epoch) < 1
      || !nonempty(raw.secret_token) || !nonempty(raw.reconnect_nonce)
      || !nonempty(raw.baseline_status)) {
    throw new Error("credential_response_invalid");
  }
  const result: SessionCredential = {
    agent_id: raw.agent_id, session_id: raw.session_id,
    connection_epoch: raw.connection_epoch as number,
    secret_token: raw.secret_token, reconnect_nonce: raw.reconnect_nonce,
    baseline_status: raw.baseline_status,
  };
  for (const key of ["receipt_id", "delivery_ref", "delivery_status"] as const) {
    if (raw[key] !== undefined) {
      if (!nonempty(raw[key])) throw new Error("credential_response_invalid");
      result[key] = raw[key];
    }
  }
  for (const key of ["created_at", "expires_at", "delivered_at", "recovery_expires_at", "consumed_at", "revoked_at"] as const) {
    if (raw[key] !== undefined) {
      if (raw[key] !== null && (typeof raw[key] !== "string"
          || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(raw[key]))) {
        throw new Error("credential_response_invalid");
      }
      result[key] = raw[key];
    }
  }
  return result;
}

export function loadSession(path: string): PersistedSession | undefined {
  const value = readPrivateJson(path);
  if (value === undefined) return undefined;
  const raw = object(value)!;
  const session: PersistedSession = parseCredential(value);
  for (const key of ["host_conversation_id_digest", "conversation_binding_digest",
    "credential_command_id", "credential_auth_binding_digest", "credential_ticket_digest"] as const) {
    if (raw[key] !== undefined) {
      if (!nonempty(raw[key])) throw new Error("credential_private_file_invalid");
      session[key] = raw[key];
    }
  }
  session.delivery_ack_pending = raw.delivery_ack_pending === true;
  if (session.delivery_ack_pending && session.credential_command_id) {
    // ACK metadata is separate so a slow ACK for epoch N never rewrites the
    // credential file after another process has already saved epoch N+1.
    try {
      const ack = object(readPrivateJson(`${path}.delivery-ack.json`));
      if (ack?.version === 1 && ack.credential_command_id === session.credential_command_id
          && ack.session_id === session.session_id && ack.connection_epoch === session.connection_epoch
          && ack.delivery_ref === session.delivery_ref) session.delivery_ack_pending = false;
    } catch {
      // Losing/corrupting an ACK marker only retries the idempotent ACK.
    }
  }
  return session;
}

function readPending(path: string): PendingRequest | undefined {
  const raw = object(readPrivateJson(path));
  if (raw === undefined) {
    if (existsSync(path)) throw new Error("credential_pending_invalid");
    return undefined;
  }
  const envelope = object(raw.envelope);
  if (raw.version !== 1 || !["agent.enroll", "session.rebind", "session.reconnect"].includes(String(raw.kind))
      || !nonempty(raw.conversation_binding_digest) || !nonempty(raw.auth_binding_digest)
      || !envelope || !nonempty(envelope.command_id) || !nonempty(envelope.protocol_version)
      || !nonempty(envelope.schema_bundle_digest) || !object(envelope.payload)) {
    throw new Error("credential_pending_invalid");
  }
  return raw as unknown as PendingRequest;
}

interface HandoffOptions {
  baseUrl: string;
  protocolVersion: string;
  schemaBundleDigest: string;
  sessionFile: string;
  conversationBindingDigest: string;
  hostDigest?: string;
  fetch?: typeof fetch;
  /** File writer injection is only for failure-window tests. */
  writePrivate?: typeof writePrivateJson;
}

interface RecoveryInput {
  ticket?: TicketFile;
  ticketFile?: string;
  baseline?: Record<string, unknown>;
  forceReconnect?: boolean;
}

type PreparedHandoff = { finished: true; session?: PersistedSession } | {
  finished: false; session?: PersistedSession; pending: PendingRequest;
  kind: CredentialKind; headers: Record<string, string>;
};
type TicketCleanup = [path: string | undefined, digest: string | undefined];

export class CredentialHandoff {
  private readonly pendingFile: string;
  private readonly request: typeof fetch;
  private readonly writePrivate: typeof writePrivateJson;

  public constructor(private readonly options: HandoffOptions) {
    this.pendingFile = `${options.sessionFile}.pending.json`;
    this.request = options.fetch ?? fetch;
    this.writePrivate = options.writePrivate ?? writePrivateJson;
  }

  private assertBinding(session: PersistedSession | undefined, pending: PendingRequest | undefined): void {
    const binding = this.options.conversationBindingDigest;
    if ((pending && pending.conversation_binding_digest !== binding)
        || (pending?.host_conversation_id_digest && this.options.hostDigest
          && pending.host_conversation_id_digest !== this.options.hostDigest)
        || (session?.conversation_binding_digest && session.conversation_binding_digest !== binding)
        || (session?.host_conversation_id_digest && this.options.hostDigest
          && session.host_conversation_id_digest !== this.options.hostDigest)) {
      throw new Error("credential_conversation_binding_mismatch");
    }
  }

  private async acknowledge(session: PersistedSession): Promise<PersistedSession> {
    if (!session.delivery_ack_pending || !session.delivery_ref) return session;
    try {
      const response = await this.request(
        `${this.options.baseUrl}/api/v1/credential-deliveries/${encodeURIComponent(session.delivery_ref)}/ack`,
        { method: "POST", headers: this.headers(session), body: "{}" },
      );
      if (!response.ok) return session;
      // Never overwrite credentials to persist ACK state: this response can
      // race a later epoch saved by another bridge sharing the conversation.
      this.writePrivate(`${this.options.sessionFile}.delivery-ack.json`, {
        version: 1, credential_command_id: session.credential_command_id,
        session_id: session.session_id, connection_epoch: session.connection_epoch,
        delivery_ref: session.delivery_ref,
      });
      return loadSession(this.options.sessionFile) ?? session;
    } catch {
      return session;
    }
  }

  private headers(session: SessionCredential): Record<string, string> {
    return {
      "content-type": "application/json", authorization: `Bearer ${session.secret_token}`,
      "tsunagou-session-id": session.session_id,
      "tsunagou-connection-epoch": String(session.connection_epoch),
    };
  }

  private async cleanTicket(path: string | undefined, digest: string | undefined): Promise<void> {
    if (!path || !digest) return;
    await withPrivateFileLock(path, () => {
      const raw = object(readPrivateJson(path));
      if (!raw || !nonempty(raw.installation_id) || !nonempty(raw.conversation_id) || !nonempty(raw.secret)) return;
      const actual = ticketDigest(raw as unknown as TicketFile);
      if (actual === digest) {
        try { unlinkSync(path); } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        }
      }
    });
  }

  private async cleanTickets(cleanup: TicketCleanup[]): Promise<void> {
    // Ticket producer (Python CLI) uses this same per-ticket mutex. Never nest
    // it under the session mutex: their hashed ports may collide harmlessly.
    for (const [path, digest] of cleanup.splice(0)) await this.cleanTicket(path, digest);
  }

  private cleanPending(pending: PendingRequest): void {
    const current = readPending(this.pendingFile);
    if (current?.envelope.command_id === pending.envelope.command_id) {
      try { unlinkSync(this.pendingFile); } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    }
  }

  private prepare(input: RecoveryInput, cleanup: TicketCleanup[]): PreparedHandoff {
    const session = loadSession(this.options.sessionFile);
    let pending = readPending(this.pendingFile);
    this.assertBinding(session, pending);

    if (pending && session?.credential_command_id === pending.envelope.command_id) {
      // Crash after save and before journal/ticket cleanup: never redeem again.
      this.cleanPending(pending);
      cleanup.push([input.ticketFile, pending.ticket_digest]);
      return { finished: true, session };
    }
    let ticket = input.ticket;
    if (ticket && session?.credential_ticket_digest === ticketDigest(ticket)) {
      cleanup.push([input.ticketFile, session.credential_ticket_digest]);
      ticket = undefined;
      if (!pending && !input.forceReconnect) return { finished: true, session };
    }
    if (!pending && session?.delivery_ack_pending && !input.forceReconnect && !ticket) {
      return { finished: true, session };
    }
    if (!pending && !ticket && !session) return { finished: true };

    const kind = pending?.kind ?? (ticket ? (session ? "session.rebind" : "agent.enroll") : "session.reconnect");
    if (kind !== "session.reconnect" && !ticket) throw new Error("credential_pending_original_ticket_required");
    if (kind === "session.reconnect" && !session) throw new Error("credential_pending_original_session_required");
    const headers = kind === "session.reconnect" ? this.headers(session!)
      : { "content-type": "application/json", authorization: `Bearer ${ticket!.secret}` };
    const authDigest = hash([kind, headers.authorization, headers["tsunagou-session-id"],
      headers["tsunagou-connection-epoch"], kind === "session.reconnect" ? undefined : ticketDigest(ticket!)]);
    if (pending && pending.auth_binding_digest !== authDigest) {
      throw new Error("credential_pending_auth_binding_mismatch");
    }
    if (!pending) {
      const payload: Record<string, unknown> = kind === "session.reconnect" ? {
        reconnect_nonce: session!.reconnect_nonce,
        expected_connection_epoch: session!.connection_epoch,
        // A degraded session cannot use the replay door (the daemon requires a ready
        // session for that), so it sends a fresh report: this is the one call the
        // daemon re-judges a degraded host by (api/auth.py: authenticate_reconnect_refresh
        // + session_reconnect in handlers). A ready session stays quiet on purpose — a
        // flaky startup probe must not downgrade a host that is already working, and
        // the nonce + epoch replay is the normal way back in.
        ...(session!.baseline_status === "ready" ? {} : { probe_payload: input.baseline ?? {} }),
      } : {
        installation_id: ticket!.installation_id,
        conversation_evidence: { conversation_id: ticket!.conversation_id },
        probe_payload: input.baseline ?? {},
        ...(kind === "session.rebind" ? { target_agent_id: session!.agent_id } : {}),
      };
      pending = {
        version: 1, kind, conversation_binding_digest: this.options.conversationBindingDigest,
        host_conversation_id_digest: this.options.hostDigest, auth_binding_digest: authDigest,
        ticket_digest: kind === "session.reconnect" ? undefined : ticketDigest(ticket!),
        expected_agent_id: session?.agent_id,
        envelope: {
          command_id: randomUUID(), protocol_version: this.options.protocolVersion,
          schema_bundle_digest: this.options.schemaBundleDigest, payload,
        },
      };
      if (!createPrivateJson(this.pendingFile, pending)) {
        const concurrent = readPending(this.pendingFile);
        if (concurrent) pending = concurrent;
        else {
          const saved = loadSession(this.options.sessionFile);
          this.assertBinding(saved, undefined);
          if (saved?.credential_auth_binding_digest !== authDigest) {
            throw new Error("credential_pending_changed:retry_pending_request");
          }
          cleanup.push([input.ticketFile, saved.credential_ticket_digest]);
          return { finished: true, session: saved };
        }
      }
      this.assertBinding(session, pending);
      if (pending.kind !== kind || pending.auth_binding_digest !== authDigest) {
        throw new Error("credential_pending_auth_binding_mismatch");
      }
    }
    // A competing bridge can finish between our initial read and journal
    // creation. Detect its saved handoff before sending a second command ID.
    const concurrentSession = loadSession(this.options.sessionFile);
    if (concurrentSession?.credential_auth_binding_digest === authDigest) {
      this.assertBinding(concurrentSession, pending);
      this.cleanPending(pending);
      cleanup.push([input.ticketFile, pending.ticket_digest]);
      return { finished: true, session: concurrentSession };
    }
    return { finished: false, session, pending, kind, headers };
  }

  public async recover(input: RecoveryInput = {}): Promise<PersistedSession | undefined> {
    const cleanup: TicketCleanup[] = [];
    const prepared = await withPrivateFileLock(this.options.sessionFile, () => this.prepare(input, cleanup));
    await this.cleanTickets(cleanup);
    if (prepared.finished) return prepared.session ? this.acknowledge(prepared.session) : undefined;
    const { session, pending, kind, headers } = prepared;
    let response: Response;
    try {
      response = await this.request(`${this.options.baseUrl}/api/v1/commands/${kind}`, {
        method: "POST", headers, body: JSON.stringify(pending.envelope),
      });
    } catch {
      throw new Error("credential_transport_failed:retry_pending_request");
    }
    const body = object(await response.json().catch(() => undefined));
    const stored = await withPrivateFileLock(this.options.sessionFile, () => {
      const saved = loadSession(this.options.sessionFile);
      if (saved?.credential_command_id === pending.envelope.command_id) {
        // The other bridge may already have saved and consumed this receipt while
        // our identical request was in flight. Its saved credential is definitive.
        this.assertBinding(saved, pending);
        this.cleanPending(pending);
        cleanup.push([input.ticketFile, pending.ticket_digest]);
        return saved;
      }
      if (!response.ok) {
        const code = object(body?.detail)?.code;
        // Only bounded protocol error identifiers may reach stderr/MCP.
        const safeCode = typeof code === "string" && /^[a-z][a-z0-9_]{0,79}$/.test(code)
          ? code : `http_${response.status}`;
        throw new Error(`credential_command_failed:${safeCode}`);
      }
      if (saved && (!session || saved.session_id !== session.session_id
          || saved.connection_epoch !== session.connection_epoch || saved.secret_token !== session.secret_token)) {
        throw new Error("credential_response_superseded:retry_pending_request");
      }
      const credential = parseCredential(body?.result);
      if ((pending.expected_agent_id && credential.agent_id !== pending.expected_agent_id)
          || (kind === "session.reconnect" && credential.session_id !== session!.session_id)) {
        throw new Error("credential_response_identity_mismatch");
      }
      const updated: PersistedSession = {
        ...credential, host_conversation_id_digest: pending.host_conversation_id_digest,
        conversation_binding_digest: pending.conversation_binding_digest,
        credential_command_id: pending.envelope.command_id,
        credential_auth_binding_digest: pending.auth_binding_digest,
        credential_ticket_digest: pending.ticket_digest ?? session?.credential_ticket_digest,
        delivery_ack_pending: credential.delivery_ref !== undefined,
      };
      this.writePrivate(this.options.sessionFile, updated);
      this.cleanPending(pending);
      cleanup.push([input.ticketFile, pending.ticket_digest]);
      return updated;
    });
    await this.cleanTickets(cleanup);
    return this.acknowledge(stored);
  }
}
