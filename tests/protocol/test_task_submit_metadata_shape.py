"""`task.submit` 的 validation_metadata 必须能被模型**短**地写出来。

2026-10-07 实测：每一条 7 个必填（started_at / finished_at / command / exit_code / tool /
tool_version / workspace_digest）、最多 100 条 —— 模型为了交一次活要吐一大段密 JSON，
DSH 侧因此报 "tool input is invalid JSON"（MALFORMED_RESPONSE）并**直接终止会话**，
协作进度整段丢掉。

所以这里把"能短"钉住：每条最多两个必填，且 `command` 必须在其中（没有命令的验证记录没有意义）。
其余字段**仍然可选存在** —— 降的是必填门槛，不是删能力。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCHEMA = ROOT / "protocol" / "schemas" / "commands" / "task" / "submit.schema.json"


def _required() -> list[str]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return list(schema["properties"]["validation_metadata"]["items"]["required"])


def test_validation_metadata_asks_for_no_more_than_two_required_fields() -> None:
    required = _required()
    assert "command" in required, "没有命令的验证记录没有意义"
    assert len(required) <= 2, (
        f"必填太多（{required}）：模型要写长 JSON，宿主解析一崩整段会话就没了"
    )


def test_the_optional_evidence_fields_are_still_accepted() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    properties = schema["properties"]["validation_metadata"]["items"]["properties"]
    for field in ("started_at", "finished_at", "tool", "tool_version", "workspace_digest",
                  "stdout_digest", "stderr_digest", "evidence_level"):
        assert field in properties, f"{field} 仍应可选存在（降门槛不是删能力）"
