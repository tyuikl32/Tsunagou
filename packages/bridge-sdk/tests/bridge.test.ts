import { describe, expect, it } from "vitest";
import {
  BASELINE_CAPABILITIES,
  ContextRenderer,
  type BridgeTransport,
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
});

describe("host-neutral conformance and boundaries", () => {
  it("requires all eleven checks and evidence before ready", () => {
    const checks = BASELINE_CAPABILITIES.map((name) => ({ name, status: "supported" as const, evidence: "probe-1" }));
    expect(evaluateConformance(checks).ready).toBe(true);
    expect(evaluateConformance(checks.slice(0, -1)).missing).toContain("delivery.deduplicate");
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
      { name: "task.submit", command_kind: "task.submit", input_schema: {} },
      { name: "token.inspect", command_kind: "task.submit", input_schema: {} },
    ]);
    expect(tools.map((tool) => tool.name)).toEqual(["task.submit"]);
    const forwarder = createStdioForwarder("session-a");
    await expect(forwarder.forward({ command_id: "c", protocol_version: "1", schema_bundle_digest: "d", payload: {} }, async () => "ok")).resolves.toBe("ok");
  });
});
