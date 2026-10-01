"""Console configuration: the one file a person edits.

Every path is written in the file, expanded against the current user, and used
without further guessing, so "where does the console look?" has exactly one
answer per deployment.
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

CONFIG_FILENAME = ".tsunagou-console.json"
_ENVIRONMENT_OVERRIDE = "TSUNAGOU_CONSOLE_CONFIG"

# 默认端口：固定下来是为了让人能把页面**收藏**（好记、四位、不与常见服务冲突）。
# 被占用时会另取一个空闲端口并在启动时说明——端口是稀缺资源，为了"占住一个"而拒绝启动
# 更没用（见 console/service.choose_port）。
DEFAULT_PORT = 2812


def is_loopback_host(host: str) -> bool:
    """只有回环地址可以托管控制台。

    控制台自己没有任何认证：它拿着各项目的控制令牌替页面转发用户级命令（删项目、任命主
    Agent 都经过它）。能访问它的人就能操作这台机器上的所有项目，所以监听在回环之外的
    地址，等于把这份权力交给网络。要从别的机器看页面就走隧道（SSH 端口转发等），
    那仍然只在本机开 socket。
    """

    text = (host or "").strip().lower()
    if text == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _expanded_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def default_config_path() -> Path:
    """Where a config file is looked for when nothing is passed in."""

    override = os.environ.get(_ENVIRONMENT_OVERRIDE)
    if override:
        return _expanded_path(override)
    local = Path.cwd() / CONFIG_FILENAME
    if local.is_file():
        return local
    return Path.home() / ".tsunagou" / "console.json"


@dataclass
class ConsoleConfig:
    """Console settings with the defaults the intermediate-version plan fixed."""
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    # 不是配置项：只表示"端口是人明确写下的"（``--port``，或配置文件里的 ``port``）。
    # 明确写下的端口被占用时**不**回退——否则隧道/防火墙对不上，而人看到的是"启动成功"。
    port_explicit: bool = field(default=False, compare=False)
    projects_root: Path = field(default_factory=lambda: Path.home() / "Tsunagou" / "projects")
    scan_roots: list[Path] = field(default_factory=list)
    index_path: Path = field(default_factory=lambda: Path.home() / ".tsunagou" / "projects.json")
    profile_path: Path = field(default_factory=lambda: Path.home() / ".tsunagou" / "console-profile.json")
    poll_ms: int = 5000
    daemon_autostart: bool = False
    web_root: Path | None = None
    path: Path | None = None

    @classmethod
    def load(cls, path: str | Path | None = None) -> ConsoleConfig:
        """Read the config; a missing file means "use the defaults"."""

        target = _expanded_path(path) if path is not None else default_config_path()
        if not target.is_file():
            if path is not None:
                raise FileNotFoundError(f"console_config_not_found:{target}")
            return cls(path=target)
        try:
            raw = json.loads(target.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"console_config_invalid_json:{target}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"console_config_must_be_an_object:{target}")
        known = {item.name for item in fields(cls)} - {"path", "port_explicit"}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError("console_config_unknown_key:" + ",".join(unknown))
        config = cls(path=target)
        for key, value in raw.items():
            if key in {"projects_root", "index_path", "profile_path", "web_root"}:
                setattr(config, key, _expanded_path(value) if value else None)
            elif key == "scan_roots":
                config.scan_roots = [_expanded_path(item) for item in value or []]
            else:
                setattr(config, key, value)
        config.port_explicit = "port" in raw
        return config

    def resolved_scan_roots(self) -> list[Path]:
        """The directories to look in; a project usually sits beside projects_root."""

        roots = self.scan_roots or [self.projects_root.parent]
        return [root.expanduser().resolve() for root in roots]

    def web_directory(self) -> Path:
        """The console page itself, shipped next to the package in this repository."""

        candidate = self.web_root or (Path(__file__).resolve().parents[3] / "web")
        if not candidate.is_dir():
            raise FileNotFoundError(f"console_web_directory_not_found:{candidate}")
        return candidate

    def public(self) -> dict[str, Any]:
        """What the browser is allowed to know. It never includes a token."""

        return {
            "poll_ms": self.poll_ms,
            "projects_root": str(self.projects_root),
            "scan_roots": [str(root) for root in self.resolved_scan_roots()],
            "daemon_autostart": self.daemon_autostart,
        }
