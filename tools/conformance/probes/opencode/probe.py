from __future__ import annotations

import shutil
from pathlib import Path

from tools.conformance.probes.common import write_evidence


def main(output: Path) -> None:
    executable = shutil.which("opencode")
    write_evidence(output, {
        "host": "opencode",
        "status": "unknown",
        "checks": {},
        "reason": "executable_not_found" if not executable else "probe_not_yet_implemented",
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.output)
