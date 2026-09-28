"""Cross-language process-owned mutex for brief private file compare/write steps."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import socket
import time
from collections.abc import Iterator
from pathlib import Path

_LOCK_PORT_START = 20000
_LOCK_PORT_COUNT = 40000


def _next_lock_port(port: int) -> int:
    """Choose the next deterministic candidate after a Windows exclusion."""
    return _LOCK_PORT_START + ((port - _LOCK_PORT_START + 1) % _LOCK_PORT_COUNT)


@contextlib.contextmanager
def private_file_lock(path: Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Match bridge private-file-lock.ts; never nest or hold across HTTP."""
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = str(path.parent.resolve() / path.name)
    if os.name == "nt":
        canonical = canonical.lower()
    port = _LOCK_PORT_START + int.from_bytes(hashlib.sha256(canonical.encode()).digest()[:2], "big") % _LOCK_PORT_COUNT
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as owner:
        if os.name == "nt":
            owner.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        while True:
            try:
                owner.bind(("127.0.0.1", port))
                owner.listen(1)
                break
            except OSError as exc:
                if exc.errno in {errno.EACCES, 10013} and os.name == "nt":
                    # Windows reserves dynamic port ranges on some hosts. All
                    # contenders derive the same fallback sequence, so a
                    # reserved candidate is skipped without weakening the
                    # mutex when a usable candidate is occupied.
                    port = _next_lock_port(port)
                    continue
                if exc.errno not in {errno.EADDRINUSE, 10048}:
                    raise RuntimeError("credential_private_lock_unavailable") from exc
                if time.monotonic() >= deadline:
                    raise RuntimeError("credential_private_lock_busy:retry_pending_request") from exc
                time.sleep(0.02)
        yield
