"""控制台监听在哪里：默认端口固定、被占用就换一个、而且只允许回环。

三条规矩互相配合，缺一条都不成立：

* **默认端口固定**（2812）：固定是为了让人能**收藏**页面 —— 地址会变就谈不上收藏。
* **被占用就换一个空闲端口**：端口是稀缺资源，为了"占住那一个"而拒绝启动更没用；换了一定要说，
  否则人收藏的是个过期地址。
* **只允许回环**：控制台自己没有任何认证，它拿着各项目的控制令牌替页面转发用户级命令
  （删项目、任命主 Agent 都经过它）。监听在回环之外，等于把"操作这台机器上所有项目"的权力交给网络。
  固定端口是给人方便的，不是给公网方便的。

人**明确写下来**的端口（``--port``，或配置文件里的 ``port``）被占用时**不换**：隧道与防火墙规则
是对着它配的，静默换一个会看起来"启动成功"，而实际上谁也访问不到。
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from tsunagou.console.config import DEFAULT_PORT, ConsoleConfig, is_loopback_host
from tsunagou.console.service import choose_port, serve


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _occupied(port: int) -> socket.socket:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", port))
    holder.listen(1)
    return holder


def test_the_default_port_is_the_one_people_bookmark() -> None:
    config = ConsoleConfig()

    assert DEFAULT_PORT == 2812
    assert config.port == DEFAULT_PORT
    assert config.port_explicit is False, "没写下来的端口才允许回退"


def test_a_free_port_is_listened_on_as_asked() -> None:
    """端口空着的时候不要"顺手换个新的"：换了收藏就废了。"""

    port = _free_port()

    assert choose_port("127.0.0.1", port, fallback=True) == (port, False)


def test_an_occupied_default_port_moves_to_a_free_one() -> None:
    taken = _free_port()
    holder = _occupied(taken)
    try:
        port, moved = choose_port("127.0.0.1", taken, fallback=True)
    finally:
        holder.close()

    assert moved is True, "换过端口就必须如实报告"
    assert port != taken
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))  # 换到的端口真的能用


def test_a_port_somebody_wrote_down_never_moves() -> None:
    """显式写的端口被占用时照实失败：隧道/防火墙是对着它配的。"""

    taken = _free_port()
    holder = _occupied(taken)
    try:
        assert choose_port("127.0.0.1", taken, fallback=False) == (taken, False)
    finally:
        holder.close()


def test_a_zero_port_still_asks_the_system_for_one() -> None:
    port, moved = choose_port("127.0.0.1", 0, fallback=True)

    assert port > 0
    assert moved is False, "本来就没要求某个端口，谈不上「换过」"


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.5.9", "localhost", "::1"])
def test_loopback_hosts_are_accepted(host: str) -> None:
    assert is_loopback_host(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "192.168.1.5", "10.0.0.7", "console.example.com"])
def test_only_loopback_may_host_the_console(host: str) -> None:
    assert is_loopback_host(host) is False

    with pytest.raises(RuntimeError, match="console_host_must_be_loopback"):
        serve(ConsoleConfig(host=host, port=DEFAULT_PORT))


def test_a_port_in_the_config_file_counts_as_written_down(tmp_path: Path) -> None:
    """配置文件里的 port 也是人手写的，同样不回退。"""

    written = tmp_path / "written.json"
    written.write_text('{"port": 2812}', encoding="utf-8")
    silent = tmp_path / "silent.json"
    silent.write_text('{"host": "127.0.0.1"}', encoding="utf-8")

    assert ConsoleConfig.load(written).port_explicit is True
    assert ConsoleConfig.load(silent).port == DEFAULT_PORT
    assert ConsoleConfig.load(silent).port_explicit is False
