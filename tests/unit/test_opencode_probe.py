import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.conformance.probes.opencode.probe import _baseline


def test_opencode_probe_keeps_unknown_baseline_explicit() -> None:
    result = _baseline({"identity.session_isolation": {"status": "supported", "evidence_refs": ["x"]}})
    assert result["identity.session_isolation"]["status"] == "supported"
    assert result["task.lifecycle"]["status"] == "unknown"
    assert set(result) == {
        "identity.session_isolation", "identity.continuity_evidence", "context.project_read",
        "command.typed_tools", "task.lifecycle", "cognition.report", "contract.participation",
        "inbox.pull_fetch_ack", "response.structured", "recovery.idempotent_reconnect",
        "delivery.deduplicate",
    }


def test_probe_output_is_json_serializable(tmp_path: Path) -> None:
    output = {"host": "opencode", "baseline": _baseline({}), "ready": False}
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(output), encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["ready"] is False
