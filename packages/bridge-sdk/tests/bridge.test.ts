import { describe, expect, it } from "vitest";
import {
  BASELINE_CAPABILITIES,
  ContextRenderer,
  type BridgeTransport,
  type InboxSource,
  createMcpTools,
  createStdioForwarder,
  createBridge,
  evaluateConformance,
  validateBridgeTicket,
} from "../src/index.js";

describe("bridge session isolation and recovery", () => {
  it("keeps credentials and deduplication state private to each session", async () => {
    const calls: Array<{ sessionId?: string; authorization?: string }> = [];
    const transport: BridgeTransport = {
      async send<T>(_envelope: unknown, context) {
        calls.push({ sessionId: context?.sessionId, authorization: context?.authorization });
        return { ok: true } as T;
      },
    };
    const a = createBridge(transport, {
      connection: { sessionId: "session-a", connectionEpoch: 1, capabilities: new Set() },
      credentialProvider: () => "secret-a",
    });
    const b = createBridge(transport, {
      connection: { sessionId: "session-b", connectionEpoch: 1, capabilities: new Set() },
      credentialProvider: () => "secret-b",
    });
    const envelope = { command_id: "cmd-1", protocol_version: "1", schema_bundle_digest: "sha256:x", payload: {} };
    await a.send(envelope);
    await a.send(envelope);
    await b.send(envelope);
    expect(calls).toEqual([
      { sessionId: "session-a", authorization: "secret-a" },
      { sessionId: "session-b", authorization: "secret-b" },
    ]);
  });

  it("rejects stale epochs and reports unknown enhancements as unknown", () => {
    const bridge = createBridge({ send: async () => ({}) }, {
      connection: { sessionId: "session-a", connectionEpoch: 2, capabilities: new Set() },
    });
    expect(() => bridge.reconnect({ sessionId: "session-a", connectionEpoch: 1, capabilities: new Set() })).toThrow("stale_connection_epoch");
    const report = bridge.conformance({ wake: undefined } as never);
    expect(report.ready).toBe(false);
    expect(report.checks.find((check) => check.name === "identity.session_isolation")?.status).toBe("unknown");
  });

  it("treats an identical reconnect result as an idempotent replay", () => {
    const capabilities = new Set(["task.lifecycle"]);
    const bridge = createBridge({ send: async () => ({}) }, {
      connection: { sessionId: "session-a", connectionEpoch: 2, capabilities },
    });
    expect(bridge.reconnect({ sessionId: "session-a", connectionEpoch: 2, capabilities: new Set(capabilities) })).toBe(false);
    expect(bridge.reconnect({ sessionId: "session-a", connectionEpoch: 3, capabilities })).toBe(true);
    expect(() => bridge.reconnect({ sessionId: "session-a", connectionEpoch: 3, capabilities: new Set() })).toThrow("connection_epoch_conflict");
  });

  it("re-enters the transport after reconnect so the new epoch is fenced", async () => {
    const epochs: number[] = [];
    const bridge = createBridge({
      async send<T>(_envelope, context) {
        epochs.push(context?.connectionEpoch ?? -1);
        return { accepted: true } as T;
      },
    }, { connection: { sessionId: "session-a", connectionEpoch: 1, capabilities: new Set() } });
    const envelope = { command_id: "cmd-epoch", protocol_version: "1", schema_bundle_digest: "d", payload: {} };
    await bridge.send(envelope, "task.claim");
    await bridge.send(envelope, "task.claim");
    bridge.reconnect({ sessionId: "session-a", connectionEpoch: 2, capabilities: new Set() });
    await bridge.send(envelope, "task.claim");
    expect(epochs).toEqual([1, 2]);
  });

  it("deduplicates concurrent commands and rejects command-id reuse with different input", async () => {
    let calls = 0;
    let release!: () => void;
    const blocked = new Promise<void>((resolve) => { release = resolve; });
    const bridge = createBridge({
      async send<T>() {
        calls += 1;
        await blocked;
        return { accepted: true } as T;
      },
    }, { connection: { sessionId: "session-a", connectionEpoch: 1, capabilities: new Set() } });
    const envelope = { command_id: "cmd-1", protocol_version: "1", schema_bundle_digest: "sha256:x", payload: { task_id: "t-1" } };
    const first = bridge.send(envelope, "task.claim");
    const duplicate = bridge.send({ ...envelope, payload: { task_id: "t-1" } }, "task.claim");
    release();
    await expect(Promise.all([first, duplicate])).resolves.toEqual([{ accepted: true }, { accepted: true }]);
    expect(calls).toBe(1);
    await expect(bridge.send({ ...envelope, payload: { task_id: "t-2" } }, "task.claim")).rejects.toThrow("idempotency_conflict");
  });

  it("retries transport failures but not typed non-retryable problems", async () => {
    let transientCalls = 0;
    const transient = createBridge({
      async send<T>() {
        transientCalls += 1;
        if (transientCalls === 1) throw new Error("socket_closed");
        return { ok: true } as T;
      },
    }, { connection: { sessionId: "session-a", connectionEpoch: 1, capabilities: new Set() }, maxRetries: 1 });
    await expect(transient.send({ command_id: "cmd-a", protocol_version: "1", schema_bundle_digest: "d", payload: {} })).resolves.toEqual({ ok: true });
    expect(transientCalls).toBe(2);

    let deniedCalls = 0;
    const denied = createBridge({
      async send() {
        deniedCalls += 1;
        throw Object.assign(new Error("scope_denied"), { status: 403, code: "scope_denied" });
      },
    }, { connection: { sessionId: "session-a", connectionEpoch: 1, capabilities: new Set() }, maxRetries: 3 });
    await expect(denied.send({ command_id: "cmd-b", protocol_version: "1", schema_bundle_digest: "d", payload: {} })).rejects.toThrow("scope_denied");
    expect(deniedCalls).toBe(1);

    let unknownCalls = 0;
    const unknown = createBridge({
      async send() {
        unknownCalls += 1;
        throw new Error("unknown_external_result");
      },
    }, { connection: { sessionId: "session-a", connectionEpoch: 1, capabilities: new Set() }, maxRetries: 3 });
    await expect(unknown.send({ command_id: "cmd-c", protocol_version: "1", schema_bundle_digest: "d", payload: {} })).rejects.toThrow("unknown_external_result");
    expect(unknownCalls).toBe(1);
  });

  it("keeps fetch, presentation and acknowledgement distinct and deduplicated", async () => {
    const calls: string[] = [];
    const source: InboxSource = {
      async claim() {
        calls.push("claim");
        return { items: [
          { delivery_id: "d-1", message_id: "m-1", recipient_session_id: "session-a" },
          { delivery_id: "d-private", message_id: "m-private", recipient_session_id: "session-b" },
        ], cursor: "next" };
      },
      async fetch(_sessionId, deliveryId) {
        calls.push(`fetch:${deliveryId}`);
        return { delivery_id: deliveryId, message_id: "m-1", recipient_session_id: "session-a", body: "hello" };
      },
      async presented(_sessionId, deliveryId) { calls.push(`presented:${deliveryId}`); },
      async ack(_sessionId, deliveryId) { calls.push(`ack:${deliveryId}`); },
    };
    const bridge = createBridge({ send: async () => ({}) }, {
      connection: { sessionId: "session-a", connectionEpoch: 1, capabilities: new Set() },
    });
    await expect(bridge.pullInbox(source)).resolves.toMatchObject({ items: [{ delivery_id: "d-1", body: "hello" }], pending_delivery_ids: [] });
    await expect(bridge.pullInbox(source, "next")).resolves.toMatchObject({ items: [], pending_delivery_ids: ["d-1"] });
    await expect(bridge.ackInbox(source, "d-1")).rejects.toThrow("inbox_delivery_not_presented");
    await expect(bridge.markInboxPresented(source, "d-1", "sha256:evidence")).resolves.toBe(true);
    await expect(bridge.markInboxPresented(source, "d-1", "sha256:evidence")).resolves.toBe(false);
    await expect(bridge.ackInbox(source, "d-1")).resolves.toBe(true);
    await expect(bridge.ackInbox(source, "d-1")).resolves.toBe(false);
    expect(calls).toEqual(["claim", "fetch:d-1", "claim", "presented:d-1", "ack:d-1"]);
  });
});

describe("host-neutral conformance and boundaries", () => {
  it("requires all eleven checks and evidence before ready", () => {
    const checks = BASELINE_CAPABILITIES.map((name) => ({ name, status: "supported" as const, evidence: "probe-1" }));
    expect(evaluateConformance(checks).ready).toBe(true);
    expect(evaluateConformance(checks.slice(0, -1)).missing).toContain("delivery.deduplicate");
    expect(evaluateConformance(BASELINE_CAPABILITIES.map((name) => ({ name, status: "supported" as const }))).missing).toEqual(BASELINE_CAPABILITIES);
    expect(evaluateConformance(BASELINE_CAPABILITIES.map((name) => ({ name, status: "supported" as const, evidence: "" }))).missing).toEqual(BASELINE_CAPABILITIES);
  });

  it("keeps bridge tickets separate from user-control tickets", () => {
    const ticket = { ticket_id: "t-1", principal_kind: "T" as const, mode: "attach" as const, adapter_kind: "codex", expires_at: "2099-01-01T00:00:00Z" };
    expect(() => validateBridgeTicket(ticket, "managed_launch")).toThrow("bridge_mode_mismatch");
    expect(() => validateBridgeTicket({ ...ticket, principal_kind: "U" as never }, "attach")).toThrow("invalid_bridge_ticket_principal");
  });

  it("does not render sensitive sections and bounds prompt context", () => {
    const result = new ContextRenderer().render([
      { name: "project", body: "visible" },
      { name: "credentials", body: "secret", sensitive: true },
      { name: "large", body: "x".repeat(100) },
    ], 40);
    expect(result.text).toContain("visible");
    expect(result.text).not.toContain("secret");
    expect(result.truncated).toBe(true);
  });

  it("keeps MCP descriptors and stdio forwarding session-scoped", async () => {
    const tools = createMcpTools([
      { name: "task__submit", command_kind: "task.submit", input_schema: {} },
      { name: "token.inspect", command_kind: "task.submit", input_schema: {} },
    ]);
    expect(tools.map((tool) => tool.name)).toEqual(["task__submit"]);
    expect(() => createMcpTools([{ name: "task.submit", command_kind: "task.submit", input_schema: {} }])).toThrow("invalid_mcp_tool_name");
    const forwarder = createStdioForwarder("session-a");
    await expect(forwarder.forward({ command_id: "c", protocol_version: "1", schema_bundle_digest: "d", payload: {} }, async () => "ok")).resolves.toBe("ok");
  });
});
