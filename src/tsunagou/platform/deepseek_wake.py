"""Private local configuration shared with the packaged Desktop wake plugin."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from tsunagou.platform.db.sqlite import ProjectLock
from tsunagou.platform.private_files import restrict_access, write_private_bytes


def deepseek_wake_directory() -> Path:
    return Path.home() / ".tsunagou/hosts/deepseek-wake"


def deepseek_wake_managed_path() -> Path:
    return deepseek_wake_directory() / "managed.json"


def deepseek_wake_runtime_path() -> Path:
    return deepseek_wake_directory() / "runtime.json"


def read_deepseek_wake_configuration() -> dict[str, Any]:
    path = deepseek_wake_managed_path()
    try:
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError()
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("format_version") != 1
                or not isinstance(value.get("key"), str) or len(value["key"]) < 32
                or not isinstance(value.get("bindings"), list)):
            raise ValueError()
        for binding in value["bindings"]:
            if (not isinstance(binding, dict) or set(binding) != {"project_id", "agent_id", "session_id"}
                    or any(not isinstance(item, str) or not item.strip() for item in binding.values())):
                raise ValueError()
        return value
    except (OSError, ValueError, UnicodeError):
        raise RuntimeError("deepseek_wake_configuration_invalid") from None


def _private_directory() -> Path:
    directory = deepseek_wake_directory()
    if directory.is_symlink():
        raise RuntimeError("deepseek_wake_configuration_invalid")
    directory.mkdir(parents=True, exist_ok=True)
    restrict_access(directory, directory=True)
    return directory


def _write(value: dict[str, Any]) -> None:
    write_private_bytes(deepseek_wake_managed_path(), (json.dumps(value, sort_keys=True) + "\n").encode())


def ensure_deepseek_wake_configuration() -> Path:
    directory = _private_directory()
    with ProjectLock(directory / "configuration.lock"):
        path = deepseek_wake_managed_path()
        if path.exists():
            read_deepseek_wake_configuration()
            restrict_access(path)
        else:
            _write({"format_version": 1, "key": secrets.token_urlsafe(48), "bindings": []})
        return path


def bind_deepseek_wake(project_id: str, agent_id: str, session_id: str) -> None:
    """Called only with the authenticated enrollment result and host-derived session."""
    binding = {"project_id": project_id, "agent_id": agent_id, "session_id": session_id}
    if any(not isinstance(value, str) or not value.strip() for value in binding.values()):
        raise RuntimeError("deepseek_wake_binding_invalid")
    directory = _private_directory()
    with ProjectLock(directory / "configuration.lock"):
        value: dict[str, Any] = read_deepseek_wake_configuration() if deepseek_wake_managed_path().exists() else {
            "format_version": 1, "key": secrets.token_urlsafe(48), "bindings": [],
        }
        bindings = [item for item in value["bindings"] if not (
            (item["project_id"] == project_id and item["agent_id"] == agent_id)
            or item["session_id"] == session_id
        )]
        bindings.append(binding)
        if bindings != value["bindings"]:
            value["bindings"] = bindings
            _write(value)
