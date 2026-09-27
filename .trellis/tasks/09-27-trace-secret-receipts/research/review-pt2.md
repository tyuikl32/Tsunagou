# PT2 reviewer evidence

- recorded_at: 2026-09-27T17:48:11.000Z
- updated_at: 2026-09-27T17:55:40.000Z
- reviewer: `/root/pt2_trace_review` (`trellis-check`)
- platform: Windows; no macOS/Linux execution claimed
- scope: credential receipts, private vault/files, offline migration, bridge handoff

## Findings fixed

1. An old database without a migration marker could restore authority before revocation. Startup now scans credential-bearing database rows and old plaintext escrow through a read-only SQLite connection before creating a writer. A completed marker does not bless subsequently restored legacy data. An assembled `build_application` regression proves the writer is not constructed first.
2. Non-object/partial protected markers and malformed/non-object old credential results could throw unstructured exceptions. Marker validation now fails with `credential_migration_incomplete`; migration replaces malformed historical credential results with revoked safe receipts.
3. A crash after quarantine unlink but before marker update omitted the copied file from the resumed report. Resume reconstructs that inventory from its durable private quarantine. Resolved backup/state paths are checked before mutation.
4. Credential replay/ACK/inventory reads used SQLite context managers that did not close connections. Those temporary read connections and the authority module-state read now use `contextlib.closing`.
5. Atomic rename alone did not protect bridge session read/compare/write across processes. A slower response could pass the old-state check, pause, then overwrite epoch N+1 with epoch N. A process-owned loopback bind mutex now covers synchronous prepare/finalize file sections; HTTP and ACK stay outside. Hash/port collision returns busy, never shared ownership. Process exit releases the mutex without stale PID-file deletion.
6. The late-ticket smoke script resolved its executable against caller cwd and failed from package scripts. It now resolves relative to `import.meta.url`.
7. Windows `icacls /inheritance:r /grant:r SID` retained other explicit ACEs on an existing vault directory. `restrict_access` now constructs a protected SID-only DACL and applies it in one `SetNamedSecurityInfoW` operation. An actual Windows test first grants Everyone access and verifies the final sole allow ACE is the current SID.
8. Bridge ticket read-digest/unlink was not synchronized with Python CLI ticket replacement. Both now use the same canonical-path mutex. Ticket cleanup is deferred until after releasing the session mutex, preventing nested-lock deadlock if two path hashes map to the same port. An actual Python CLI process holds the ticket lock while a Node bridge saves its session; cleanup must return busy, and its retry preserves the subsequently replaced ticket.
9. CLI control-token creation wrote plaintext before setting the old ACL. It now uses the shared ACL-before-write helper; existing control-token files have their DACL restricted before reading. The obsolete alternate ACL helper was removed.

## Verification

- `uv run pytest -q tests/unit/test_trace_secret_receipts.py tests/unit/test_secret_delivery.py tests/unit/test_credential_migration.py tests/unit/test_credential_migration_cli.py tests/unit/test_storage_runtime.py`: 45 cases passed after final Python fixes.
- `uv run ruff check src tests tools`: passed.
- `uv run mypy src`: passed, 59 source files after adding the Python mutex.
- `corepack pnpm run check`: all seven Node workspaces passed.
- `corepack pnpm --filter @tsunagou/bridge-server run test:credentials`: build, 16 handoff/ACL/concurrency cases (including actual Python/Node concurrency), explicit-session late-ticket smoke and implicit-session restart smoke passed.
- `uv run pytest -q tests/unit/test_private_file_lock.py tests/unit/test_cli.py`: six cases passed after CLI mutex/control-token changes.
- `git diff --check`: passed.
- Negative control in an isolated temporary copy: replaced only the bridge mutex with a no-op, ran `paused old session writer cannot overwrite the next epoch from another process`; it failed with persisted epoch `1 !== 2`. The real mutex passes the same subprocess barrier test. Production source/dist were not changed for this control.

## Scope and remaining handoff

The main session additionally guards patch generation against tracked private credential files; this reviewer requested a case-insensitive private-root regression for Windows. Full task-scope, symlink and artifact-reader semantics remain PT3 as planned. The prior producer-side ticket race is fixed and tested (finding 8). No user project or live daemon was modified during this review. Shared full-suite/standalone acceptance is completed by the main session after integrating its concurrent schema/docs/export changes.

## Primary Windows references

- [SetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setnamedsecurityinfow): sets the DACL supplied by the caller; return code and inheritance behavior.
- [GetSecurityDescriptorDacl](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-getsecuritydescriptordacl): validate both DACL presence and a non-null pointer before setting it.
- [ConvertStringSecurityDescriptorToSecurityDescriptorW](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsecuritydescriptortosecuritydescriptorw): SDDL revision 1 and `LocalFree` ownership of the allocated descriptor.
