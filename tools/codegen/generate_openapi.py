from __future__ import annotations

import json
from pathlib import Path

from tsunagou.api.app import create_app
from tsunagou.bootstrap.daemon import ProjectDaemon

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    output = ROOT / "protocol" / "openapi.json"
    schema = create_app().openapi()
    # Schema construction has no filesystem/startup effects. The outer daemon
    # owns local registration; child apps continue to own all project routes.
    control = ProjectDaemon({"TSUNAGOU_STATE_DIR": ".", "TSUNAGOU_PROJECT_ROOT": ".",
                             "TSUNAGOU_CONTROL_TOKEN": ""}).control.openapi()
    schema["paths"]["/api/v1/daemon/projects"] = control["paths"]["/api/v1/daemon/projects"]
    schema["components"]["schemas"].update(control["components"]["schemas"])
    for path, operations in schema["paths"].items():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            if path not in {"/api/v1/health", "/api/v1/daemon/projects"}:
                operation.setdefault("parameters", []).append({
                    "name": "Tsunagou-Project-Id", "in": "header", "required": False,
                    "schema": {"type": "string"},
                    "description": ("Required for paths without a project ID when this daemon serves multiple projects. "
                                    "Must match the URL ID."),
                })
    content = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.write_text(content, encoding="utf-8")
    (ROOT / "src/tsunagou/protocol_data/openapi.json").write_text(content, encoding="utf-8")
    print(f"generated {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
