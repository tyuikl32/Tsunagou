"""Validate planning documents and Trellis context without product dependencies."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    errors: list[str] = []
    checked_links = 0
    manifest = json.loads((ROOT / "docs/history/source-manifest.json").read_text(encoding="utf-8"))
    for entry in manifest:
        path = ROOT / entry["archive_path"]
        if not path.is_file():
            errors.append(f"Missing archived source: {path}")
            continue
        raw = path.read_bytes()
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            errors.append(f"Archived source changed: {path}")

    markdown = [ROOT / "README.md", ROOT / "AGENTS.md"]
    for folder in ["docs", ".trellis/spec", ".trellis/tasks"]:
        markdown.extend((ROOT / folder).rglob("*.md"))
    link_re = re.compile(r"(?<!!)\[[^\]\n]+\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")
    for path in markdown:
        text = path.read_text(encoding="utf-8")
        # Literal examples in code fences do not define navigation links.
        prose = re.sub(r"```.*?```", "", text, flags=re.S)
        for match in link_re.finditer(prose):
            href = match.group(1).strip("<>")
            if href.startswith("#") or urlsplit(href).scheme:
                continue
            target = unquote(href.split("#", 1)[0].split("?", 1)[0])
            checked_links += 1
            if target and not (path.parent / target).resolve().exists():
                errors.append(f"Broken link: {path.relative_to(ROOT)} -> {href}")
        if ".trellis/spec" in path.as_posix():
            for marker in ["To fill", "To be filled", "TODO: fill", "Fill in each file"]:
                if marker in text:
                    errors.append(f"Unfilled template {marker!r}: {path}")

    plan = json.loads((ROOT / "docs/implementation/task-plan.json").read_text(encoding="utf-8"))
    tasks = {t["id"]: t for t in plan["tasks"]}
    if len(tasks) != len(plan["tasks"]):
        errors.append("Duplicate stable task IDs")
    state: dict[str, int] = {}

    def visit(task_id: str) -> None:
        if state.get(task_id) == 1:
            errors.append(f"Dependency cycle at {task_id}")
            return
        if state.get(task_id) == 2:
            return
        state[task_id] = 1
        for dependency in tasks[task_id]["depends_on"]:
            if dependency not in tasks:
                errors.append(f"Unknown dependency {dependency} in {task_id}")
            else:
                visit(dependency)
        state[task_id] = 2

    for task_id in tasks:
        visit(task_id)

    parent_path = ROOT / plan["parent_task"] / "task.json"
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    for task_id, task in tasks.items():
        folder = ROOT / task["trellis_path"]
        for name in ["task.json", "prd.md", "design.md", "implement.md", "implement.jsonl", "check.jsonl"]:
            if not (folder / name).is_file():
                errors.append(f"Missing {task_id} artifact: {name}")
        if not (folder / "task.json").is_file():
            continue
        metadata = json.loads((folder / "task.json").read_text(encoding="utf-8"))
        if metadata.get("meta", {}).get("plan_id") != task_id:
            errors.append(f"Wrong stable plan_id for {task_id}")
        if metadata.get("meta", {}).get("depends_on") != task["depends_on"]:
            errors.append(f"Dependency metadata drift for {task_id}")
        if metadata.get("assignee") != plan["developer"]:
            errors.append(f"Unexpected task assignee: {task_id}")
        if folder.name not in parent.get("children", []):
            errors.append(f"Parent misses child {task_id}")
        if metadata.get("parent") != parent_path.parent.name:
            errors.append(f"Wrong parent for {task_id}: {metadata.get('parent')}")
        for spec in task["specs"]:
            if not (ROOT / spec).is_file():
                errors.append(f"Missing specification for {task_id}: {spec}")

    context_count = 0
    for path in (ROOT / ".trellis/tasks").rglob("*.jsonl"):
        if path.name not in {"implement.jsonl", "check.jsonl"}:
            continue
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            errors.append(f"Empty task context: {path.relative_to(ROOT)}")
        for number, line in enumerate(lines, 1):
            context_count += 1
            try:
                item = json.loads(line)
                if not item.get("reason") or not (ROOT / item["file"]).is_file():
                    errors.append(f"Invalid context entry: {path.relative_to(ROOT)}:{number}")
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(f"Invalid JSONL: {path.relative_to(ROOT)}:{number}: {exc}")

    decisions = (ROOT / "docs/decisions/2026-09-18-boundary-decisions.md").read_text(encoding="utf-8")
    for number in range(161, 183):
        if not re.search(rf"\bD{number}\b", decisions):
            errors.append(f"Missing persisted decision D{number}")

    if errors:
        print("Planning validation FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"PASS: {len(manifest)} unchanged archived sources; {len(markdown)} Markdown files; "
          f"{checked_links} local links; {len(tasks)} implementation tasks; "
          f"{context_count} context entries; acyclic dependencies; D161-D182 present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
