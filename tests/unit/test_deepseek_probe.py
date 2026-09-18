import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.conformance.probes.deepseek.probe import _baseline


def test_deepseek_probe_keeps_all_unknown_baseline_rows() -> None:
    result = _baseline({"identity.session_isolation": {"status": "supported", "evidence_refs": ["x"]}})
    assert result["identity.session_isolation"]["status"] == "supported"
    assert result["delivery.deduplicate"]["status"] == "unknown"
    assert len(result) == 11


def test_deepseek_evidence_shape_is_json_serializable(tmp_path: Path) -> None:
    path = tmp_path / "deepseek.json"
    path.write_text(json.dumps({"baseline": _baseline({}), "ready": False}), encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["ready"] is False
