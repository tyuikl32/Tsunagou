"""Suite-wide guards for a test run that touches the real machine.

Some tests deliberately drive the *real* CLI and the *real* console
(``project init``, ``daemon start``), and those commands register the project in
the machine-level index at ``~/.tsunagou/projects.json``. Nothing redirected that
path, so every run left one permanent line per temporary project. One developer
machine ended up with **260** identical ``Tsunagou project`` entries pointing at
``pytest-of-*/`` folders, and the console dutifully listed all of them.

The index is a convenience cache, never a source of truth — each project's own
``.tsunagou/project.json`` stays authoritative, and the console also discovers
projects by scanning its roots. Pointing it at a throwaway file therefore costs
the tests nothing and keeps the machine's real list honest.

``TSUNAGOU_PROJECT_INDEX`` is the documented override (see
``tsunagou.platform.project_index``); anything that writes the index inherits it,
including daemon processes the tests start.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_machine_index(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Keep this run's project registrations out of the user's home directory."""

    index = tmp_path_factory.mktemp("machine-index") / "projects.json"
    previous = os.environ.get("TSUNAGOU_PROJECT_INDEX")
    os.environ["TSUNAGOU_PROJECT_INDEX"] = str(index)
    try:
        yield index
    finally:
        if previous is None:
            os.environ.pop("TSUNAGOU_PROJECT_INDEX", None)
        else:
            os.environ["TSUNAGOU_PROJECT_INDEX"] = previous


def test_guard_the_suite_never_registers_into_the_real_index(isolated_machine_index: Path) -> None:
    """The guard itself is load-bearing: without it the machine list grows forever.

    A test that drives the CLI would otherwise append a line to the user's own
    ``~/.tsunagou/projects.json`` for a folder that is deleted as soon as the test
    ends — a project nobody can open and nothing can clean up automatically.
    """

    from tsunagou.platform.project_index import index_path

    assert Path(os.environ["TSUNAGOU_PROJECT_INDEX"]) == isolated_machine_index
    assert index_path() == isolated_machine_index
    assert index_path() != Path.home() / ".tsunagou" / "projects.json"
