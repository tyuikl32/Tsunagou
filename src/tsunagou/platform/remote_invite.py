"""The invitation a host hands to a remote Agent (cross-machine, host-initiated).

A person on the host picks the project, the host product and the role, and one single-use
ticket is signed. That ticket is bound to the identity the remote will present — so the
invitation carries the identity too:

* hosts whose conversation name the host may choose (OpenCode) get a name from the host;
* hosts whose name only they know (Codex, DeepSeek Harness) report it first, and the host
  types it in (``--conversation-id``).

The invitation **is** a secret: the ticket is in it, handed over the way a password is
(one-time, short-lived, worker-only in practice). Everything else in it — the address to
dial, the project, the role, the expiry — exists so the remote needs nothing else: one
command, then one sentence in its own chat.

Nothing in here is stored on the host: this is a value to show the person and forget.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from datetime import datetime
from typing import Any

PREFIX = "tsunagou-invite-v1:"
VERSION = 1
#: Every field the importing side needs; ``nickname`` is display sugar and may be empty.
REQUIRED = (
    "project_id", "url", "adapter", "profile", "installation_id", "conversation_id",
    "role", "secret", "expires_at",
)
ROLES = ("worker", "main")


def encode(invite: dict[str, Any]) -> str:
    """One copy-pasteable line: the ticket, the address, and who this is for."""

    missing = sorted(key for key in REQUIRED if not str(invite.get(key) or "").strip())
    if missing:
        raise RuntimeError("invite_incomplete:" + ",".join(missing))
    body = {"v": VERSION, "kind": "tsunagou-invite", "nickname": str(invite.get("nickname") or "")}
    body.update({key: str(invite[key]) for key in REQUIRED})
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode(text: str) -> dict[str, Any]:
    """Read an invitation back; each refusal gets its own code so a person can act on it."""

    raw = str(text or "").strip()
    if not raw.startswith(PREFIX):
        raise RuntimeError("invite_malformed")
    payload = raw[len(PREFIX):]
    try:
        body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("invite_malformed") from exc
    if not isinstance(body, dict) or body.get("kind") != "tsunagou-invite":
        raise RuntimeError("invite_malformed")
    if body.get("v") != VERSION:
        raise RuntimeError("invite_unsupported_version")
    for key in REQUIRED:
        if not isinstance(body.get(key), str) or not body[key].strip():
            raise RuntimeError("invite_incomplete:" + key)
    return {
        **{key: str(body[key]) for key in REQUIRED},
        "nickname": str(body.get("nickname") or ""),
        "v": VERSION,
    }


def check(invite: dict[str, Any], *, now: float | None = None) -> None:
    """Refuse an invitation that cannot be honoured: unknown role, or past its expiry."""

    if str(invite.get("role") or "") not in ROLES:
        raise RuntimeError("invite_role_invalid")
    text = str(invite.get("expires_at") or "")
    try:
        expires = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise RuntimeError("invite_malformed") from exc
    if expires <= (time.time() if now is None else now):
        raise RuntimeError("invite_expired")


def seconds_left(invite: dict[str, Any], *, now: float | None = None) -> int:
    """How long this invitation still works — the number the page puts on a countdown."""

    text = str(invite.get("expires_at") or "")
    try:
        expires = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0
    return max(0, int(expires - (time.time() if now is None else now)))
