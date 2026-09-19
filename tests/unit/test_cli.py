from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tsunagou.cli.app import _write_ticket_private


def test_ticket_is_written_to_private_file_not_returned_in_output(tmp_path: Path) -> None:
    # The CLI must deliver the one-time ticket through a 0600 file, never stdout:
    # the returned path is safe to print while the secret stays inside the file.
    path = _write_ticket_private("install-a", "conversation-a", "s3cret-token", tmp_path / "ticket.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["secret"] == "s3cret-token"
    assert raw["installation_id"] == "install-a"
    assert raw["conversation_id"] == "conversation-a"
    # The secret must not be part of what the CLI prints (the file path only).
    assert "s3cret-token" not in str(path)


def test_ticket_file_is_owner_only(tmp_path: Path) -> None:
    path = _write_ticket_private("install-a", "conversation-a", "s3cret-token", tmp_path / "ticket.json")
    if os.name == "nt":
        # chmod is a no-op for Windows ACLs; the fix strips inherited ACEs and
        # grants only CREATOR OWNER. Assert the world-readable ACEs are gone.
        out = subprocess.run(["icacls", str(path)], capture_output=True, text=True).stdout
        assert "Authenticated Users" not in out
        assert r"\Users:" not in out
    else:  # POSIX chmod is meaningful
        assert (path.stat().st_mode & 0o777) == 0o600
