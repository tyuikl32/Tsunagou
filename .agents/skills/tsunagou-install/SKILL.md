---
name: tsunagou-install
description: "Install Tsunagou from its GitHub repository, including Python runtime dependencies, the Node stdio bridge, and Agent onboarding skills. Use when a user asks to install, clone, update, or set up Tsunagou from GitHub. Do not use this for normal project onboarding after Tsunagou is already installed."
---

# Install Tsunagou from GitHub

Use this skill when the user says they want to install Tsunagou from GitHub. The intended outcome is a usable local checkout, a working Python CLI, a built stdio bridge, discoverable Tsunagou skills, and (when the user explicitly means the current business project) project-local Tsunagou entries. After installation, hand off to `tsunagou-agent-onboarding` for daemon startup and Agent enrollment.

## Safety and user intent

Installation changes local files and may create user-level skill directories. Confirm the destination when an existing path is ambiguous. Never delete a directory, reset a repository, overwrite a non-Tsunagou skill, or run a remote script piped directly into a shell. Use the repository's checked-in installer after cloning.

Do not request or print control tokens, session tokens, ticket files, or private host configuration. A source-only installation does not initialize a coordination project or create Agent identities. A project-root installation may initialize the explicitly selected project and materialize non-secret entries, but it still does not create Agent identities.

## Default source and destination

Use the official repository unless the user specifies another trusted ref:

```text
https://github.com/tyuikl32/Tsunagou.git
```

Use an explicit source/destination first. Otherwise inspect `~/.tsunagou/installation.json` for the registered source, then the checkout containing this installer. Only a fresh installation without either uses `~/Tsunagou`. When the user selected a checkout, pass its actual `--source-root` so a stale registration cannot override it. Do not reset or silently switch an existing checkout to satisfy a requested ref.

## Installation workflow

1. Check that `git` is available. Check for Python 3.13, `uv` or `python`, and Node 24.19.x with Corepack/pnpm. Report missing prerequisites before starting dependency installation.
2. Clone the repository into the chosen destination. Use `--branch <ref>` only when the user explicitly chooses a branch or tag.
3. Before cloning, decide whether the user selected the current business project. If so, resolve its Git root from the original working directory and save it in a separate variable. Do not use the new Tsunagou checkout as the project root. Run the checked-in installer from the cloned checkout:

   ```powershell
   uv run python tools/install/install.py --source-root $PWD --skill-scope user --host codex --json
   ```

   On a host without `uv`, use the available Python executable:

   ```text
   python tools/install/install.py --source-root <resolved-checkout> --skill-scope user --host <selected-host> --json
   ```

   The script installs the locked Python dependencies, installs the frozen pnpm workspace, builds `packages/bridge-server/dist/server.js`, and copies the two skills to the shared user `.agents/skills` and explicitly selected host only. It generates a user CLI launcher bound to this runtime and registers its actual source. In an already-open terminal use the fully qualified `installation.launcher` returned by the installer. It refuses conflicting skill directories; an authorized skill update may use `--force` after checking these are Tsunagou-managed copies.

4. Validate the result with the returned JSON and these read-only checks:

   ```text
   <runtime> -m tsunagou --version
node --check packages/bridge-server/dist/server.js
```

When the user explicitly asked to install Tsunagou in the current business
project, pass that saved root. The installer initializes the selected Git
project if `.tsunagou/project.json` is absent, then materializes its non-secret
local entries in the same run:

```powershell
uv run python tools/install/install.py --source-root $PWD --skill-scope user `
  --project-root <selected-business-project-root> `
  --host codex --project-name '<project-name>' `
  --project-objective '<project-objective>' --json
```

The explicit `--project-root` path may call `project init` once and then calls
`project bootstrap`; it does not start a daemon, enroll a conversation, appoint
main, publish a task, or write credentials. Without an explicit project root,
installation remains source/skill installation only and hands off to
onboarding. If the selected root is not already a Git repository, stop and
show the user `git init --quiet <path>` rather than creating the repository
silently.

5. Tell the user exactly where the checkout, bridge entry and skills were installed. Do not claim that a daemon or Agent is ready yet.
6. Offer the next step by loading `tsunagou-agent-onboarding`. For a project-root installation, it continues with `daemon start` and one `agent connect` command; the command can carry the user's explicit `--role main` choice and registers the bridge when the host supports it. For a source-only installation, it first guides the user through choosing a business project, `project init` and `project bootstrap`. Installation/bootstrap success alone must never be reported as Agent readiness.

## Existing installation

If the destination is already a Tsunagou Git checkout, do not run `git pull` over dirty user changes. Report the current branch and dirty state, then ask whether to update it. Dependency synchronization and skill installation may proceed only when they do not overwrite user changes; use `--force` for skill files only after the user explicitly requests skill refresh.

## Failure handling

- `destination_not_empty`: ask for a new directory; never remove the existing contents.
- `command_unavailable`: name the missing prerequisite and give the platform-specific installation direction without pretending installation succeeded.
- `skill_destination_conflict`: show the conflicting skill directory and ask whether to use `--force`.
- Dependency or build failure: preserve the checkout and report the failing command; do not retry indefinitely.

End with `installed` or a precise failure state, the next single user action, and a link to the onboarding guide. Installation success is not bridge enrollment and is not proof of host compatibility.
