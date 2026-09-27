from pathlib import Path

import pytest

from tsunagou.platform.private_file_lock import private_file_lock


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
