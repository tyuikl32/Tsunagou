import { describe, expect, it } from "vitest";
import { BASELINE_CAPABILITIES, evaluateConformance } from "@tsunagou/bridge-sdk";
import { OpenCodeAdapter, createOpenCodeInstallationPlan } from "../src/index.js";

describe("OpenCode adapter evidence boundary", () => {
  it("does not infer identity from a missing session digest", () => {
    expect(new OpenCodeAdapter().getIdentity({ adapter_installation_id: "i", host_kind: "opencode", host_version: "unknown" })).toBeUndefined();
  });
  it("returns the shared baseline shape with unknown host evidence", async () => {
    const checks = await new OpenCodeAdapter().probeCapabilities({ adapter_installation_id: "i", host_kind: "opencode", host_version: "unknown" });
    expect(checks.map((check) => check.name)).toEqual(BASELINE_CAPABILITIES);
    expect(evaluateConformance(checks).ready).toBe(false);
  });
  it("uses only a non-secret profile reference", () => {
    expect(() => createOpenCodeInstallationPlan("i", "api-token-profile", "install")).toThrow("invalid_non_secret_profile");
  });
});
