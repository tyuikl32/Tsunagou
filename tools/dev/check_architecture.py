from __future__ import annotations

from pathlib import Path

FORBIDDEN = ("fastapi", "sqlalchemy", "typer", "uvicorn")


def check_source(source: str, module: str) -> bool:
    """Return whether an import string violates the project layer boundary."""
    if ".domain." in module and (
        any(f"import {name}" in source or f"from {name}" in source for name in FORBIDDEN)
        or "from ..infrastructure" in source
    ):
        return True
    if ".application." in module and ".infrastructure" in source:
        return True
    if module.startswith("tsunagou.api.") and ".infrastructure" in source:
        return True
    if ".application.workflows." in module and ".domain" in source:
        return True
    return False


def check_tree(root: Path) -> list[str]:
    violations: list[str] = []
    for path in root.rglob("*.py"):
        module = ".".join(path.relative_to(root).with_suffix("").parts)
        source = path.read_text(encoding="utf-8")
        if check_source(source, module):
            violations.append(str(path))
    return violations


def main() -> int:
    root = Path(__file__).resolve().parents[2] / "src" / "tsunagou"
    violations: list[str] = []
    modules = root / "modules"
    for path in modules.rglob("*.py") if modules.exists() else []:
        if "domain" not in path.parts:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for name in FORBIDDEN:
            if f"import {name}" in text or f"from {name}" in text:
                violations.append(f"{path}: domain imports {name}")
    if violations:
        print("architecture check failed")
        print("\n".join(violations))
        return 1
    print("architecture check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
