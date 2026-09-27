"""Bounded, command-bound private credential escrow; SQLite keeps only receipts."""

from __future__ import annotations

import json
import re
import secrets
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tsunagou.platform.private_files import protect_bytes, restrict_access, unprotect_bytes, write_private_bytes
from tsunagou.shared_kernel.digests import canonical_bytes, canonical_digest
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import now_ms

_REF = re.compile(r"^delivery:[A-Za-z0-9_-]{24}$")
_SAFE_FIELDS = (
    "receipt_id", "delivery_ref", "delivery_status", "created_at", "expires_at",
    "delivered_at", "recovery_expires_at", "consumed_at", "revoked_at",
)


class SecretDeliveryStore:
    def __init__(self, root: str | Path, *, clock: Callable[[], int] = now_ms) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("private_path_symlink_denied")
        restrict_access(self.root, directory=True)
        self._clock = clock
        # One daemon owns a project (the database process lock). Serialize its
        # simultaneous read/ack requests so a completed ACK cannot revive data.
        self._lock = threading.RLock()

    def put(self, result: dict[str, Any], *, binding: dict[str, Any], ttl_ms: int = 600_000) -> dict[str, Any]:
        if not binding or not 0 < ttl_ms <= 600_000:
            raise ValueError("invalid_secret_delivery_binding_or_ttl")
        created_at = self._clock()
        ref = f"delivery:{secrets.token_urlsafe(18)}"
        value = {
            "version": 2, "receipt_id": new_id(), "delivery_ref": ref,
            "binding_digest": canonical_digest(binding), "delivery_status": "pending",
            "created_at": created_at, "expires_at": created_at + ttl_ms,
            "delivered_at": None, "recovery_expires_at": None, "consumed_at": None, "revoked_at": None,
            "result": result,
        }
        with self._lock:
            self._write(value)
        return self._metadata(value)

    def read(self, ref: str, *, binding: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = self._load(ref, binding)
            if value["delivery_status"] in {"expired", "consumed", "revoked"}:
                raise RuntimeError(f"secret_delivery_{value['delivery_status']}")
            result = value.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("secret_delivery_corrupt")
            if value["delivered_at"] is None:
                delivered_at = self._clock()
                value["delivered_at"] = delivered_at
                value["recovery_expires_at"] = min(value["expires_at"], delivered_at + 120_000)
                value["delivery_status"] = "delivered"
                self._write(value)
            return dict(result)

    def metadata(self, ref: str, *, binding: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._metadata(self._load(ref, binding))

    def acknowledge(self, ref: str, *, binding: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = self._load(ref, binding)
            if value["delivery_status"] in {"expired", "revoked"}:
                raise RuntimeError(f"secret_delivery_{value['delivery_status']}")
            if value["delivered_at"] is None:
                raise RuntimeError("secret_delivery_not_delivered")
            if value["delivery_status"] != "consumed":
                value.update(delivery_status="consumed", consumed_at=self._clock())
                value.pop("result", None)
                self._write(value)
            return self._metadata(value)

    def revoke(self, ref: str, *, binding: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = self._load(ref, binding)
            if value["delivery_status"] not in {"consumed", "revoked", "expired"}:
                value.update(delivery_status="revoked", revoked_at=self._clock())
                value.pop("result", None)
                self._write(value)
            return self._metadata(value)

    def _load(self, ref: str, binding: dict[str, Any]) -> dict[str, Any]:
        path = self._path(ref)
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("secret_delivery_missing")
        try:
            value = json.loads(unprotect_bytes(path.read_bytes()))
        except (OSError, ValueError, RuntimeError) as exc:
            raise RuntimeError("secret_delivery_corrupt") from exc
        if not isinstance(value, dict) or value.get("version") != 2 or value.get("delivery_ref") != ref:
            raise RuntimeError("secret_delivery_corrupt")
        if not secrets.compare_digest(str(value.get("binding_digest", "")), canonical_digest(binding)):
            raise PermissionError("secret_delivery_scope_denied")
        if value.get("delivery_status") not in {"pending", "delivered", "consumed", "revoked", "expired"}:
            raise RuntimeError("secret_delivery_corrupt")
        expiry = value.get("recovery_expires_at") or value.get("expires_at")
        if type(expiry) is not int:
            raise RuntimeError("secret_delivery_corrupt")
        if value["delivery_status"] in {"pending", "delivered"} and self._clock() >= expiry:
            value["delivery_status"] = "expired"
            value.pop("result", None)
            self._write(value)
        return dict(value)

    def _write(self, value: dict[str, Any]) -> None:
        write_private_bytes(self._path(value["delivery_ref"]), protect_bytes(canonical_bytes(value)))

    def _path(self, ref: str) -> Path:
        if not _REF.fullmatch(ref):
            raise ValueError("invalid_delivery_ref")
        return self.root / (ref.removeprefix("delivery:") + ".bin")

    @staticmethod
    def _metadata(value: dict[str, Any]) -> dict[str, Any]:
        return {key: value.get(key) for key in _SAFE_FIELDS}
