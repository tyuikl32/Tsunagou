# Research: OpenCode original-chat end-to-end acceptance

- Query: Validate the implemented minimal original-chat join flow with actual host, CLI, daemon, bridge, console application service, and isolated state.
- Scope: internal real-host acceptance with deterministic local model fixture
- Date: 2026-10-03

## Findings

**PASS.** The completed runner exited 0 on 2026-10-03. OpenCode package version was 2.0.18. Python CLI ran from the checkout virtual environment and compiled bridge used the actual product implementation. No CLI, enrollment, daemon, bridge, or native MCP behavior was mocked. Only the model response was supplied by a deterministic localhost OpenAI-compatible SSE fixture requesting one real host tool per turn.

### Isolation

Created a disposable Chinese/space-containing coordination project and a separate Chinese/space-containing original-chat working directory. The main session initialized only the disposable project's Git repository. Child USERPROFILE and XDG paths, OpenCode config/data/cache/state, console index/profile, pending store, private routes and daemon state all pointed inside the disposable runtime directory. Python Path.home and EnrollmentStore paths were asserted before enrollment. No user project, existing conversation, real provider credential, or user global config was changed.

### Passed scenarios

1. Created real OpenCode original and second sessions before installation. Actual `agent prepare --adapter opencode` installed the global no-credential plugin/MCP entry without enrolling an Agent.
2. Repeated prepare preserved exact config bytes. Reload returned to the same original session ID.
3. Actual project init and daemon start created a temporary Chinese-path project with host wake disabled.
4. Actual console `enrollment.prepare(... vendor="opencode", role="worker")` left a pending request. No project or identity was supplied by model tool arguments.
5. Original session invoked installed `tsunagou_connect`; it executed actual `agent join --adapter opencode`, chose the requested project/worker role, and returned enrolled with host_ready=false.
6. Actual console status remained waiting after helper enrollment.
7. Second real session could not claim the original request, and its native context call did not obtain the original Agent identity.
8. Original session repeated connect and retained the same Agent ID.
9. Original session called native MCP context__project_read. Context identified the same Agent; actual console status became arrived through the exact receipt and fresh roster check.
10. A second configuration reload retained both host session and Agent identity on another native context read.
11. Host configuration bytes remained unchanged through join/retry/native context, establishing per-session route-only connection behavior.
12. Both temporary host and daemon were stopped and the model fixture shut down at completion.

Boolean evidence is retained in `live-acceptance-evidence.json`; identifiers and credentials are deliberately excluded.

### Observed host timing

The first immediate post-reload model turn ran before native MCP catalog loading completed. Host logs showed the MCP connection completing about 320 ms after location reload. The final successful runner waited for `/api/mcp` to report `status.status == "connected"` before issuing the next turn. No host compatibility framework or product code workaround was added. User instructions should allow MCP to finish reconnecting after reload.

### Files and implementation patterns

- `src/tsunagou/platform/opencode_onboarding.py`: actual user-level prepare and managed plugin/MCP registration used by the test.
- `packages/adapter-opencode/connect.js`: actual zero-argument host action used the real execution context and sanitized CLI subprocess environment.
- `src/tsunagou/cli/app.py`: actual prepare/join commands used by the installed plugin.
- `src/tsunagou/console/enrollment.py`: actual prepare/status application services, without HTTP/UI mocks or daemon roster stubs.
- `.trellis/spec/adapters/index.md`: identity isolation and original-chat readiness contracts.
- Task `prd.md`, `design.md`, `implement.md`: current-chat, Chinese path, helper exclusion, and reload acceptance requirements.

### External references / versions

No external sources were required. Live installed OpenCode 2.0.18 API and the current checkout implementation provided evidence.

## Caveats / Not Found

This acceptance used the real host server/API with a controlled local model fixture, not a human-driven OpenCode Desktop click-through or a paid production model round. The UI waiting/arrived behavior was checked through its actual console application services; no browser UI rendering claim is made. It does not re-certify all eleven historic host baseline capabilities or automatic wake, which remains out of scope.

Raw runtime files contain temporary credentials and identifiers and must remain outside commits. The main session handles relocation of `live-runtime/` and the one-off `live_acceptance.py` runner to OS temporary storage. Only this report and sanitized boolean evidence belong in task records.
