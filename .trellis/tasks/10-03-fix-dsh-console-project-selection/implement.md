# Implementation Plan

1. Add a DSH adapter context/CLI argument path that carries the pending project root when available without accepting model-supplied paths.
2. Change CLI DSH runtime resolution to prefer pending enrollment over cwd discovery, while preserving explicit project selection and no-pending fallback.
3. Add project-manifest and existing-session mismatch guards before `connect_agent` can create identity or bridge state.
4. Add focused adapter/CLI tests for pending-vs-cwd, no-pending fallback, same-project success, and mismatch rejection.
5. Run targeted Python and Node tests, then the relevant full checks and inspect the final diff for scope.

## Verification

- DSH provider tests: 10 passed. Python focused/regression tests: 129 passed. Real CLI/daemon/bridge integration: 4 passed, including pending A with cwd B and route/identity checks.
- Ruff, mypy, pnpm check, docs validator, and git diff --check passed. Independent check reran Node 10/10 and related Python 22/22; its broader Python attempt was limited by Windows temporary-directory/ACL behavior.
- A real DSH Desktop chat has not yet been used for end-to-end acceptance. This task does not change the console's arrived/receipt behavior.
- A concurrent pair of connect attempts for the same DSH conversation but different projects can race between the route preflight and route write. The route write rejects the losing attempt, but its identity file may already exist. Ordinary sequential rebinding is rejected before identity creation; widening the lock scope is a separate connection-flow design change.
