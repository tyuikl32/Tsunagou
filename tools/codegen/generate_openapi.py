from __future__ import annotations

import json
from pathlib import Path

from tsunagou.api.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    output = ROOT / "protocol" / "openapi.json"
    content = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.write_text(content, encoding="utf-8")
    (ROOT / "src/tsunagou/protocol_data/openapi.json").write_text(content, encoding="utf-8")
    print(f"generated {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
