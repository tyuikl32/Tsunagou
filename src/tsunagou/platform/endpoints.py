"""Which address a client may dial, versus which one a socket merely listens on.

``--host 0.0.0.0`` is an instruction ("listen on every interface"), not a place: dialling it
fails (on Windows with WSAEADDRNOTAVAIL / WinError 10049), and the IPv6 wildcard is no better.
A daemon records the address it *bound*, so every reader that turns that record into a request
URL has to pass it through :func:`connectable_url` first. One rule, one place -- the CLI
readiness probe, the console relay and the agent-side runtime resolution all use it.
"""

from __future__ import annotations

import urllib.parse

#: Wildcard spellings: "listen everywhere", never "I am here".
WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::", "[::]", "*"})


def connectable_url(url: str) -> str:
    """Swap a wildcard host for the loopback address, and change nothing else."""

    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
        port = parsed.port
    except ValueError:
        return text
    hostname = parsed.hostname
    if hostname is not None and hostname not in WILDCARD_HOSTS:
        return text
    loopback = "[::1]" if hostname in {"::", "[::]"} else "127.0.0.1"
    netloc = f"{loopback}:{port}" if port else loopback
    return urllib.parse.urlunsplit(
        (parsed.scheme or "http", netloc, parsed.path, parsed.query, parsed.fragment)
    )
