# Technical Design

## Boundary

The DSH adapter remains the source of trusted conversation identity and host cwd. The Python CLI remains the single authority for resolving the project used by `agent connect`, so manual CLI and MCP-triggered onboarding share one precedence rule.

## Resolution

For DeepSeek connect only, runtime resolution is: explicit `--project-root` selection, then the active adapter enrollment's `project_root`, then cwd/parent discovery. Existing configured runtime selection remains respected. The pending record must refer to a valid project manifest and its project id must match the resolved manifest.

The adapter supplies the pending project context to the CLI invocation when available, while the CLI repeats the pending lookup and validates the final runtime. This protects against other DSH entrypoints and prevents cwd from silently winning.

## Conflict handling

If the current DSH conversation is already bound to a different project than the pending record, connect fails with `onboarding_project_mismatch`. No bridge registration or new agent identity is created before the check.

## Compatibility

OpenCode/Codex are untouched. DSH without a pending enrollment keeps cwd fallback for manual onboarding. No enrollment status mutation is added.
