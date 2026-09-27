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


@contextlib.contextmanager
def private_file_lock(path: Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Match bridge private-file-lock.ts; never nest or hold across HTTP."""
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = str(path.parent.resolve() / path.name)
    if os.name == "nt":
        canonical = canonical.lower()
    port = 20000 + int.from_bytes(hashlib.sha256(canonical.encode()).digest()[:2], "big") % 40000
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
                if exc.errno not in {errno.EADDRINUSE, errno.EACCES, 10048, 10013}:
                    raise RuntimeError("credential_private_lock_unavailable") from exc
                if time.monotonic() >= deadline:
                    raise RuntimeError("credential_private_lock_busy:retry_pending_request") from exc
                time.sleep(0.02)
        yield
