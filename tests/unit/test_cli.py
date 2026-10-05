from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tsunagou.cli.app import (
    _probe_url,
    _profile_identity,
    _resolve_codex_executable,
    _write_ticket_private,
)
from tsunagou.platform.bridge_files import write_bridge_config


@pytest.mark.parametrize(
    ("given", "probed"),
    [
        # 通配绑定：能 bind，但那个地址连不上 —— 探测换成回环，端口与路径都保留。
        ("http://0.0.0.0:2810", "http://127.0.0.1:2810"),
        ("http://0.0.0.0:2810/api/v1/health?x=1", "http://127.0.0.1:2810/api/v1/health?x=1"),
        ("http://[::]:2810", "http://[::1]:2810"),
        # 具体地址原样：探测与对外地址在这件事上不该分叉。
        ("http://127.0.0.1:2810", "http://127.0.0.1:2810"),
        ("http://192.168.32.1:2810", "http://192.168.32.1:2810"),
        ("http://localhost:2810", "http://localhost:2810"),
    ],
)
def test_readiness_probe_uses_a_connectable_address(given: str, probed: str) -> None:
    """`daemon start --host 0.0.0.0` 曾经必然超时：CLI 拿不可连接的 0.0.0.0 去探测，
    于是把一个已经健康的 daemon 判成启动失败并反手杀掉（2026-10-04 实测）。"""

    assert _probe_url(given) == probed


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

def test_the_machine_field_must_be_a_name_not_an_address() -> None:
    """2026-10-05 实测：把 daemon 地址填进 --machine，主机界面就认不出"在哪台机器"。"""

    from tsunagou.cli.app import _require_machine_name

    assert _require_machine_name("VM-OPENCODE-01") is None
    assert _require_machine_name("desktop-k03dv8n") is None
    assert _require_machine_name("") is None
    assert _require_machine_name("测试机") is None  # 名字可以是中文，只是不能是地址
    for bad in ("http://192.168.32.1:2810", "192.168.32.1:2810", "https://box.example.com", "0.0.0.0:2810"):
        try:
            _require_machine_name(bad)
        except RuntimeError:
            continue
        raise AssertionError(f"这一格本该被拒绝：{bad}")

def test_the_remote_conversation_id_is_ascii_and_random() -> None:
    """昵称可以中文，会话 id 不可以 —— 它会进宿主的 HTTP 头（2026-10-05 实测）。"""

    import re

    from tsunagou.cli.app import _remote_conversation_id

    assert _remote_conversation_id("ses_OpenCode-Net", adapter="opencode") == "ses_OpenCode-Net"
    for bad in ("ses_OpenCode-网络", "会话", "ses_名字"):
        try:
            _remote_conversation_id(bad, adapter="opencode")
        except RuntimeError as exc:
            assert "ascii" in str(exc)
            continue
        raise AssertionError(f"这个会话 id 本该被拒绝：{bad}")
    first = _remote_conversation_id("", adapter="opencode")
    second = _remote_conversation_id("", adapter="opencode")
    assert re.fullmatch(r"ses_[0-9a-f]{8}", first), first
    assert first != second
    try:
        _remote_conversation_id("", adapter="codex")
    except RuntimeError as exc:
        assert "required" in str(exc)
    else:
        raise AssertionError("codex 没给会话 id 本该被拒绝")
