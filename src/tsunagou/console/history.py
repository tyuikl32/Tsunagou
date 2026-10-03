"""What the console last carried, kept so a stopped project is still readable.

The console reads a project by asking its daemon. When that daemon stops — project finished,
machine restarted, process killed — there is nothing left to ask, and every panel that was
full a minute ago turns empty. This module keeps the console's own record of **what it
carried**: for each project and each exit it read, the last answer and when it arrived.

Three rules make it safe to have:

* **It is a record, never a source of truth.** Nothing here is ever written back to a daemon,
  and no decision is ever taken from it. The project's own state stays authoritative; this is
  "what that machine last said to me".
* **It never breaks a read.** A damaged, missing or unreadable file means "no record" — never
  an error on a screen that would otherwise have worked.
* **It is bounded.** Lists are trimmed, oversized answers are replaced by a note, and a
  project's record is deleted with the project.

``console-history/`` sits beside the console's project index, so the layout stays "one file
per project" and a test that points the index at a temporary directory is isolated for free.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tsunagou.platform.private_file_lock import private_file_lock
from tsunagou.platform.private_files import write_private_bytes

DIRECTORY_NAME = "console-history"
FORMAT_VERSION = 1
#: Longer lists are trimmed: the console's job is "the gist of what was there", and an
#: unbounded copy of every task, message and audit row is exactly what this must not become.
MAX_ITEMS = 500
#: One answer larger than this is recorded as "too big to keep" instead.
MAX_BYTES = 262_144
#: A guard against a runaway key space (odd URLs); the ordinary project uses under twenty.
MAX_SOURCES = 48
#: Lists that are known to be lists of rows; anything else is stored as-is.
_LIST_KEYS = ("items", "history", "messages", "open_tasks", "tasks", "attempts", "results")


def _directory(beside: Path) -> Path:
    return beside.parent / DIRECTORY_NAME


class HistoryStore:
    """One file per project, holding the last answer seen for each exit."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    @classmethod
    def beside_index(cls, index_path: Path) -> HistoryStore:
        """Where the console keeps its own state; no extra configuration to write down."""

        return cls(_directory(Path(index_path)))

    def path_for(self, project_id: str) -> Path:
        safe = "".join(ch for ch in str(project_id) if ch.isalnum() or ch in "-_")[:64]
        return self.directory / f"{safe or 'unknown'}.json"

    def read(self, project_id: str) -> dict[str, Any]:
        """The whole record for one project; an unreadable file reads as "nothing kept"."""

        path = self.path_for(project_id)
        if not path.is_file():
            return {"format_version": FORMAT_VERSION, "project_id": project_id, "sources": {}}
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {"format_version": FORMAT_VERSION, "project_id": project_id, "sources": {}}
        if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
            return {"format_version": FORMAT_VERSION, "project_id": project_id, "sources": {}}
        sources = {
            str(name): item for name, item in raw["sources"].items()
            if isinstance(item, dict) and "payload" in item
        }
        return {"format_version": FORMAT_VERSION, "project_id": project_id, "sources": sources}

    def payload(self, project_id: str, source: str) -> tuple[Any, str] | None:
        """``(payload, captured_at)`` for one recorded exit, or ``None`` if never seen."""

        item = self.read(project_id)["sources"].get(source)
        if not isinstance(item, dict) or "payload" not in item:
            return None
        return item["payload"], str(item.get("captured_at") or "")

    def captured_at(self, project_id: str, source: str) -> str | None:
        record = self.payload(project_id, source)
        return record[1] if record is not None else None

    def latest(self, project_id: str) -> str | None:
        """When this project was last recorded at all — what the project card shows."""

        stamps = [str(item.get("captured_at") or "") for item in self.read(project_id)["sources"].values()]
        return max((stamp for stamp in stamps if stamp), default=None) or None

    def summary(self, project_id: str) -> dict[str, Any]:
        """A small description for a list response: when, and how many exits were kept."""

        sources = self.read(project_id)["sources"]
        return {"captured_at": self.latest(project_id), "sources": len(sources)}

    def record(self, project_id: str, source: str, payload: Any, *, captured_at: str | None) -> None:
        """Keep the last answer for one exit. Never raises: this is a side effect of reading."""

        try:
            self._record(project_id, source, payload, str(captured_at or ""))
        except (OSError, ValueError, TypeError):
            # A record that cannot be written must not take the live answer down with it.
            return

    def _record(self, project_id: str, source: str, payload: Any, captured_at: str) -> None:
        name = str(source).strip()
        if not name:
            return
        bounded = self._bounded(payload)
        if bounded is None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(project_id)
        with private_file_lock(path):
            sources: dict[str, Any] = dict(self.read(project_id)["sources"])
            if name not in sources and len(sources) >= MAX_SOURCES:
                # Keep the newest MAX_SOURCES exits; drop the oldest by capture time so an
                # odd URL space cannot grow one project's record without bound.
                oldest = min(sources, key=lambda key: str(sources[key].get("captured_at") or ""))
                del sources[oldest]
            sources[name] = {"captured_at": captured_at, "payload": bounded}
            stamps = [str(item.get("captured_at") or "") for item in sources.values()]
            value = {"format_version": FORMAT_VERSION, "project_id": project_id,
                     "captured_at": max(stamps), "sources": sources}
            write_private_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))

    def forget(self, project_id: str) -> bool:
        """Delete one project's record (called when the project itself is deleted)."""

        path = self.path_for(project_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    @staticmethod
    def _bounded(payload: Any) -> Any | None:
        """A copy small enough to keep: long lists trimmed, huge answers replaced by a note."""

        def trim(value: Any) -> Any:
            if isinstance(value, list):
                return [trim(item) for item in value[:MAX_ITEMS]]
            if isinstance(value, dict):
                return {str(key): trim(item) for key, item in value.items()}
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            return str(value)

        trimmed = trim(payload)
        if isinstance(trimmed, dict):
            for key in _LIST_KEYS:
                rows = trimmed.get(key)
                if isinstance(rows, list) and len(rows) >= MAX_ITEMS:
                    trimmed[key + "_trimmed"] = True
        try:
            encoded = json.dumps(trimmed, ensure_ascii=False)
        except (TypeError, ValueError):
            return None
        if len(encoded.encode("utf-8")) > MAX_BYTES:
            return {"note": "这一份太大，没有留下记录（历史只留够用的那一份）。",
                    "too_large": True, "bytes": len(encoded.encode("utf-8"))}
        return trimmed
