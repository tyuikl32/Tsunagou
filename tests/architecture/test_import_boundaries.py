import importlib.util
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[2] / "tools/dev/check_architecture.py"
spec = importlib.util.spec_from_file_location("architecture_checker", CHECKER)
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("tsunagou.modules.tasks.domain.task", "from fastapi import FastAPI"),
        ("tsunagou.modules.tasks.domain.task", "from sqlalchemy.orm import Session"),
        ("tsunagou.modules.tasks.domain.task", "from ..infrastructure import repository"),
        ("tsunagou.modules.tasks.application.commands", "from tsunagou.modules.agents.infrastructure import tables"),
        ("tsunagou.api.app", "from tsunagou.modules.tasks.infrastructure import repository"),
        ("tsunagou.application.workflows.task", "from tsunagou.modules.tasks.domain import task"),
    ],
)
def test_rejects_forbidden_edges(module: str, source: str) -> None:
    assert checker.check_source(source, module)


def test_allows_pure_domain_and_public_ports() -> None:
    assert not checker.check_source(
        "from dataclasses import dataclass\nfrom tsunagou.shared_kernel import ids\nfrom . import attempt",
        "tsunagou.modules.tasks.domain.task",
    )
    assert not checker.check_source(
        "from tsunagou.modules.agents.public import AgentView",
        "tsunagou.modules.tasks.application.commands",
    )


def test_repository_import_graph() -> None:
    assert checker.check_tree(CHECKER.parents[2] / "src/tsunagou") == []
