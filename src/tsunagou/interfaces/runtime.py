"""One command dispatcher projected through HTTP, MCP, and CLI adapters."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest

Handler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    kind: str
    principal_id: str
    session_id: str | None = None
    connection_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class DispatchResponse:
    command_kind: str
    command_hash: str
    result: dict[str, Any]


class CommandDispatcher:
    def __init__(self, registry_path: str | Path) -> None:
        raw = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        self.registry: dict[str, dict[str, Any]] = raw["commands"]
        self.handlers: dict[str, Handler] = {}

    def register(self, command_kind: str, handler: Handler) -> None:
        if command_kind not in self.registry:
            raise KeyError(f"unregistered_command:{command_kind}")
        self.handlers[command_kind] = handler

    def dispatch(
        self, command_kind: str, envelope: dict[str, Any], *,
        principal: PrincipalContext,
    ) -> DispatchResponse:
        policy = self.registry.get(command_kind)
        if policy is None:
            raise KeyError("unknown_command")
        if policy["principal"] != principal.kind:
            raise PermissionError("principal_kind_denied")
        handler = self.handlers.get(command_kind)
        if handler is None:
            raise KeyError("handler_not_registered")
        expected = {"command_id", "protocol_version", "schema_bundle_digest", "payload"}
        if set(envelope) != expected:
            raise ValueError("malformed_command_envelope")
        semantic = {
            "command_kind": command_kind,
            "principal_kind": principal.kind,
            "principal_id": principal.principal_id,
            "payload": envelope["payload"],
        }
        command_hash = canonical_digest(semantic)
        result = handler(envelope["payload"], {
            "principal_id": principal.principal_id,
            "session_id": principal.session_id,
            "connection_epoch": principal.connection_epoch,
            "command_hash": command_hash,
        })
        return DispatchResponse(command_kind, command_hash, result)

    def mcp_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "inputSchema": {"type": "object", "additionalProperties": False}}
            for name, policy in sorted(self.registry.items())
            if policy["principal"] not in {"U", "D", "T"}
        ]


class BlackboardComposer:
    SENSITIVE_KEYS = {"token", "secret", "credential", "absolute_path", "private_message"}

    def compose(self, sections: dict[str, Any], *, max_items: int = 50) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        truncated: dict[str, int] = {}
        for name, value in sections.items():
            filtered = self._filter(value)
            if isinstance(filtered, list) and len(filtered) > max_items:
                truncated[name] = len(filtered) - max_items
                filtered = filtered[:max_items]
            snapshot[name] = filtered
        if truncated:
            snapshot["truncated"] = truncated
        snapshot["snapshot_digest"] = canonical_digest(snapshot)
        return snapshot

    def _filter(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._filter(item) for key, item in value.items()
                if key.casefold() not in self.SENSITIVE_KEYS
            }
        if isinstance(value, list):
            return [self._filter(item) for item in value]
        return value


PROMPT_FRAGMENTS = {
    "identity": "Use the authenticated project identity supplied by the bridge; never invent actor IDs.",
    "task_boundary": "Claim and resume prepare work. Only task.start begins execution.",
    "coordination": "Report explicit assumptions, uncertainty, and contract changes through project tools.",
}
PROMPT_VERSION = "1.0"
PROMPT_DIGEST = canonical_digest({"version": PROMPT_VERSION, "fragments": PROMPT_FRAGMENTS})
