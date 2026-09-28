"""Explicit offline credential revocation and visible-copy cleanup.

The private backup is forensic recovery material, never a runnable rollback.
An incomplete marker fences daemon startup until the approved migration resumes.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from tsunagou.platform.db.sqlite import SCHEMA, ProjectDatabase, ProjectLock, UnitOfWork
from tsunagou.platform.private_files import protect_bytes, restrict_access, unprotect_bytes, write_private_bytes
from tsunagou.shared_kernel.digests import canonical_bytes, canonical_digest
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import format_timestamp, now_ms

_SECRET_FIELDS = {"secret", "secret_token", "reconnect_nonce", "token", "password", "authorization",
                  "api_key", "credential", "access_token", "refresh_token"}
_MARKER = "credential-migration.json"
_CREDENTIAL_COMMANDS = {
    "agent.ticket.create.user", "agent.ticket.create", "agent.enroll", "session.rebind", "session.reconnect",
}


def assert_credential_migration_ready(state_dir: Path) -> None:
    marker = state_dir / _MARKER
    if marker.exists():
        if _load_marker(marker)["status"] != "completed":
            raise RuntimeError("credential_migration_incomplete")
    if _legacy_credentials_present(state_dir):
        raise RuntimeError("credential_migration_required")


def _load_marker(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(unprotect_bytes(path.read_bytes()))
    except (OSError, ValueError, RuntimeError, UnicodeDecodeError) as exc:
        raise RuntimeError("credential_migration_incomplete") from exc
    required = ("plan_digest", "database_digest", "operation_id", "backup_relative_path", "started_at")
    if (not isinstance(value, dict) or value.get("status") not in {"in_progress", "completed"}
            or any(not isinstance(value.get(key), str) or not value[key] for key in required)):
        raise RuntimeError("credential_migration_incomplete")
    return value


def _legacy_credentials_present(state_dir: Path) -> bool:
    """Inspect before opening a writer or restoring authority, including restored backups."""
    escrow = state_dir / "state.sqlite3.deliveries"
    if escrow.exists() and any(escrow.glob("*.json")):
        return True
    path = state_dir / "state.sqlite3"
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("migration_database_missing_or_symlink")
    with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        counts, _ = _inventory(conn)
        return bool(counts)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
    )]


def _database_digest(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for table in _tables(conn):
        digest.update(table.encode())
        for row in conn.execute(f"SELECT * FROM {_quote(table)} ORDER BY rowid"):
            digest.update(json.dumps(tuple(row), ensure_ascii=False, default=str, separators=(",", ":")).encode())
    return "sha256:" + digest.hexdigest()


def _collect_secrets(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in _SECRET_FIELDS and isinstance(item, str) and len(item) >= 8 and item != "[REDACTED]":
                found.add(item)
            _collect_secrets(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_secrets(item, found)


def _inventory(conn: sqlite3.Connection) -> tuple[dict[str, int], set[str]]:
    found: set[str] = set()
    counts: dict[str, int] = {}
    for table in _tables(conn):
        conn.row_factory = sqlite3.Row
        for row in conn.execute(f"SELECT * FROM {_quote(table)}"):
            row_secrets: set[str] = set()
            corrupt_credential = False
            for key in row.keys():
                value = row[key]
                if key.endswith("_json") and isinstance(value, str):
                    try:
                        _collect_secrets(json.loads(value), row_secrets)
                    except ValueError:
                        # A corrupt credential result cannot be replayed or
                        # trusted safe. Migration replaces it with a receipt.
                        if table == "commands" and row["command_kind"] in _CREDENTIAL_COMMANDS:
                            corrupt_credential = True
            if table == "commands" and row["command_kind"] in _CREDENTIAL_COMMANDS:
                try:
                    if not isinstance(json.loads(row["result_json"]), dict):
                        corrupt_credential = True
                except (ValueError, TypeError):
                    corrupt_credential = True
            if table == "commands" and row["command_kind"] in {"agent.enroll", "session.rebind"}:
                principal = str(row["principal_id"])
                if not principal.startswith(("ticket/", "ticket:", "sha256:", "ticket_hash/", "ticket-sha256:")):
                    row_secrets.add(principal)
            if row_secrets or corrupt_credential:
                counts[table] = counts.get(table, 0) + 1
            found.update(row_secrets)
    return counts, found


def _clean(value: Any, known: set[str]) -> Any:
    if isinstance(value, str):
        for secret in sorted(known, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {("redacted_hash/" + hashlib.sha256(str(key).encode()).hexdigest() if str(key) in known else _clean(str(key), known)):
                "[REDACTED]" if str(key).casefold() in _SECRET_FIELDS else _clean(item, known)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item, known) for item in value]
    return value


class CredentialMigration:
    def __init__(self, coordination_root: Path) -> None:
        self.root = coordination_root.resolve()
        self.project_dir = self.root / ".tsunagou"
        self.state_dir = self.project_dir / "local"
        self.path = self.state_dir / "state.sqlite3"
        self.marker = self.state_dir / _MARKER
        if not self.state_dir.resolve().is_relative_to(self.root):
            raise ValueError("migration_path_outside_project")
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError("migration_database_missing_or_symlink")

    def _readonly(self, path: Path) -> sqlite3.Connection:
        return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)

    def _unsafe_files(self, known: set[str]) -> list[Path]:
        found = []
        for path in self.project_dir.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.project_dir)
            if relative.parts[:2] == ("local", "credential-migrations"):
                continue
            if path.parent == self.state_dir and (path.name.startswith("state.sqlite3") or path == self.marker):
                continue
            if not path.resolve().is_relative_to(self.project_dir.resolve()):
                raise ValueError("migration_path_outside_project")
            # All old escrow entries are revoked; quarantine even encrypted
            # files, whose contents deliberately cannot be scanned as plaintext.
            if "state.sqlite3.deliveries" in relative.parts:
                found.append(path)
            else:
                content = path.read_bytes()
                file_secrets: set[str] = set()
                if path.suffix == ".json":
                    try:
                        _collect_secrets(json.loads(content), file_secrets)
                    except (ValueError, UnicodeError):
                        pass
                if file_secrets or any(secret.encode() in content for secret in known):
                    found.append(path)
        return sorted(found)

    def preview(self) -> dict[str, Any]:
        with contextlib.closing(self._readonly(self.path)) as source, contextlib.closing(sqlite3.connect(":memory:")) as snapshot:
            source.backup(snapshot)
            if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("migration_integrity_failed")
            counts, known = _inventory(snapshot)
            database_digest = _database_digest(snapshot)
        files = self._unsafe_files(known)
        manifest = {str(path.relative_to(self.project_dir)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        body = {"database_digest": database_digest, "files": manifest}
        return {
            "status": "preview", "plan_digest": canonical_digest(body), "database_digest": database_digest,
            "recorded_at": format_timestamp(now_ms()), "sensitive_rows_by_table": counts,
            "quarantine_files": _clean(list(manifest), known),
            "revoke_all_existing_sessions_and_tickets": True,
            "main_authority_after_migration": "unassigned",
            "backup_contains_revoked_historical_secrets": True,
        }

    def apply(self, plan_digest: str) -> dict[str, Any]:
        # Do not stop a live daemon as a side effect of confirmation.
        with ProjectLock(self.path.with_suffix(".sqlite3.runtime.lock"), timeout=0), \
                ProjectLock(self.path.with_suffix(".sqlite3.lock"), timeout=0):
            previous = self._read_marker() if self.marker.exists() else None
            if previous and previous.get("status") == "completed" and _legacy_credentials_present(self.state_dir):
                # A prior completion marker cannot bless a restored old DB.
                # Re-run the confirmed plan as a fresh revocation operation.
                previous = None
            if previous and previous.get("plan_digest") == plan_digest:
                if previous.get("status") == "completed":
                    return dict(previous)
                marker = previous
            else:
                if previous and previous.get("status") != "completed":
                    raise ValueError("migration_resume_original_plan_required")
                preview = self.preview()
                if not secrets.compare_digest(preview["plan_digest"], plan_digest):
                    raise ValueError("migration_plan_changed")
                operation_id = new_id()
                backup_dir = self.state_dir / "credential-migrations" / operation_id
                if not backup_dir.resolve().is_relative_to(self.state_dir.resolve()):
                    raise ValueError("migration_backup_path_invalid")
                backup_dir.mkdir(parents=True)
                restrict_access(backup_dir, directory=True)
                backup = backup_dir / "before.sqlite3"
                write_private_bytes(backup, b"")
                with contextlib.closing(self._readonly(self.path)) as source, contextlib.closing(sqlite3.connect(backup)) as target:
                    source.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("migration_backup_integrity_failed")
                backup.chmod(0o400)
                marker = {**preview, "status": "in_progress", "operation_id": operation_id,
                          "started_at": format_timestamp(now_ms()), "backup_relative_path": str(backup.relative_to(self.state_dir))}
                self._save_marker(marker)
            backup = (self.state_dir / marker["backup_relative_path"]).resolve()
            backup_root = (self.state_dir / "credential-migrations").resolve()
            if not backup_root.is_relative_to(self.state_dir.resolve()) or not backup.is_relative_to(backup_root):
                raise ValueError("migration_backup_path_invalid")
            with contextlib.closing(self._readonly(backup)) as source:
                if _database_digest(source) != marker["database_digest"]:
                    raise RuntimeError("migration_backup_changed")
                _, known = _inventory(source)
            self._revoke_and_scrub(str(marker["operation_id"]), known)
            quarantined = list(marker.get("quarantined_files", []))
            # Recover the copy/unlink/marker crash window from the durable
            # quarantine itself rather than omitting its files from the report.
            quarantine_root = backup.parent / "quarantine"
            if quarantine_root.exists():
                quarantined.extend(str(path.relative_to(quarantine_root)) for path in quarantine_root.rglob("*") if path.is_file())
            for source_path in self._unsafe_files(known):
                target_path = backup.parent / "quarantine" / source_path.relative_to(self.project_dir)
                if not target_path.resolve().is_relative_to(backup.parent.resolve()):
                    raise ValueError("migration_quarantine_path_invalid")
                # Copy to an ACL-protected private file before deleting only
                # this explicitly inventoried original. A crash is resumable.
                write_private_bytes(target_path, source_path.read_bytes())
                source_path.unlink()
                quarantined.append(str(source_path.relative_to(self.project_dir)))
                marker["quarantined_files"] = sorted(set(_clean(quarantined, known)))
                self._save_marker(marker)
            with contextlib.closing(sqlite3.connect(self.path, isolation_level=None)) as conn:
                if conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
                    raise RuntimeError("migration_wal_busy")
                conn.execute("VACUUM")
                if conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
                    raise RuntimeError("migration_wal_busy")
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("migration_integrity_failed")
            for file in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")):
                if file.exists() and any(secret.encode() in file.read_bytes() for secret in known):
                    raise RuntimeError("migration_visible_secret_remaining")
            marker.update(status="completed", completed_at=format_timestamp(now_ms()), integrity_check="ok",
                          quarantined_files=sorted(set(_clean(quarantined, known))), recovery_action="enroll_and_appoint_again")
            self._save_marker(marker)
            return dict(marker)

    def _save_marker(self, marker: dict[str, Any]) -> None:
        write_private_bytes(self.marker, protect_bytes(canonical_bytes(marker)))

    def _read_marker(self) -> dict[str, Any]:
        return _load_marker(self.marker)

    def _revoke_and_scrub(self, operation_id: str, known: set[str]) -> None:
        with contextlib.closing(sqlite3.connect(self.path, isolation_level=None)) as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(SCHEMA)
            ProjectDatabase._ensure_schema_columns(conn)
            event_columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
            for name, kind in (("original_digest", "TEXT"), ("redacted_at", "INTEGER")):
                if name not in event_columns:
                    conn.execute(f"ALTER TABLE events ADD COLUMN {name} {kind}")
            if conn.execute("SELECT 1 FROM events WHERE command_id=? AND event_type='credential.migrate'", (operation_id,)).fetchone():
                return
            conn.execute("PRAGMA secure_delete=ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                project_ids = [row[0] for row in conn.execute("SELECT project_id FROM runtime_fences")]
                if len(project_ids) != 1:
                    raise ValueError("migration_single_project_required")
                project_id = str(project_ids[0])
                row = conn.execute(
                    "SELECT payload_json FROM module_state WHERE project_id=? AND module='authority'", (project_id,),
                ).fetchone()
                if row:
                    authority = json.loads(row[0])
                    for session in authority.get("sessions", {}).values():
                        session.update(active=False, status="ended", credential_hash=secrets.token_hex(32),
                                       reconnect_nonce_hash=secrets.token_hex(32), connection_epoch=session.get("connection_epoch", 0) + 1)
                    for ticket in authority.get("tickets", {}).values():
                        ticket.update(used=True, expires_at=0, requested_role="worker")
                    for grant in authority.get("grants", {}).values():
                        grant["status"] = "revoked"
                    for agent in authority.get("agents", {}).values():
                        agent.update(role="worker", requested_role="worker")
                    authority.update(main_agent_id=None, authority_epoch=authority.get("authority_epoch", 0) + 1)
                    conn.execute("UPDATE module_state SET payload_json=?,revision=revision+1,updated_at=? "
                                 "WHERE project_id=? AND module='authority'", (json.dumps(authority), now_ms(), project_id))
                conn.execute("UPDATE runtime_fences SET runtime_epoch=? WHERE project_id=?", (new_id(), project_id))
                for table in _tables(conn):
                    for row in conn.execute(f"SELECT rowid AS _migration_rowid,* FROM {_quote(table)}").fetchall():
                        updates: dict[str, Any] = {}
                        for field in row.keys():
                            value = row[field]
                            if not isinstance(value, str):
                                continue
                            if field.endswith("_json"):
                                try:
                                    decoded = json.loads(value)
                                    cleaned = _clean(decoded, known)
                                    changed = (
                                        json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
                                        if cleaned != decoded else value
                                    )
                                except ValueError:
                                    changed = _clean(value, known)
                            else:
                                changed = _clean(value, known)
                            if changed != value:
                                updates[field] = changed
                        if (table == "commands" and row["command_kind"] in {"agent.enroll", "session.rebind"}
                                and row["principal_id"] in known):
                            updates["principal_id"] = "ticket-sha256:" + hashlib.sha256(str(row["principal_id"]).encode()).hexdigest()
                        if table == "commands" and row["command_kind"] in _CREDENTIAL_COMMANDS:
                            try:
                                result = json.loads(updates.get("result_json", row["result_json"]))
                            except (ValueError, TypeError):
                                result = {}
                            if not isinstance(result, dict):
                                result = {}
                            safe_fields = {"agent_id", "session_id", "connection_epoch", "baseline_status", "ticket_id", "ticket_ref"}
                            result = {key: value for key, value in result.items() if key in safe_fields}
                            result.update(delivery_status="revoked", recovery_action="reconnect_required", migration_id=operation_id)
                            updates["result_json"] = json.dumps(result)
                        if table == "events" and "payload_json" in updates:
                            updates["original_digest"] = row["original_digest"] or row["digest"]
                            updates["digest"] = canonical_digest(json.loads(updates["payload_json"]))
                            updates["redacted_at"] = now_ms()
                        if updates:
                            assignments = ",".join(f"{_quote(field)}=?" for field in updates)
                            conn.execute(f"UPDATE {_quote(table)} SET {assignments} WHERE rowid=?",
                                         (*updates.values(), row["_migration_rowid"]))
                conn.execute("UPDATE commands SET auth_proof_hash=NULL,delivery_ref=NULL WHERE project_id=?", (project_id,))
                lineage = conn.execute("SELECT value FROM runtime_meta WHERE key=?", (f"lineage:{project_id}",)).fetchone()
                uow = UnitOfWork(conn, project_id, operation_id)
                uow.append_event(lineage_id=str(lineage[0]) if lineage else "unknown", event_type="credential.migrate",
                                 aggregate_ref=f"project/{project_id}", actor_ref="user_control", reason_code="legacy_credentials_revoked",
                                 payload={"evidence_level": "system_verified", "migration_id": operation_id,
                                          "sessions_revoked": True, "main_authority": "unassigned"})
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
