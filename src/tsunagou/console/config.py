"""Console configuration: the one file a person edits.

Every path is written in the file, expanded against the current user, and used
without further guessing, so "where does the console look?" has exactly one
answer per deployment.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

CONFIG_FILENAME = ".tsunagou-console.json"
_ENVIRONMENT_OVERRIDE = "TSUNAGOU_CONSOLE_CONFIG"


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
    port: int = 0
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
        known = {item.name for item in fields(cls)} - {"path"}
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
