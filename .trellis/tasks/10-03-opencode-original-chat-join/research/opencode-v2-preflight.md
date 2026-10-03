# Research: OpenCode 2.0.18 original-session preflight

- Query: Verify user-level identity tool, matching native MCP metadata, and original session continuity after reload.
- Scope: internal, local runtime probe
- Date: 2026-10-03

## Findings

**PASS for all three host prerequisites.** Tested installed @opencode/cli 2.0.18 using an isolated localhost server and a controlled local OpenAI-compatible model fixture. The fixture requested tools through the real host session engine; it did not fabricate tool context or MCP metadata.

1. Isolated user config `plugins: [absolute_directory]` loaded a directory with package.json type=module and index.js. Runtime plugin state was active.
2. Real host executed a zero-argument tool. execute(args, context) received sessionID, agent, messageID, id, progress, signal. sessionID exactly matched the created host session. Return `{content:[{type:"text",text:"..."}]}` completed successfully.
3. Native local MCP received `_meta["ai.opencode/sessionID"]` exactly matching that session ID (and an unrelated progressToken). Config is `mcp.servers.<name>` with type=local, command array and codemode=false.
4. POST /api/location/reload returned 204. Existing session retained its ID. A second plugin tool call in it reported that same ID.
5. User configuration loaded for a session directory different from server startup directory, without project-local plugin config.

### Exact minimal API

See opencode-v2-plugin-example.js:1. Installed v2 requires default export with id and setup(api), using api.tool.transform(registry => registry.add(...)). Plain JSON Schema input works. No external npm plugin dependency is needed.

A direct .mjs entry in plugins was rejected: configured plugin path must be a directory. Use package directory. options.codemode=false makes the tool directly exposed. Identity comes from context.sessionID, never tool arguments.

### Files, patterns, and related specs

- C:/Users/35742/AppData/Roaming/npm/node_modules/@opencode/cli/package.json: installed version 2.0.18.
- Same package bin/opencode.exe: actual tested runtime, embedded plugin and MCP implementation examined.
- .trellis/spec/adapters/index.md:5: per-call native identity contract.
- tools/conformance/probes/opencode/probe.py: existing host validation infrastructure.
- Active task design.md and implement.md: prerequisite gate and minimal scope.

### External references / versions

No external API claims needed. Locally installed 2.0.18 and its live /openapi.json were authoritative. Upstream dev/v1 plugin examples do not describe this installed API.

## Caveats / Not Found

This is host capability evidence, not final Tsunagou enrollment acceptance. Console claim, CLI signing, route selection, helper exclusion, second-session isolation, Chinese paths and final original-chat readiness still require tests.

All sessions/config/data/cache/state were isolated under this task research directory; no existing user conversation/config/provider credential or Tsunagou identity changed. Both server and model fixture are stopped. The main session safely moved raw artifacts to an OS temporary directory after an earlier removal command was blocked; only compact evidence remains in the task.
