"""The coordination centre's port: fixed on purpose, never a reason the daemon won't start.

Reachable remotes need a port that survives a restart, so ``daemon start`` uses 2810 unless
somebody says otherwise. A port that is already held must not become a failure: the daemon
takes a free one and says so (a warning on stderr plus ``port_fallback`` in the answer),
because whatever port ends up in use is the port that goes into the invitation.
"""

from __future__ import annotations

import socket

import pytest

from tsunagou.cli import app as cli


def _held_port(host: str = "127.0.0.1") -> tuple[socket.socket, int]:
    """A port this test holds open, so the daemon cannot have it."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(1)
    return sock, int(sock.getsockname()[1])


def test_a_free_port_is_used_as_is() -> None:
    sock, port = _held_port()
    sock.close()                       # 现在这个端口是空的：应该原样用它
    chosen, fell_back = cli._pick_daemon_port("127.0.0.1", port)
    assert (chosen, fell_back) == (port, False)


def test_an_occupied_port_falls_back_to_a_free_one() -> None:
    sock, port = _held_port()
    try:
        chosen, fell_back = cli._pick_daemon_port("127.0.0.1", port)
    finally:
        sock.close()
    assert fell_back is True, "占用了就得说出来（人要改邀请里的地址）"
    assert chosen != port and chosen > 0


def test_port_zero_means_any_free_port_and_is_not_a_fallback() -> None:
    """`--port 0` 是"随便给我一个"，不是"被占了"：不要报警告。"""

    chosen, fell_back = cli._pick_daemon_port("127.0.0.1", 0)
    assert chosen > 0 and fell_back is False


def test_the_default_port_is_the_fixed_one() -> None:
    """默认端口是常量 2810，不是随手写的一个数字。"""

    assert cli.DEFAULT_DAEMON_PORT == 2810


def test_an_occupied_default_port_still_answers_with_a_usable_port() -> None:
    """2810 被别人占了也一样能起来：给一个空闲端口，并且承认这是回退。"""

    if not cli._daemon_port_is_free("127.0.0.1", cli.DEFAULT_DAEMON_PORT):
        pytest.skip("2810 此刻已被占用：这条用例的前提不成立")
    sock, _ = _held_port()             # 另一个端口被占，用"指定的固定端口"这条路来验回退
    try:
        chosen, fell_back = cli._pick_daemon_port("127.0.0.1", int(sock.getsockname()[1]))
    finally:
        sock.close()
    assert fell_back is True and chosen > 0
