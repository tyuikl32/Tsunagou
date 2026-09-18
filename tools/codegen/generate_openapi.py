from __future__ import annotations

import json
from pathlib import Path

from tsunagou.api.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    output = ROOT / "protocol" / "openapi.json"
    output.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"generated {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
