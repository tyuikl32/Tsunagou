import json
from pathlib import Path


def test_pnpm_build_policy_allows_only_esbuild() -> None:
    workspace = Path(__file__).parents[2] / "pnpm-workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    policy_start = lines.index("allowBuilds:") + 1
    policy: dict[str, str] = {}
    for line in lines[policy_start:]:
        if not line.startswith("  "):
            break
        package, value = line.strip().split(":", maxsplit=1)
        policy[package] = value.strip()

    assert policy == {"esbuild": "true"}


def test_root_check_runs_each_workspace_package_check() -> None:
    root = Path(__file__).parents[2]
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    tsconfig = json.loads((root / "tsconfig.base.json").read_text(encoding="utf-8"))
    workspace_packages = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / "packages").glob("*/package.json"))
    ]

    assert package["scripts"]["check"] == "corepack pnpm -r run check"
    assert workspace_packages
    assert all(workspace_package.get("scripts", {}).get("check") for workspace_package in workspace_packages)
    assert "composite" not in tsconfig["compilerOptions"]
