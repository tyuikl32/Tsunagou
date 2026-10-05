# Research: DSH plugin integration

- Query: Minimal initialization and authenticated existing-session wake integration.
- Scope: internal source plus externally delivered plugin and installed DSH source, read-only.
- Date: 2026-10-05

## Findings

- External delivery report `D:/AB/测试文档记录/dsh/DSH唤醒插件-交付与验收报告.md` documents real background response and busy dedup on Desktop 0.2.0-rc.2. Cold restore, idle start, crash exactly-once and isolated live reload remain unverified. Header count of four missing cases differs from five listed cases.
- External plugin `index.js:189` validates static nonempty bindings; `:222` freezes config and resolves four injected services. `:240` registers effect-owned fixed status/wake routes. Preserve zero harness imports. A managed-file mode must allow initially empty bindings and reread them after authenticated enrollment; retain standalone static mode compatibility.
- `src/tsunagou/platform/host_registration.py:345` already installs Desktop identity provider via package entry file URL, managed YAML block and registration lock. Reuse this source installation shape for packaged `packages/dsh-wake-plugin`, not a new installer. Existing Desktop npm CLI requires exiting Desktop whereas direct file URL supports HMR.
- `src/tsunagou/application/agent_connection.py:126` writes host route before authenticated bootstrap; after bootstrap around `:166`, project/agent identity is verified. Add exact project/agent/conversation wake binding only after that verification.
- `src/tsunagou/application/onboarding.py:138` writes deepseek private routes; `_write_host_route` overwrites fields so explicitly preserve any added private wake descriptor on reconnect.
- `packages/adapter-deepseek-host/index.js:76` strips TSUNAGOU environment before CLI launch. Do not rely on inherited wake secrets; no model arguments may supply endpoint or bindings.
- `src/tsunagou/application/wake_assistance.py:95` resolves authenticated target route, verifies live bridge session, epoch and token. `_host` at `:370` currently passes only adapter/conversation/root/message; use verified target project/agent/route internally for DSH and never expose private endpoint/key fields.
- `src/tsunagou/application/host_wake_runner.py:80` currently rejects all deepseek. Add fixed HTTP DSH path with no proxy/redirect, literal loopback endpoint, finite timeout, response allowlist and distinction between pre-submit failure and unknown submit outcome.
- `wake_assistance.py:331` currently permits idle or running+can_queue. DSH unloaded existing session needs explicit supported normalization or branch; never call it running. 202 is accepted, not actual turn evidence.
- Tests: `tests/unit/test_host_registration_deepseek.py`, `tests/unit/test_wake_assistance.py`, `tests/unit/test_host_wake_runner.py`, identity-provider tests and bridge reminder stdio tests. External plugin has 27 simulated tests, not source integration proof.
- Guide `docs/overview/agent-wake-guide.md:53,63` has obsolete generic Desktop unsupported/UI guidance. Update supported plugin-first path while preserving unknown form/version boundaries. Related spec `.trellis/spec/adapters/reminder-hooks.md` needs equivalent adjustment.
- `pyproject.toml` wheel includes Python src only. Existing installation uses persistent source packages; include npm package in that distribution and avoid claiming standalone wheel alone carries it.

## Agreed minimal private contract

- Python owns private directory ACL and seeds `~/.tsunagou/hosts/deepseek-wake/managed.json` containing generated dedicated key and exact authenticated bindings; model tools never read it. Managed file avoids process-env restart and credentials-store parsing.
- Plugin reads managed configuration per request. Runtime sibling descriptor contains endpoint/generation only, atomically written with restrictive file mode under private parent; cleanup removes only its own generation. No second queue/scheduler.
- Target enrollment writes bindings only after authentication; revoked/stale target remains rejected by existing authority checks before HTTP.
- Existing explicit coordination status/wake tool remains the caller-facing API. No raw secret in CLI arguments, YAML, logs or public results.

## Installed webServer getter proof

Read `D:/dsh桌面版/resources/app.asar` by parsing ASAR header in memory, without extraction or touching config/secrets. Entry `dsh/node_modules/@deepseek-ai/dsh-host-webserver/lib/index.js` exports WebServer with public `get host() { return this.config.host; }` and `get port() { return this.listenedPort; }`. Config permits only `127.0.0.1` and `0.0.0.0`; awaited `Service.init` assigns listenedPort from `server.address().port`. Thus plugin can require host exactly 127.0.0.1 and valid actual port; no historical port or guessed environment endpoint required.

## Caveats / Not Found

- No live configs, credentials, chat history, HTTP requests, enrollment, wake or restart performed.
- No new real integration acceptance inferred from external success. User explicitly separates later testing from this source integration work.
- No external web references needed; delivery report and installed 0.2.0 source are the evidence.
