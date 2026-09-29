import hashlib
import os
import socket
import sys
from pathlib import Path

import pytest

from tsunagou.platform.private_file_lock import private_file_lock


@pytest.mark.skipif(os.name != "nt" and not sys.platform.startswith("linux"), reason="native IPC locks are Windows/Linux")
def test_credential_lock_does_not_contend_with_unrelated_tcp_listener(tmp_path: Path) -> None:
    for i in range(100):
        path = tmp_path / f"ticket-{i}.json"
        canonical = str(path).lower() if os.name == "nt" else str(path)
        port = 20000 + int.from_bytes(hashlib.sha256(canonical.encode()).digest()[:2], "big") % 40000
        with socket.socket() as unrelated:
            try:
                unrelated.bind(("127.0.0.1", port))
            except OSError:
                continue
            unrelated.listen(1)
            with private_file_lock(path, timeout=0):
                assert unrelated.getsockname()[1] == port
            return
    pytest.fail("could not find a loopback port for collision regression")


def test_private_path_mutex_is_exclusive_and_releases_after_exception(tmp_path: Path) -> None:
    path = tmp_path / "ticket.json"
    with pytest.raises(ValueError, match="fixture_crash"):
        with private_file_lock(path):
            with pytest.raises(RuntimeError, match="credential_private_lock_busy"):
                with private_file_lock(path, timeout=0):
                    pytest.fail("same path admitted a second owner")
            raise ValueError("fixture_crash")
    with private_file_lock(path, timeout=0):
        assert not path.exists()  # Lock never writes a secret or a stale PID file.
