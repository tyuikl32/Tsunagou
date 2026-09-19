import { describe, expect, it } from "vitest";
import { BASELINE_CAPABILITIES, evaluateConformance } from "@tsunagou/bridge-sdk";
import { CodexAdapter, createCodexInstallationPlan } from "../src/index.js";

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
});
