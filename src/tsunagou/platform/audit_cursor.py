"""Bounded, runtime-local audit cursors; never authorization credentials."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.time import now_ms


class AuditCursorCodec:
    """Bind a keyset position and snapshot to the exact authenticated query.

    The signing key lives only in this query provider. A daemon restart rejects
    old cursors; the caller starts a fresh query. No secret enters SQLite.
    """

    def __init__(self, *, clock: Callable[[], int] = now_ms) -> None:
        self._key = secrets.token_bytes(32)
        self._clock = clock

    def encode(self, *, context: Mapping[str, object], after_seq: int, as_of_event_seq: int) -> str:
        if not 0 <= after_seq <= as_of_event_seq:
            raise ValueError("invalid_audit_cursor_position")
        body = json.dumps({
            "v": 1, "context": canonical_digest(dict(context)), "after": after_seq,
            "as_of": as_of_event_seq, "expires_at": self._clock() + 900_000,
        }, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = hmac.digest(self._key, body, hashlib.sha256)
        return base64.urlsafe_b64encode(body + signature).decode("ascii").rstrip("=")

    def decode(self, token: str, *, context: Mapping[str, object]) -> tuple[int, int]:
        if not token or len(token) > 2048:
            raise ValueError("invalid_audit_cursor")
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            if len(raw) <= 32:
                raise ValueError("invalid_audit_cursor")
            body, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(signature, hmac.digest(self._key, body, hashlib.sha256)):
                raise ValueError("invalid_audit_cursor")
            data = json.loads(body)
            if not isinstance(data, dict) or set(data) != {"v", "context", "after", "as_of", "expires_at"}:
                raise ValueError("invalid_audit_cursor")
            if data["v"] != 1 or data["context"] != canonical_digest(dict(context)):
                raise ValueError("invalid_audit_cursor")
            after, as_of, expires_at = data["after"], data["as_of"], data["expires_at"]
            if any(type(value) is not int for value in (after, as_of, expires_at)) or not 0 <= after <= as_of:
                raise ValueError("invalid_audit_cursor")
        except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
            raise ValueError("invalid_audit_cursor") from exc
        if self._clock() >= expires_at:
            raise ValueError("expired_audit_cursor")
        return int(after), int(as_of)
