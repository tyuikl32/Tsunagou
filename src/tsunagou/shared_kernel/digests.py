from __future__ import annotations

import hashlib
from typing import Any

import rfc8785


def canonical_bytes(value: Any) -> bytes:
    return rfc8785.dumps(value)


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()
