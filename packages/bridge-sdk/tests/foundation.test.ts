import { describe, expect, it } from "vitest";

describe("workspace ESM boundaries", () => {
  it("loads all package entrypoints without starting a host", async () => {
    const entries = [
      "../src/index.js",
      "../../protocol-ts/src/index.js",
      "../../adapter-codex/src/index.js",
      "../../adapter-opencode/src/index.js",
      "../../adapter-zcode/src/index.js",
      "../../adapter-deepseek/src/index.js",
    ];
    for (const entry of entries) {
      expect(await import(entry)).toBeDefined();
    }
  });
});
