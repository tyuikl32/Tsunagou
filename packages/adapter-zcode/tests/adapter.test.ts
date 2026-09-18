import { describe, expect, it } from "vitest";
import { ZCodeAdapter, createZCodeInstallationPlan } from "../src/index.js";

describe("ZCode adapter evidence boundary", () => {
  it("does not treat a configured hook as identity evidence", () => {
    expect(new ZCodeAdapter().getIdentity({ adapter_installation_id: "i", host_kind: "zcode", host_version: "unknown" })).toBeUndefined();
  });
  it("records lifecycle semantics without creating domain state", () => {
    const adapter = new ZCodeAdapter();
    adapter.observeLifecycle({ adapter_installation_id: "i", host_kind: "zcode", host_version: "unknown" }, { kind: "clear" });
    expect(adapter.lifecycle()?.kind).toBe("clear");
  });
  it("exposes a reversible profile plan", () => {
    expect(createZCodeInstallationPlan("i", "zcode-profile", "uninstall").action).toBe("uninstall");
  });
});
