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


@pytest.fixture(autouse=True)
def isolated_enrollment_store(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep this test's pending enrollment out of the user's home directory.

    The machine-level enrollment record (``~/.tsunagou/console-enrollments``) is the one
    answer to "which project and role should this chat join", and there is exactly **one**
    of them per OS user. Tests that drive the console or the CLI write it, so without this
    guard two things happen: a record left pending by one test makes the next one fail with
    ``enrollment_already_pending``, and the user's machine ends up claiming that somebody is
    waiting to join a project that was deleted with the test's temporary folder.

    Scoped per test rather than per run: a test that deliberately leaves a pending record
    (the cross-machine flow does) must not be able to block the next one.
    """

    directory = tmp_path_factory.mktemp("console-enrollments")
    monkeypatch.setenv("TSUNAGOU_ENROLLMENT_DIR", str(directory))
    return directory


def test_guard_the_suite_never_writes_the_real_enrollment_store(isolated_enrollment_store: Path) -> None:
    """同样这条守卫也是承重的：记录属于"这台机器"，测试不该在那上面留痕。"""

    from tsunagou.platform.enrollment_store import EnrollmentStore

    assert Path(os.environ["TSUNAGOU_ENROLLMENT_DIR"]) == isolated_enrollment_store
    assert EnrollmentStore().directory == isolated_enrollment_store
    assert EnrollmentStore().directory != Path.home() / ".tsunagou" / "console-enrollments"
