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

  it("plans reversible profile changes without a credential", () => {
    const plan = createCodexInstallationPlan("i", "codex-profile", "install");
    expect(plan.bridge_command.join(" ")).not.toMatch(/token|secret/i);
    expect(createCodexInstallationPlan("i", "codex-profile", "uninstall").action).toBe("uninstall");
  });
});
