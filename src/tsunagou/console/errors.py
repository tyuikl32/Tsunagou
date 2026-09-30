"""Errors the console can explain to a caller.

The daemon answers with ``{"detail": {"code": "..."}}``; a two-hop call should
not change dialect halfway, so the console speaks the same shape and reuses the
daemon's own error bodies verbatim when it forwards one.
"""

from __future__ import annotations

from typing import Any


class ConsoleError(RuntimeError):
    """A refusable request: the code is stable, the status is the HTTP answer."""

    def __init__(self, code: str, *, status: int = 400, detail: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}

    def body(self) -> dict[str, Any]:
        return {"detail": {"code": self.code, **self.detail}}
