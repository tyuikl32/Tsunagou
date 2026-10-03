"""Saying where others should reach me: not the same question as where I listen.

``--host`` answers "which interfaces am I on"; ``--advertised-url`` answers "what address do
remotes dial". Binding ``0.0.0.0`` is the case that makes the difference obvious — it is not
an address anybody can dial — and an invitation built from the bind address sends remotes to
a dead end. So the declaration is checked here, and anything wrong with it is said out loud
rather than left for the remote to discover.
"""

from __future__ import annotations

import json

import pytest

from tsunagou.cli import app as cli


def _warnings(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    captured = capsys.readouterr()
    return [json.loads(line) for line in captured.err.splitlines() if line.strip()]


def test_without_a_declaration_nothing_is_advertised() -> None:
    assert cli._advertised_url("", "127.0.0.1") == ""


def test_a_declared_origin_is_normalised() -> None:
    assert cli._advertised_url("http://192.168.1.10:2810/", "0.0.0.0") == "http://192.168.1.10:2810"
    assert cli._advertised_url("http://nas.local:2810", "0.0.0.0") == "http://nas.local:2810"
    # 少写协议的写法很常见：补 http:// 而不是让人为了一个冒号重敲一遍。
    assert cli._advertised_url("192.168.1.10:2810", "0.0.0.0") == "http://192.168.1.10:2810"
    assert cli._advertised_url("nas.local", "0.0.0.0") == "http://nas.local"


@pytest.mark.parametrize("declared", ["0.0.0.0:2810", "http://0.0.0.0:2810", "http://[::]:2810"])
def test_a_wildcard_is_refused_as_an_advertised_address(declared: str) -> None:
    """绑 0.0.0.0 是"在所有网卡上听"，不是"我在这里"。"""

    with pytest.raises(RuntimeError, match="^advertised_url_must_not_be_a_wildcard$"):
        cli._advertised_url(declared, "0.0.0.0")


def test_something_that_is_not_an_origin_is_refused() -> None:
    for declared in ("ftp://192.168.1.10", "http://192.168.1.10:2810/path", "http://192.168.1.10:notaport"):
        with pytest.raises(RuntimeError, match="^advertised_url_must_be_an_origin$"):
            cli._advertised_url(declared, "0.0.0.0")


def test_advertising_loopback_is_allowed_but_said_out_loud(capsys: pytest.CaptureFixture[str]) -> None:
    """本机自测可以这么写，但要明确"只有这台机器能连"。"""

    assert cli._advertised_url("http://127.0.0.1:2810", "0.0.0.0") == "http://127.0.0.1:2810"
    assert [item["error"] for item in _warnings(capsys)] == ["advertised_url_is_loopback"]


def test_advertising_a_lan_address_while_listening_on_loopback_warns(capsys: pytest.CaptureFixture[str]) -> None:
    """最常见的口误：地址写成局域网，监听却还在回环 —— 远端连不上。"""

    assert cli._advertised_url("http://192.168.1.10:2810", "127.0.0.1") == "http://192.168.1.10:2810"
    warnings = _warnings(capsys)
    assert [item["error"] for item in warnings] == ["daemon_bind_is_loopback"]
    assert "--host" in warnings[0]["note"]
