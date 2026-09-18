from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from tools.conformance.probes.common import BASELINE, write_evidence


def main(output: Path) -> None:
    executable = shutil.which("zcode")
    evidence = {
        "host": "zcode",
        "version": "unknown",
        "scope": "no_live_host",
        "checks": {},
        "reason": "executable_not_found" if not executable else "probe_not_yet_implemented",
        "baseline": {name: {"status": "unknown"} for name in BASELINE},
        "ready": False,
    }
    write_evidence(output, evidence)
    print(json.dumps(evidence))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.output)
