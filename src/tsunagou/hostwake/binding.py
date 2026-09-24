"""Private, atomic persistence for host bindings.

Only the adapter reads this file.  Public project queries receive a
``HostBindingRef`` with digests and status, never the raw thread/session IDs.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from tsunagou.hostwake.port import BindingStatus, CapabilityStatus, HostBindingRef


class PrivateBindingStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def list_refs(self) -> list[HostBindingRef]:
        with self._lock:
            return [self._ref_from_record(record) for record in self._load().values()]

    def get(self, agent_id: str) -> tuple[HostBindingRef, dict[str, Any]] | None:
        with self._lock:
            record = self._load().get(agent_id)
            if record is None:
                return None
            return self._ref_from_record(record), dict(record)

    def put(
        self,
        ref: HostBindingRef,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        endpoint: str | None = None,
        executable: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> HostBindingRef:
        with self._lock:
            records = self._load()
            prior = records.get(ref.agent_id, {})
            record = {**prior, **asdict(ref), "extra": {**prior.get("extra", {}), **(extra or {})}}
            for key, value in (
                ("thread_id", thread_id), ("session_id", session_id),
                ("endpoint", endpoint), ("executable", executable),
            ):
                if value is not None:
                    record[key] = value
            records[ref.agent_id] = record
            self._save(records)
            return self._ref_from_record(record)

    def update_status(self, agent_id: str, status: str, *, reason: str | None = None) -> HostBindingRef:
        with self._lock:
            records = self._load()
            record = records.get(agent_id)
            if record is None:
                raise KeyError("host_binding_not_found")
            record["status"] = status
            if reason:
                record.setdefault("last_probe", {})["reason"] = reason
            self._save(records)
            return self._ref_from_record(record)

    def delete(self, agent_id: str) -> None:
        with self._lock:
            records = self._load()
            if agent_id in records:
                del records[agent_id]
                self._save(records)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("host_binding_store_invalid") from exc
        if not isinstance(raw, dict):
            raise RuntimeError("host_binding_store_invalid")
        return raw

    def _save(self, records: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(records, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _ref_from_record(record: dict[str, Any]) -> HostBindingRef:
        raw_capabilities = record.get("capabilities")
        capabilities = {
            str(key): cast(CapabilityStatus, str(value))
            for key, value in (raw_capabilities.items() if isinstance(raw_capabilities, dict) else ())
        }
        return HostBindingRef(
            binding_id=str(record["binding_id"]),
            agent_id=str(record["agent_id"]),
            provider=str(record["provider"]),
            adapter_profile=str(record["adapter_profile"]),
            thread_id_digest=record.get("thread_id_digest"),
            session_id_digest=record.get("session_id_digest"),
            endpoint_kind=str(record.get("endpoint_kind", "unknown")),
            cwd_digest=record.get("cwd_digest"),
            scope_digest=record.get("scope_digest"),
            policy_digest=record.get("policy_digest"),
            status=cast(BindingStatus, record.get("status", "degraded")),
            binding_revision=int(record.get("binding_revision", 1)),
            connection_epoch=record.get("connection_epoch"),
            capabilities=capabilities,
            last_probe=dict(record.get("last_probe") or {}),
        )
