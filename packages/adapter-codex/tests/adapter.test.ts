import { describe, expect, it } from "vitest";
import { BASELINE_CAPABILITIES, evaluateConformance } from "@tsunagou/bridge-sdk";
import { CodexAdapter, createCodexInstallationPlan, createCodexWakePrompt } from "../src/index.js";

describe("Codex adapter evidence boundary", () => {
  it("requires a sanitized conversation digest for identity", () => {
    const adapter = new CodexAdapter();
    expect(adapter.getIdentity({ adapter_installation_id: "i", host_kind: "codex", host_version: "0.154" })).toBeUndefined();
    expect(adapter.getIdentity({ adapter_installation_id: "i", host_kind: "codex", host_version: "0.154", host_conversation_id_digest: "sha256:x" })).toEqual({
      installation_id: "i",
      host_kind: "codex",
      host_conversation_id_digest: "sha256:x",
    });
  });

  it("keeps missing real-host evidence unknown", async () => {
    const adapter = new CodexAdapter();
    const checks = await adapter.probeCapabilities({ adapter_installation_id: "i", host_kind: "codex", host_version: "0.154" });
    expect(checks).toHaveLength(BASELINE_CAPABILITIES.length);
    expect(evaluateConformance(checks).ready).toBe(false);
    expect(checks.every((check) => check.status === "unknown")).toBe(true);
  });

  it("does not accept capability evidence without a bound host identity", async () => {
    const adapter = new CodexAdapter();
    const checks = await adapter.probeCapabilities({
      adapter_installation_id: "i",
      host_kind: "codex",
      host_version: "0.154",
      baseline: { "task.lifecycle": { status: "supported", evidence: "probe" } },
    } as never);
    expect(checks.find((check) => check.name === "task.lifecycle")?.status).toBe("unknown");
  });

  it("records only sanitized lifecycle continuity", () => {
    const adapter = new CodexAdapter();
    const input = { adapter_installation_id: "i", host_kind: "codex", host_version: "0.154", host_conversation_id_digest: "digest-a" };
    adapter.observeLifecycle(input, { kind: "resume", host_conversation_id_digest: "digest-a" });
    expect(adapter.lifecycle()).toEqual({ kind: "resume", identity_continuity: "same", consistent: true, host_conversation_id_digest: "digest-a" });
    adapter.observeLifecycle(input, { kind: "fork", host_conversation_id_digest: "digest-a" });
    expect(adapter.lifecycle()?.consistent).toBe(false);
  });

  it("plans reversible profile changes without a credential", () => {
    const plan = createCodexInstallationPlan("i", "codex-profile", "install");
    expect(plan.bridge_command.join(" ")).not.toMatch(/token|secret/i);
    expect(createCodexInstallationPlan("i", "codex-profile", "uninstall").action).toBe("uninstall");
  });

  it("keeps unverified Codex wake explicitly unsupported", () => {
    const adapter = new CodexAdapter();
    const input = { adapter_installation_id: "i", host_kind: "codex", host_version: "0.155", host_conversation_id_digest: "digest" };
    expect(adapter.wakeAdapter.getWakeCapability(input)).toMatchObject({
      status: "unsupported",
      evidence: "codex_app_server_wake_unverified",
    });
    return expect(adapter.wake(input, { wake_id: "w-1", task_id: "t-1", assignment_id: "a-1" })).resolves.toMatchObject({
      wake_id: "w-1",
      status: "unsupported",
    });
  });

  it("returns accepted wake evidence only from an injected verified transport", async () => {
    const prompts: string[] = [];
    const adapter = new CodexAdapter({
      capability: { status: "supported", strength: "observed", evidence: "codex-probe:wake-v1" },
      transport: {
        async requestTurn(_input, prompt) {
          prompts.push(prompt);
          return { host_turn_id_digest: "sha256:turn-1", evidence: "app-server:turn-1" };
        },
      },
    });
    const input = { adapter_installation_id: "i", host_kind: "codex", host_version: "0.155", host_conversation_id_digest: "digest" };
    await expect(adapter.wake(input, { wake_id: "w-1", task_id: "t-1", assignment_id: "a-1" })).resolves.toEqual({
      wake_id: "w-1",
      status: "accepted",
      host_turn_id_digest: "sha256:turn-1",
      evidence: "app-server:turn-1",
      accepted_at: undefined,
    });
    expect(prompts[0]).toContain("wake_id=w-1");
    expect(prompts[0]).toContain("task_id=t-1");
    expect(prompts[0]).not.toContain("project");
  });

  it("rejects host wake responses without sanitized evidence", async () => {
    const adapter = new CodexAdapter({
      capability: { status: "supported", evidence: "codex-probe:wake-v1" },
      transport: { async requestTurn() { return { host_turn_id_digest: "", evidence: "" }; } },
    });
    const input = { adapter_installation_id: "i", host_kind: "codex", host_version: "0.155", host_conversation_id_digest: "digest" };
    await expect(adapter.wake(input, { wake_id: "w-2", task_id: "t-2", assignment_id: "a-2" })).resolves.toMatchObject({
      status: "failed",
      reason: "host_wake_evidence_required",
    });
  });

  it("does not expose host transport exception text", async () => {
    const adapter = new CodexAdapter({
      capability: { status: "supported", evidence: "codex-probe:wake-v1" },
      transport: { async requestTurn() { throw new Error("raw-turn-id-and-secret"); } },
    });
    const input = { adapter_installation_id: "i", host_kind: "codex", host_version: "0.155", host_conversation_id_digest: "digest" };
    await expect(adapter.wake(input, { wake_id: "w-3", task_id: "t-3", assignment_id: "a-3" })).resolves.toMatchObject({
      status: "failed",
      reason: "host_wake_transport_failed",
    });
  });

  it("keeps the wake prompt reference-only", () => {
    const prompt = createCodexWakePrompt({ wake_id: "w", task_id: "t", assignment_id: "a" });
    expect(prompt).toContain("worker.ready");
    expect(prompt).toContain("inbox");
    expect(() => createCodexWakePrompt({ wake_id: "", task_id: "t", assignment_id: "a" })).toThrow("invalid_wake_request");
  });
});
