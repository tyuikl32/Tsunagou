import { describe, expect, it } from "vitest";
import { BASELINE_CAPABILITIES, evaluateConformance } from "@tsunagou/bridge-sdk";
import { DeepSeekAdapter, createDeepSeekInstallationPlan } from "../src/index.js";

describe("DeepSeek Harness adapter evidence boundary", () => {
  it("does not confuse a model API with a Harness session", async () => {
    const checks = await new DeepSeekAdapter().probeCapabilities({ adapter_installation_id: "i", host_kind: "deepseek", host_version: "model-api-only" });
    expect(checks).toHaveLength(BASELINE_CAPABILITIES.length);
    expect(evaluateConformance(checks).ready).toBe(false);
  });
  it("requires a host-issued digest for identity", () => {
    expect(new DeepSeekAdapter().getIdentity({ adapter_installation_id: "i", host_kind: "deepseek", host_version: "unknown" })).toBeUndefined();
  });
  it("rejects lifecycle events routed from another host adapter", () => {
    const adapter = new DeepSeekAdapter();
    expect(() => adapter.observeLifecycle(
      { adapter_installation_id: "i", host_kind: "opencode", host_version: "1", host_conversation_id_digest: "digest-a" },
      { kind: "resume", host_conversation_id_digest: "digest-a" },
    )).toThrow("adapter_host_mismatch");
  });
  it("does not accept a secret as a profile reference", () => {
    expect(() => createDeepSeekInstallationPlan("i", "secret-profile", "install")).toThrow("invalid_non_secret_profile");
  });
});
