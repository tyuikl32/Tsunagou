"""Cross-language process-owned mutex for brief private file compare/write steps."""

from __future__ import annotations

import contextlib
import ctypes
import errno
import hashlib
import os
import socket
import sys
import time
from collections.abc import Iterator
from pathlib import Path

_LOCK_PORT_START = 20000
_LOCK_PORT_COUNT = 40000


@contextlib.contextmanager
def _windows_pipe_lock(name: str, deadline: float) -> Iterator[None]:
    # Match libuv's first-instance bind. No connections/data/PID files are
    # involved: the kernel owns the name until this handle/process closes.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateNamedPipeW
    create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                       ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    create.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    while True:
        # PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE, byte mode, one instance.
        handle = create(name, 0x00080003, 0, 1, 0, 0, 0, None)
        if handle != ctypes.c_void_p(-1).value:
            break
        if ctypes.get_last_error() not in {5, 231}:  # access denied / pipe busy
            raise RuntimeError("credential_private_lock_unavailable")
        if time.monotonic() >= deadline:
            raise RuntimeError("credential_private_lock_busy:retry_pending_request")
        time.sleep(0.02)
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


@contextlib.contextmanager
def private_file_lock(path: Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Match bridge private-file-lock.ts; never nest or hold across HTTP."""
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = str(path.parent.resolve() / path.name)
    if os.name == "nt":
        canonical = canonical.lower()
    digest = hashlib.sha256(canonical.encode()).digest()
    deadline = time.monotonic() + timeout
    if os.name == "nt":
        with _windows_pipe_lock("\\\\.\\pipe\\tsunagou-private-lock-" + digest.hex(), deadline):
            yield
        return
    # Linux abstract sockets also disappear on process exit. macOS retains the
    # existing fail-busy TCP fallback; never reclaim a stale filesystem socket.
    address: str | tuple[str, int]
    if sys.platform == "linux":
        family = socket.AF_UNIX
        address = "\0tsunagou-private-lock-" + digest.hex()
    else:
        family = socket.AF_INET
        address = ("127.0.0.1", _LOCK_PORT_START + int.from_bytes(digest[:2], "big") % _LOCK_PORT_COUNT)
    with socket.socket(family, socket.SOCK_STREAM) as owner:
        while True:
            try:
                owner.bind(address)
                owner.listen(1)
                break
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE:
                    raise RuntimeError("credential_private_lock_unavailable") from exc
                if time.monotonic() >= deadline:
                    raise RuntimeError("credential_private_lock_busy:retry_pending_request") from exc
                time.sleep(0.02)
        yield
