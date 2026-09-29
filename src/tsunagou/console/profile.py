"""The little bits of state that are about the person, not about a project.

An agent's display name and vendor are not coordination facts: nothing in the
protocol changes if a worker is called "熊猫" and runs on Codex. They live here,
next to the user's own name and colour theme, so the daemon stays free of
presentation and a re-install does not lose them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROFILE_VERSION = 1
_AGENT_FIELDS = ("nickname", "vendor", "icon")


def _empty_profile() -> dict[str, Any]:
    return {"version": PROFILE_VERSION, "nickname": "", "theme": "", "agents": {}}


def load_profile(path: Path) -> dict[str, Any]:
    """Read the profile; a missing or damaged file means "nothing set yet"."""

    if not path.is_file():
        return _empty_profile()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return _empty_profile()
    if not isinstance(raw, dict):
        return _empty_profile()
    profile = _empty_profile()
    profile["nickname"] = str(raw.get("nickname") or "")
    profile["theme"] = str(raw.get("theme") or "")
    agents = raw.get("agents")
    if isinstance(agents, dict):
        profile["agents"] = {
            str(agent_id): {key: value for key, value in entry.items() if key in _AGENT_FIELDS}
            for agent_id, entry in agents.items()
            if isinstance(entry, dict)
        }
    return profile


def update_profile(path: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into the profile and return the stored result.

    A patch is merged, never replaced: a screen that only edits the theme must not
    be able to wipe the agent names by leaving them out.
    """

    profile = load_profile(path)
    for key in ("nickname", "theme"):
        if key in patch:
            profile[key] = str(patch[key] or "")
    agents = patch.get("agents")
    if agents is not None:
        if not isinstance(agents, dict):
            raise ValueError("profile_agents_must_be_an_object")
        for agent_id, entry in agents.items():
            if not isinstance(entry, dict):
                raise ValueError("profile_agent_must_be_an_object")
            merged = dict(profile["agents"].get(str(agent_id)) or {})
            merged.update({key: str(value or "") for key, value in entry.items() if key in _AGENT_FIELDS})
            profile["agents"][str(agent_id)] = merged
    _write(path, profile)
    return profile


def _write(path: Path, profile: dict[str, Any]) -> None:
    """Replace the profile in one step so a reader never sees half a file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
