from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tsunagou.platform.deepseek_wake import (
    bind_deepseek_wake,
    ensure_deepseek_wake_configuration,
    read_deepseek_wake_configuration,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


def test_configuration_preserves_key_and_bindings_on_prepare():
    path = ensure_deepseek_wake_configuration()
    original = read_deepseek_wake_configuration()
    assert len(original["key"]) >= 64
    bind_deepseek_wake("p", "a", "s")
    before = path.read_bytes()
    ensure_deepseek_wake_configuration()
    assert path.read_bytes() == before
    assert read_deepseek_wake_configuration()["key"] == original["key"]


def test_bind_replaces_stale_target_and_preserves_other_projects():
    bind_deepseek_wake("p", "a", "old")
    bind_deepseek_wake("other", "b", "other-session")
    bind_deepseek_wake("p", "a", "new")
    bind_deepseek_wake("new-project", "new-agent", "new")
    assert read_deepseek_wake_configuration()["bindings"] == [
        {"project_id": "other", "agent_id": "b", "session_id": "other-session"},
        {"project_id": "new-project", "agent_id": "new-agent", "session_id": "new"},
    ]


def test_concurrent_bindings_do_not_lose_updates():
    ensure_deepseek_wake_configuration()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: bind_deepseek_wake("p", f"a{n}", f"s{n}"), range(8)))
    assert len(read_deepseek_wake_configuration()["bindings"]) == 8


def test_invalid_configuration_is_not_reset():
    path = ensure_deepseek_wake_configuration()
    path.write_text('{"key":"private-invalid"}')
    with pytest.raises(RuntimeError, match="^deepseek_wake_configuration_invalid$"):
        ensure_deepseek_wake_configuration()
    assert path.read_text() == '{"key":"private-invalid"}'
