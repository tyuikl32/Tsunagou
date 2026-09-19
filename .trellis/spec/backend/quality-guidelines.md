# Quality gates

Sources: [validation](../../../docs/implementation/validation.md), [command catalog](../../../docs/implementation/command-catalog.md).

T01 establishes Ruff/mypy/pytest and exact invocations in project configuration. T03 establishes schema/codegen fixtures. Run the relevant task checks, then required shared gates; do not invent command success before tooling exists.

Every public command must have one registered policy, typed request/response and positive/negative authorization tests. JSON Schema is authoritative; generated files and OpenAPI must regenerate without diff. Test ownership, stale epochs, all-or-none mutations and recipient-only visibility.

Use injected clocks for TTL/backoff and real SQLite/Git fixtures for persistence. Keep Windows release-blocking and record actual macOS/Linux coverage. Four host simulator passes do not replace four live-host records. Research outcome gates are separate from engineering correctness.

Only user-approved product boundaries can change; ordinary internal implementation choices are recorded by the main implementation Agent. Keep PRD/design/implement and public documentation aligned.

## Node workspace install and check contract

### 1. Scope / Trigger

Apply when changing the root Node toolchain, workspace membership, TypeScript build settings, or dependency build-script policy. This prevents a clean checkout from passing only because one machine has stale build output or a previously approved lifecycle script.

### 2. Signatures

- Install: `corepack pnpm install --frozen-lockfile`
- Type-check: `corepack pnpm run check`
- Root script: `"check": "corepack pnpm -r run check"`
- Build allowlist: `pnpm-workspace.yaml` contains only `allowBuilds.esbuild: true` until another dependency has a reviewed need.

### 3. Contracts

- Corepack must honor the exact `packageManager` version in `package.json`.
- Every `packages/*/package.json` must define a non-empty `scripts.check`; recursive execution must not silently skip a workspace.
- Do not use root `tsc -b` without a real root `tsconfig.json` and reviewed project references.
- Do not enable `composite` merely to create incremental caches. Tracked generated outputs and `tsconfig.tsbuildinfo` must remain unchanged after a clean check.

### 4. Validation & Error Matrix

| Condition | Required outcome |
|---|---|
| Build-script policy is missing, placeholder, or broader than reviewed | Frozen install fails; do not use interactive blanket approval |
| Root check names a missing `tsconfig.json` | Gate fails with the TypeScript error; fix the root script/config rather than suppressing it |
| A workspace lacks `scripts.check` | Integration policy test fails |
| Type-check changes generated output or build caches | Generated-diff gate fails; restore or intentionally regenerate reviewed artifacts |

### 5. Good / Base / Bad Cases

- Good: frozen install runs only the reviewed esbuild postinstall, then all six workspaces type-check.
- Base: a new workspace is added without a check script; policy regression catches it before release.
- Bad: run `pnpm approve-builds` interactively and accept every dependency, or keep a root `tsc -b` command with no root config.

### 6. Tests Required

- `tests/integration/test_toolchain_policy.py` asserts the sole build allowlist entry, the exact recursive root check, and a check script for every workspace package.
- Run frozen install, root check, Vitest, and `git diff --exit-code -- 'packages/*/dist' 'packages/*/tsconfig.tsbuildinfo'`.

### 7. Wrong vs Correct

Wrong:

```yaml
allowBuilds:
  esbuild: set this to true or false
```

Correct:

```yaml
allowBuilds:
  esbuild: true
```
