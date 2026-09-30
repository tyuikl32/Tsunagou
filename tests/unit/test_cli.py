from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tsunagou.cli.app import (
    _profile_identity,
    _resolve_codex_executable,
    _write_ticket_private,
)
from tsunagou.platform.bridge_files import write_bridge_config


@pytest.mark.parametrize("adapter", ["opencode", "codex"])
def test_bridge_config_declares_per_call_host_metadata(tmp_path: Path, adapter: str) -> None:
    # OpenCode delivers its conversation id per tool call; the declaration is
    # what makes the bridge reject calls without valid metadata. CLI connect,
    # CLI enroll and Console enrollment all use this shared config writer.
    path = write_bridge_config(
        adapter=adapter, mode="attach", installation_id=f"{adapter}:worker", output_dir=tmp_path,
        ticket_path=tmp_path / "ticket.json", daemon_url="http://127.0.0.1:9",
        daemon_state_dir="", project_root=tmp_path,
    )
    config = json.loads(path.read_text(encoding="utf-8"))
    environment = config["env"]
    assert environment["TSUNAGOU_TICKET_FILE"] == str(tmp_path / "ticket.json")
    assert environment["TSUNAGOU_SESSION_FILE"] == str(tmp_path / "bridge-session.json")
    assert config["secret_fields"] == []
    if adapter == "opencode":
        assert environment["TSUNAGOU_HOST_META_KEY"] == "ai.opencode/sessionID"
    else:
        assert "TSUNAGOU_HOST_META_KEY" not in environment


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
        # grants only the current user SID. Assert the world-readable ACEs are gone.
        out = subprocess.run(["icacls", str(path)], capture_output=True, text=True).stdout
        assert "Authenticated Users" not in out
        assert r"\Users:" not in out
    else:  # POSIX chmod is meaningful
        assert (path.stat().st_mode & 0o777) == 0o600


def test_profile_identity_uses_the_conversation_not_the_display_profile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TSUNAGOU_INSTALLATION_ID", raising=False)
    monkeypatch.setenv("TSUNAGOU_HOST_CONVERSATION_ID", "host-thread-one")
    main_dir = tmp_path / "main"
    worker_dir = tmp_path / "worker"
    main_first = _profile_identity(main_dir, "codex", "main")
    main_second = _profile_identity(main_dir, "codex", "main")
    monkeypatch.setenv("TSUNAGOU_HOST_CONVERSATION_ID", "host-thread-two")
    worker = _profile_identity(worker_dir, "codex", "worker")
    assert main_first == main_second
    assert main_first[1] != worker[1]
    assert main_first[0] == worker[0]


def test_codex_executable_prefers_host_path(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "codex.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("CODEX_CLI_PATH", str(executable))
    # 探测逻辑现在住在 `tsunagou.platform.host_registration`（一个厂商一行），
    # CLI 只是它的一个调用者，所以 path 也打在那里。
    monkeypatch.setattr("tsunagou.platform.host_registration.shutil.which", lambda _: None)
    assert _resolve_codex_executable() == str(executable)


def test_codex_executable_discovers_desktop_install(monkeypatch, tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Codex Desktop fallback is Windows-specific")
    executable = tmp_path / "OpenAI" / "Codex" / "bin" / "versioned" / "codex.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setattr("tsunagou.platform.host_registration.shutil.which", lambda _: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert _resolve_codex_executable() == str(executable)
