"""Evidence helpers deliberately discard host identifiers and transcript content."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Any

BASELINE = (
    "identity.session_isolation", "identity.continuity_evidence", "context.project_read",
    "command.typed_tools", "task.lifecycle", "cognition.report", "contract.participation",
    "inbox.pull_fetch_ack", "response.structured", "recovery.idempotent_reconnect",
    "delivery.deduplicate",
)


class IdentityEvidence:
    """Use a fresh, unexported HMAC key for each experiment."""

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    def digest(self, raw: str) -> str:
        if not raw:
            raise ValueError("missing_host_identity")
        return hmac.new(self._key, raw.encode(), hashlib.sha256).hexdigest()


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def require_baseline(evidence: dict[str, Any]) -> bool:
    """Unknown or incomplete evidence can never authorize ready."""
    rows = evidence.get("baseline", {})
    return set(rows) == set(BASELINE) and all(
        row.get("status") == "supported" and row.get("evidence_refs")
        for row in rows.values()
    )
