# PT4 Trellis review

reviewed_at: 2026-09-28T00:32:48Z

Reviewer: `tyuikl32` (main implementation session), Windows checkout `D:\Tsunagou`, branch `codex/persistence-traceability`. No real user project was opened or modified; no commit/push was performed.

## Findings resolved

- Checkpoint materialization is staged after the SQLite commit. The committed job payload contains the exact public snapshot, actor, reason, watermark, parent digest and artifact inputs. A retry validates the stored `input_digest` and reuses the same payload.
- The shared export is allow-listed by module. Runtime authority, credentials, host/session identifiers, private messages, leases, job claims and local absolute paths are excluded. Embedded path strings and bearer/secret sentinels in public prose are redacted.
- Promoted project-shared artifacts are exported with public references and verified blob metadata. The worker follows only the canonical local CAS path, checks size and SHA-256, and refuses missing, duplicate, symlinked or tampered inputs. Recipient-only artifacts remain absent.
- Git anchors inspect local heads/tags and the actual reachable tree, including manifest and artifact bytes. Remote refs, reflogs and digest substrings do not authorize recovery. The checkpoint directory uses a compact key for Windows path-length headroom and retains legacy full-key read compatibility.
- Clone preview is read-only. Confirm rechecks the plan digest and anchor, constructs SQLite plus artifact bytes in one temporary local directory, validates SQLite integrity, then publishes the directory. Authority is unassigned, roots are unbound, prior sessions/tickets/grants/leases/job claims are not restored, and unfinished work requires recovery review.

## Remaining scope boundaries

The checkpoint worker does not make business decisions, assign an Agent, or resolve unfinished tasks. Those actions remain in the existing main/user command boundary and are covered by PT5+ query/operation work. Git is an evidence anchor, not an automatic commit/push mechanism. Recovery is intentionally restricted to a clean clone; existing initialized local state follows the separate lineage-reset design.

## Verification

- `uv run pytest -q --disable-warnings`: passed; 3 platform-conditional tests skipped.
- `uv run pytest -q tests/integration/test_clone_recovery.py tests/unit/test_checkpoint_materialization.py tests/unit/test_checkpoints.py`: 23 passed.
- `uv run ruff check src tests tools`: passed.
- `uv run mypy src`: passed for 63 source files.
- `uv run python tools/docs/validate_docs.py`: passed.
- `git diff --check`: no content errors; only Git line-ending advisory warnings.
