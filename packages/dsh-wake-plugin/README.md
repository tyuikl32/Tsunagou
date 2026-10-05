# @tsunagou/dsh-wake-plugin

A DeepSeek Harness Desktop host plugin that wakes an **existing** session so it
reads its own Tsunagou context and inbox.

A local caller posts a small identity tuple; the plugin submits one fixed read
reminder into that session through `sessionController.prompt({ mode: 'queue' })`.
No window is opened, no focus or clipboard is touched, and no keystroke is sent.

---

## Supported version

| | |
|---|---|
| Runtime | DeepSeek Harness **Desktop** |
| Verified against | `0.2.0-rc.2` |
| Node | bundled runtime (`24.x`); the plugin itself needs `>=22` |
| Platform | Windows (developed and checked there); no Windows-only API is used |

Verified service versions in that runtime: `@deepseek-ai/cordis` 4.0.4,
`dsh-agent` / `dsh-api-session-controller` / `dsh-credentials` /
`dsh-host-webserver` `0.2.0-rc.2`.

> Do not develop or test against `~/.dsh/profiles/node_modules`. That directory
> holds a *different*, older dependency copy (`0.1.5-rc.2`). The installed
> Desktop runtime lives inside `app.asar` and is the only authority.

---

## Standalone install and enable

Tsunagou users normally use `agent prepare --adapter deepseek --profile desktop`
and original-session onboarding; see managed initialization below. The manual
steps in this section are only for standalone installation.

The plugin is a normal npm package. It has **no runtime dependencies**: it
imports Node built-ins only and receives every DSH service through Cordis
injection. That is deliberate — a profile's `node_modules` cannot reliably
resolve the harness's own packages, so a plugin that imports `@deepseek-ai/*`
at runtime would fail to load.

### 1. Install the package into the Desktop profile

`dsh plugin` requires the profile to exist and **Desktop to be fully quit**:

```
dsh plugin --profile desktop add <path-to-this-package>
```

Use the package directory or an `npm pack` tarball produced from it:

```
npm pack                     # -> tsunagou-dsh-wake-plugin-0.1.0.tgz
dsh plugin --profile desktop add ./tsunagou-dsh-wake-plugin-0.1.0.tgz
```

### 2. Add the loader row

Edit `~/.dsh/profiles/desktop/cordis.patch.yml` and insert one entry. The
`insert:` list form is required — the profile root is an empty entry list.

```yaml
- insert:
    - id: tsunagou-wake
      name: '@tsunagou/dsh-wake-plugin'
      config:
        keyEnv: TSUNAGOU_WAKE_KEY
        bindings:
          - project_id: '<tsunagou project id>'
            agent_id: '<tsunagou agent id>'
            session_id: '<DSH session id of the target conversation>'
```

A `file:///` URL also works if you prefer to point at the source directory
instead of installing a package, exactly like the existing Tsunagou adapter row:

```yaml
      name: 'file:///D:/path/to/dsh-wake-plugin/index.js'
```

### 3. Credentials

Tsunagou initialization uses managed mode (below), without environment secrets.
Legacy standalone mode resolves `keyEnv` through DSH's credentials service.
Desktop 0.2.0 reads inherited process environment and its credentials store,
not `.env`. Updating a user environment variable does not update an already
running Desktop process. Never print a key or put its value in profile YAML.

### 4. Restart if needed

Desktop applies profile changes live when its HMR service is present. If a
change reports `restart-required`, quit and reopen Desktop. Save work first; do
not restart a Desktop that is hosting your development session.

### Verify it loaded

If the plugin fails to activate, check the loader entry's fiber phase and the
package-manager diagnostics:

- `ctx.pluginManager.listPlugins()` — look for `fiberPhase: 'failed'`.
- The `dsh plugin` command prints `diagnostics: <path>` when pnpm fails.

---

## Finding the host address

Do not hard-code a port. Read it from the running host:

- The Desktop host passes `--port <n>` when it boots, and the environment of a
  child process of that host carries `DSH_WEB_URL`
  (for example `http://127.0.0.1:19387`).
- A caller that already runs inside the host can read `ctx.webServer.port`.

The plugin registers its routes on the host's existing web server, so it is
reachable at `http://127.0.0.1:<port>/tsunagou/...`. It adds no second listener.

---

## Endpoints

Both require `Authorization: Bearer <key>`, `Content-Type: application/json`,
and a loopback peer. Both accept **only** the fields listed; any extra field is
refused, so no caller can choose content, mode, an endpoint or a command.

### `POST /tsunagou/wake/status`

```json
{ "project_id": "...", "agent_id": "...", "session_id": "..." }
```

```json
{
  "ok": true,
  "project_id": "...",
  "agent_id": "...",
  "session_id": "...",
  "exists": true,
  "loaded": false,
  "state": "unloaded",
  "queueable": true
}
```

### `POST /tsunagou/wake`

```json
{ "project_id": "...", "agent_id": "...", "session_id": "...", "message_id": "..." }
```

```json
{ "ok": true, "accepted": true, "request_id": "tsunagou-wake-v1:<64 hex>" }
```

`202` means **admitted, or already admitted under this request id**. It does
**not** mean a turn started, that the session read anything, or that any work
completed. Confirm execution through the session log.

### Status fields

| Field | Meaning |
|---|---|
| `exists` | A live agent has this id, **or** durable storage has this session. A live-registry miss is never reported as absence. |
| `loaded` | A live agent currently holds the session. |
| `state` | `idle` (loaded, between turns), `running` (loaded, mid-turn), `unloaded` (persisted, no live agent), `unknown` (not found). |
| `queueable` | `exists`. The one case this cannot see is a session owned by subagent routing; only the wake call can report that (`session_subagent_owned`). |

The status call is read-only: it never activates, resumes, creates or forks a
session, and it returns no chat content and no session listing.

---

## Behaviour by session state

| Target | What `mode: 'queue'` does |
|---|---|
| Loaded and idle | Opens a new turn immediately. |
| Loaded and running | Queues for the next turn boundary; the current turn is not interrupted. |
| Persisted, not loaded | The host resumes the session from durable storage, then admits the reminder. |
| Does not exist | Refused with `session_not_found`. No session is created or forked. |

`queue` is the only mode this plugin submits. It never uses `steer`, never
falls back to `followup`, and has no scheduler, retry driver or durable queue of
its own.

### What resume preserves

The host, not this plugin, owns resume:

- **Working directory** — taken from the session's own header. The resume call
  passes no `cwd`, so nothing is overridden.
- **Agent preset** — read from the session's projection, not from the current
  deployment default.
- **Model** — the session-local selection resolves against the durable request
  header recorded in that session's log. A session whose log carries no request
  header yet falls back to the host's current default model; that is host
  behaviour, and this plugin cannot change it.
- **Approval policy** — folded from the session's own durable `approval/policy`
  events.

This plugin therefore cannot loosen permissions, swap a model, or recreate a
session to make a call succeed.

---

## Request id

```
requestId = "tsunagou-wake-v1:" + sha256(JSON.stringify([project_id, agent_id, session_id, message_id]))
```

Same tuple → same id → same body, so a retry reuses the host's de-duplication.
The id is never time-stamped and never randomised.

**The host compares request ids only.** For an id it has already queued or
logged it returns `accepted: true` and ignores the new content — so reusing one
`message_id` for different content would silently drop the second body. Use one
`message_id` per business intent.

De-duplication is the host's, and it is durable: it scans the session's pending
inbox and its persisted log. This plugin deliberately adds no second store.

---

## Errors

| HTTP | `error` | Cause |
|---|---|---|
| 400 | `invalid_json` / `invalid_field` | malformed or unexpected body |
| 401 | `unauthorized` | wrong, missing or empty bearer key; or a non-loopback peer |
| 403 | `target_not_bound` | the exact `(project_id, agent_id, session_id)` is not configured |
| 404 | `session_not_found` | no such session |
| 405 / 413 / 415 | `method_not_allowed` / `body_too_large` / `unsupported_content_type` | transport misuse |
| 409 | `session_subagent_owned` | session belongs to subagent routing; use subagent delivery |
| 409 | `session_write_locked` | another process holds the write handle (Desktop usually holds it) |
| 502 | `submit_failed` | the host rejected the prompt for another reason |
| 504 | `submit_unknown` | the outcome is genuinely unknown (submit timed out) |

`504` never reports success and never silently retries. First inspect the original
request's outcome. If a retry is justified, preserve the same `message_id` so the
host can de-duplicate; this is not a crash-safe exactly-once guarantee. Tsunagou
keeps its existing unknown-outcome guard and does not blindly resend.

Reasons are deliberately de-identified: no session content, no file paths, no
credential material, no secret values.

---

## Uninstall

1. Remove the `tsunagou-wake` entry from
   `~/.dsh/profiles/desktop/cordis.patch.yml`.
2. `dsh plugin --profile desktop remove @tsunagou/dsh-wake-plugin` (Desktop
   fully quit), or delete the `file:///` directory if you used that form.
3. Remove the key from wherever you set it (`TSUNAGOU_WAKE_KEY` in the
   environment or credential store).

A reload removes both routes before re-registering them, so a repeated load does
not collide or double-register. Uninstalling touches only this plugin's own
entry and key; it must not remove other profile configuration.

---

## Initialization responsibilities

Tsunagou prepares the packaged loader row and a private managed configuration,
then adds the exact binding after authenticated original-session onboarding.
Normal initialization requires no manually copied key, port or session ID.
The standalone configuration above remains available for independent installs.

The plugin does not discover sessions or create bindings from requests.
**Network requests can never add a binding.**
Bindings are exact triples — there is no `cwd` prefix matching, because a
business directory and a coordination project directory may legitimately differ.

Outside the plugin, Tsunagou enforces the authenticated sending
agent, message-permission checks, and the authoritative binding source of truth.

---

## Verification client

`example/client.mjs` is a minimal caller for testing and later integration. It
reads the endpoint and key from the environment, refuses to send the key to a
non-loopback host, and prints the response.

```
TSUNAGOU_WAKE_URL=http://127.0.0.1:19387 \
TSUNAGOU_WAKE_KEY=... \
node example/client.mjs status --project-id P --agent-id A --session-id S

TSUNAGOU_WAKE_URL=http://127.0.0.1:19387 \
TSUNAGOU_WAKE_KEY=... \
node example/client.mjs wake --project-id P --agent-id A --session-id S --message-id M
```

## Tests

```
node --test test/plugin.test.mjs
```

These are **host doubles**: no Desktop process, no network. They check this
plugin's own contract — authentication, exact binding, request-id derivation,
which host calls it makes, and that status never submits. They prove nothing
about the real host. The external 2026-10-05 delivery report proves a background business reply and busy queue/dedup; cold restore and idle startup remain unverified live.

## Limitations

- **Not exactly-once.** If the process dies between admitting a prompt and
  writing it durably, a retry may or may not be de-duplicated. The host's own
  log is the authority; this plugin makes no stronger promise.
- **`queueable` cannot detect subagent ownership** (see the status table).
- **One key, all bindings.** Every configured binding shares the single bearer
  key; there is no per-binding key.
- **Loopback only.** No cross-machine support by design.

## Tsunagou managed initialization

The generated profile row contains only `config.managedFile`, an absolute path
in a user-private directory prepared by Tsunagou. It takes precedence over
legacy static configuration. The JSON is `{format_version:1,key,bindings}`;
bindings are exact project/Agent/session triples and may initially be empty.
Tsunagou adds bindings only after authenticated original-session enrollment.
Each request reads one current snapshot; malformed or missing files fail closed.
No request can add bindings, provide a path, or choose reminder content.

The plugin publishes sibling `runtime.json` from the actual bound loopback
server address. It contains format_version=1, contract_version=1,
plugin_version, endpoint, instance_id and pid, never the key or session IDs.
The plugin creates no directory; initialization must protect the parent first.
Publication uses an atomic rename, and disposal removes only its own instance.
This descriptor proves plugin activation, not recipient execution or actual
DSH version compatibility. The tested Desktop baseline is 0.2.0-rc.2; other versions are not claimed
validated merely because this descriptor exists. Credential and binding updates do not require
restarting Desktop; the managed file is read on every request.
