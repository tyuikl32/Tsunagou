"""Private, durable handoff from the local console to a host conversation.

This store carries selection and lifecycle only. Tickets, sessions and grants stay
with the existing onboarding flow. The mutex covers local compare/write work;
callers must never keep it across host or daemon requests.

Why it is not Codex-only: a person asking an Agent to join says one sentence inside the
host, and at that moment the chat knows only its own conversation id and working
directory. The coordination root is *not* derivable from either one — a project may
coordinate several folders, and the console creates projects under its own root — so the
one thing that can answer "which project, which role" is the record the console wrote
when the person clicked. Every host with an in-chat entry point reads this store, which
is why ``active`` is one slot for the whole machine: at most one Agent is being enrolled
at a time, and that is exactly what makes the answer unambiguous.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tsunagou.platform.private_file_lock import private_file_lock
from tsunagou.platform.private_files import restrict_access, write_private_bytes

ENROLLMENT_TTL_SECONDS = 900.0
_BOUND = {"claimed", "failed", "enrolled", "arrived"}
_ACTIVE = {"pending", "claimed", "failed", "enrolled"}
_TERMINAL = {"cancelled", "expired", "forgotten"}


class EnrollmentStore:
    """One uncompleted Agent handoff per OS user; retain completed records by id."""

    def __init__(self, directory: Path | None = None, *, clock: Callable[[], float] = time.time) -> None:
        configured = directory or os.environ.get("TSUNAGOU_ENROLLMENT_DIR")
        self.directory = Path(configured).expanduser().absolute() if configured else Path.home() / ".tsunagou" / "console-enrollments"
        self.path = self.directory / "enrollments.json"
        self._clock = clock

    @contextmanager
    def _transaction(self) -> Iterator[dict[str, Any]]:
        if self.directory.is_symlink() or self.path.is_symlink():
            raise RuntimeError("enrollment_private_path_invalid")
        self.directory.mkdir(parents=True, exist_ok=True)
        restrict_access(self.directory, directory=True)
        with private_file_lock(self.path):
            try:
                state = (
                    json.loads(self.path.read_text(encoding="utf-8"))
                    if self.path.exists()
                    else {
                        "format_version": 1,
                        "active_id": None,
                        "records": {},
                    }
                )
            except (OSError, ValueError) as exc:
                raise RuntimeError("enrollment_store_invalid") from exc
            if not isinstance(state, dict) or state.get("format_version") != 1 or not isinstance(state.get("records"), dict):
                raise RuntimeError("enrollment_store_invalid")
            before = json.dumps(state, sort_keys=True)
            for key, record in state["records"].items():
                if (
                    not isinstance(record, dict)
                    or record.get("enrollment_id") != key
                    or not isinstance(record.get("revision"), int)
                    or not isinstance(record.get("expires_at"), (int, float))
                ):
                    raise RuntimeError("enrollment_store_invalid")
                if record.get("status") == "pending" and self._clock() >= record["expires_at"]:
                    self._change(record, status="expired")
            active = state["records"].get(state.get("active_id"))
            if active is not None and active.get("status") not in _ACTIVE:
                state["active_id"] = None
            try:
                yield state
            finally:
                if json.dumps(state, sort_keys=True) != before:
                    write_private_bytes(self.path, (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    def _change(self, record: dict[str, Any], **updates: Any) -> None:
        record.update(updates)
        record["revision"] += 1
        record["updated_at"] = self._clock()

    @staticmethod
    def _record(state: dict[str, Any], enrollment_id: str) -> dict[str, Any]:
        record = state["records"].get(enrollment_id)
        if not isinstance(record, dict):
            raise RuntimeError("enrollment_not_found")
        return record

    @staticmethod
    def _owner(record: dict[str, Any], thread_id: str) -> None:
        if not thread_id or record.get("thread_id") != thread_id:
            raise RuntimeError("enrollment_claimed_by_another_chat")
        if record.get("status") in _TERMINAL:
            raise RuntimeError("enrollment_" + str(record["status"]))

    def create(
        self,
        *,
        project_id: str,
        project_root: Path,
        role: str,
        nickname: str = "",
        adapter: str = "codex",
        baseline: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Record the person's decision: this Agent joins this project with this role.

        Codex claims the record from inside its chat and the ticket is signed at claim
        time; the other hosts keep their own handoff (a ticket written into the project,
        or nothing at all because the chat signs its own) and only *read* this record to
        learn where they are joining. Both shapes need the same three facts, and both
        need the single slot: one enrollment at a time is what makes "which project"
        unambiguous for the chat that is asking.

        ``baseline`` is who already sat in this project when the request was made. A host
        that enrolls inside its own chat has no ticket and no receipt to wait for, so the
        only thing that can be watched is the roster: "somebody new arrived". Without the
        baseline written down here, a console that was restarted (or a page that was
        reloaded after the arrival) could never tell "new" from "already there".
        """

        if (
            not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", str(adapter or ""))
            or role not in {"main", "worker"} or not project_id or not project_root.is_absolute()
        ):
            raise RuntimeError("enrollment_selection_invalid")
        known = sorted({str(item) for item in baseline if str(item)})
        with self._transaction() as state:
            if state.get("active_id"):
                active = self._record(state, state["active_id"])
                if (
                    active["project_id"] == project_id
                    and Path(active["project_root"]).resolve() == project_root.resolve()
                    and active["requested_role"] == role
                    and active["adapter"] == adapter
                ):
                    return dict(active)
                raise RuntimeError("enrollment_already_pending")
            enrollment_id = uuid.uuid4().hex
            now = self._clock()
            record = {
                "enrollment_id": enrollment_id,
                "project_id": project_id,
                "project_root": str(project_root.resolve()),
                "requested_role": role,
                "nickname": nickname.strip(),
                "adapter": adapter,
                "status": "pending",
                "revision": 1,
                "created_at": now,
                "updated_at": now,
                "expires_at": now + ENROLLMENT_TTL_SECONDS,
                "receipt_file": str(self.directory / (enrollment_id + ".receipt.json")),
                **({"baseline": known} if known else {}),
            }
            state["records"][enrollment_id] = record
            state["active_id"] = enrollment_id
            return dict(record)

    def note_baseline(self, enrollment_id: str, *, agent_ids: Iterable[str]) -> dict[str, Any]:
        """Write the baseline down late, for a record whose project was unreadable then.

        Only ever fills a gap: a record that already has a baseline (or that a chat has
        claimed) is left exactly as it is.
        """

        known = sorted({str(item) for item in agent_ids if str(item)})
        with self._transaction() as state:
            record = self._record(state, enrollment_id)
            if record.get("baseline") is not None or record.get("thread_id") or record["status"] in _TERMINAL:
                return dict(record)
            self._change(record, baseline=known)
            return dict(record)

    def get(self, enrollment_id: str) -> dict[str, Any]:
        with self._transaction() as state:
            return dict(self._record(state, enrollment_id))

    def active(self) -> dict[str, Any] | None:
        """Inspect the user-visible slot without claiming it or selecting a chat."""
        if not self.path.exists():
            return None
        with self._transaction() as state:
            active_id = state.get("active_id")
            return dict(self._record(state, active_id)) if active_id else None

    def current(self, thread_id: str | None = None) -> dict[str, Any]:
        with self._transaction() as state:
            if thread_id:
                owned = [r for r in state["records"].values() if r.get("thread_id") == thread_id and r["status"] in _BOUND]
                if owned:
                    return dict(max(owned, key=lambda r: r["created_at"]))
            active_id = state.get("active_id")
            if not active_id:
                raise RuntimeError("enrollment_not_pending")
            record = self._record(state, active_id)
            if record.get("thread_id") and record["thread_id"] != thread_id:
                raise RuntimeError("enrollment_claimed_by_another_chat")
            return dict(record)

    def claim(self, enrollment_id: str, thread_id: str, *, expected_revision: int) -> dict[str, Any]:
        if not thread_id.strip():
            raise RuntimeError("enrollment_thread_required")
        with self._transaction() as state:
            record = self._record(state, enrollment_id)
            if record["status"] in _TERMINAL:
                raise RuntimeError("enrollment_" + str(record["status"]))
            if record.get("thread_id"):
                self._owner(record, thread_id)
                if record["status"] == "failed":
                    self._change(record, status="claimed", error=None)
                return dict(record)
            if record["revision"] != expected_revision:
                raise RuntimeError("enrollment_revision_conflict")
            if state.get("active_id") != enrollment_id or record["status"] != "pending":
                raise RuntimeError("enrollment_not_pending")
            self._change(record, status="claimed", thread_id=thread_id)
            return dict(record)

    def mark_enrolled(self, enrollment_id: str, thread_id: str, *, agent_id: str) -> dict[str, Any]:
        if not agent_id:
            raise RuntimeError("enrollment_agent_required")
        with self._transaction() as state:
            record = self._record(state, enrollment_id)
            self._owner(record, thread_id)
            if record.get("agent_id") and record["agent_id"] != agent_id:
                raise RuntimeError("enrollment_agent_mismatch")
            if record["status"] != "arrived":
                self._change(record, status="enrolled", agent_id=agent_id, error=None)
            return dict(record)

    def fail(self, enrollment_id: str, thread_id: str, error: str) -> dict[str, Any]:
        with self._transaction() as state:
            record = self._record(state, enrollment_id)
            self._owner(record, thread_id)
            if record["status"] not in {"enrolled", "arrived"}:
                code = error.split(":", 1)[0]
                safe = code if re.fullmatch(r"[a-z][a-z0-9_]{0,99}", code) else "enrollment_connect_failed"
                self._change(record, status="failed", error=safe)
            return dict(record)

    def cancel(self, enrollment_id: str) -> dict[str, Any]:
        with self._transaction() as state:
            record = self._record(state, enrollment_id)
            if record["status"] == "arrived":
                raise RuntimeError("enrollment_already_arrived")
            if record.get("thread_id"):
                raise RuntimeError("enrollment_already_claimed")
            if record["status"] not in _TERMINAL:
                self._change(record, status="cancelled")
            if state.get("active_id") == enrollment_id:
                state["active_id"] = None
            return dict(record)

    def mark_arrived(self, enrollment_id: str) -> dict[str, Any]:
        """Called by the console only after checking the original-host receipt."""
        with self._transaction() as state:
            record = self._record(state, enrollment_id)
            if record["status"] == "arrived":
                return dict(record)
            if record["status"] != "enrolled" or not record.get("agent_id"):
                raise RuntimeError("enrollment_not_enrolled")
            self._change(record, status="arrived")
            if state.get("active_id") == enrollment_id:
                state["active_id"] = None
            return dict(record)

    def active_for(self, adapter: str) -> dict[str, Any] | None:
        """The pending slot, but only when it belongs to this host's adapter.

        An in-chat entry point asks "is somebody waiting for *me*?": a Codex selection
        must not be handed to a DeepSeek chat that happens to ask first, and vice versa.
        Reading only — claiming is still the Codex path's job (or the console's).
        """

        wanted = str(adapter or "").strip().lower()
        active = self.active()
        if active is None or not wanted:
            return None
        return active if str(active.get("adapter") or "").lower() == wanted else None

    def observe_arrival(self, enrollment_id: str, *, agent_id: str) -> dict[str, Any]:
        """Close a record whose Agent was watched into the project by the console.

        The hosts that enroll inside their own chat (or into a file the host reads)
        never claim a record: there is no thread id to bind, and the console sees the
        Agent appear in the roster instead. That observation is the same fact
        ``mark_arrived`` records for Codex, so it closes the slot the same way.
        """

        if not agent_id:
            raise RuntimeError("enrollment_agent_required")
        with self._transaction() as state:
            record = self._record(state, enrollment_id)
            if record["status"] == "arrived":
                return dict(record)
            if record.get("thread_id"):
                # A bound record has an owner: only that chat may finish it.
                raise RuntimeError("enrollment_claimed_by_another_chat")
            if record["status"] in _TERMINAL:
                raise RuntimeError("enrollment_" + str(record["status"]))
            self._change(record, status="arrived", agent_id=agent_id, error=None)
            if state.get("active_id") == enrollment_id:
                state["active_id"] = None
            return dict(record)

    def forget_project(self, project_id: str) -> list[str]:
        """Invalidate handoffs only; never remove global MCP or an enrolled Agent."""
        with self._transaction() as state:
            dropped = []
            for record in state["records"].values():
                if record["project_id"] != project_id or record["status"] == "forgotten":
                    continue
                self._change(record, status="forgotten")
                dropped.append(record["enrollment_id"])
                if state.get("active_id") == record["enrollment_id"]:
                    state["active_id"] = None
            return dropped
