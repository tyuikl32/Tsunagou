from __future__ import annotations

import uuid


def new_id() -> str:
    """Return UUIDv7 when the runtime exposes it, with a UUIDv4 fallback."""
    factory = getattr(uuid, "uuid7", None)
    value = factory() if factory else uuid.uuid4()
    return str(value).lower()


def is_id(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return value == value.lower()
