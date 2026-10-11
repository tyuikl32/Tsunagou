"""daemon 不能把别人改的名字覆盖掉（2026-10-11 用户实测）。

控制台改名后，daemon 下一次整份写回 `project.json` 时把启动时读到的旧名字又写了回去 ⇒ 用户看到
"改了有反应、刷新就没了"。名字是标签，改它的人不是 daemon：写盘前重读磁盘，磁盘上的名字优先。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tsunagou.modules.projects import ProjectRegistry


def test_an_external_rename_survives_the_next_manifest_write(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    registry = ProjectRegistry.initialize(root, name="大规模重测3", objective="待用户确认")
    manifest_path = registry.shared_path

    # 别人（控制台/CLI）在磁盘上把名字改了。
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["name"] = "3-F"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")

    # daemon 现在因为别的事情整份写回一次。
    registry.materialize_projection()

    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["name"] == "3-F", "外部改的名字必须活过 daemon 的写回"
    assert registry.project is not None and registry.project.name == "3-F", "内存也要跟上，之后几次写才一致"
