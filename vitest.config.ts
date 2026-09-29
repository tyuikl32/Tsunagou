import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["packages/*/tests/**/*.test.ts", "web/tests/**/*.test.ts"],
    passWithNoTests: false,
  },
});
