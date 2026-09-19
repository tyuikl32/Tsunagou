from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from tools.conformance.probes.codex import probe


def test_codex_probe_uses_explicit_writable_root_and_utf8_decode(
    tmp_path: Path, monkeypatch: Any
) -> None:
    roots: list[Path] = []

    def fake_run(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        return type("Completed", (), {"stdout": "codex-cli 0.test\n"})()

    class FakeRpc:
        def __init__(self, _executable: str, root: Path) -> None:
            assert (root / "codex-home").is_dir()
            roots.append(root)
            self.starts = 0
            self.stderr: list[str] = []

        def call(self, method: str, _params: dict[str, Any]) -> dict[str, Any]:
            if method == "initialize":
                return {"result": {}}
            if method == "thread/start":
                self.starts += 1
                return {"result": {"thread": {"id": f"thread-{self.starts}"}}}
            if method == "thread/resume":
                return {"result": {"thread": {"id": "thread-1"}}}
            if method == "thread/fork":
                return {"result": {"thread": {"id": "thread-3"}}}
            raise AssertionError(method)

        def close(self) -> None:
            return None

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(probe, "Rpc", FakeRpc)

    evidence = probe.run("codex", work_root=tmp_path)

    assert evidence["version"] == "codex-cli 0.test"
    assert evidence["checks"]["same_directory_distinct"] is True
    assert evidence["baseline"]["identity.session_isolation"] == {
        "status": "supported",
        "evidence_refs": ["initialize", "same_directory_distinct"],
    }
    assert evidence["baseline"]["task.lifecycle"] == {"status": "unknown"}
    assert evidence["checks"]["resume"]["same_identity"] is True
    assert evidence["checks"]["fork"]["same_identity"] is False
    assert roots and not roots[0].exists()
