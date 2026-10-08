from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tsunagou.platform.deepseek_wake import (
    bind_deepseek_wake,
    ensure_deepseek_wake_configuration,
    read_deepseek_wake_configuration,
    set_deepseek_wake_mode,
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


def test_a_new_configuration_starts_in_queue_mode():
    ensure_deepseek_wake_configuration()
    assert read_deepseek_wake_configuration()["wake_mode"] == "queue"


def test_mode_switch_persists_without_touching_key_or_bindings():
    ensure_deepseek_wake_configuration()
    bind_deepseek_wake("p", "a", "s")
    before = read_deepseek_wake_configuration()
    set_deepseek_wake_mode("steer")
    after = read_deepseek_wake_configuration()
    assert after["wake_mode"] == "steer"
    assert after["key"] == before["key"]
    assert after["bindings"] == before["bindings"]
    set_deepseek_wake_mode("steer")
    assert read_deepseek_wake_configuration()["wake_mode"] == "steer"
    set_deepseek_wake_mode("queue")
    assert read_deepseek_wake_configuration()["wake_mode"] == "queue"


def test_mode_must_be_one_the_plugin_may_submit():
    ensure_deepseek_wake_configuration()
    with pytest.raises(ValueError, match="^deepseek_wake_mode_invalid$"):
        set_deepseek_wake_mode("interrupt")
    assert read_deepseek_wake_configuration()["wake_mode"] == "queue"


def test_configuration_without_the_mode_field_still_validates():
    """A file written before the field existed keeps working: absent means queue."""
    path = ensure_deepseek_wake_configuration()
    value = read_deepseek_wake_configuration()
    del value["wake_mode"]
    path.write_text(json.dumps(value))
    assert "wake_mode" not in read_deepseek_wake_configuration()


@pytest.mark.parametrize("bad", ["abort", "normal", None, 1])
def test_a_mode_the_plugin_cannot_submit_is_rejected(bad):
    """Python and the plugin must agree: the plugin only reads an absent key as
    the default, so an explicit unusable value is invalid on both sides."""
    path = ensure_deepseek_wake_configuration()
    value = read_deepseek_wake_configuration()
    value["wake_mode"] = bad
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="^deepseek_wake_configuration_invalid$"):
        read_deepseek_wake_configuration()
