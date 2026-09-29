"""The machine-level project index is a merge, not an overwrite."""

from __future__ import annotations

import json
from pathlib import Path

from tsunagou.platform.project_index import load_index, record_project


def test_recording_a_project_twice_updates_it_instead_of_duplicating(tmp_path: Path) -> None:
    index = tmp_path / "projects.json"
    first = record_project(
        project_id="p-1", path=tmp_path / "one", name="One", objective="first", index=index, now=1_000,
    )
    again = record_project(project_id="p-1", path=tmp_path / "one", source="console", index=index, now=2_000)

    assert again["created_at"] == first["created_at"]
    assert again["updated_at"] != first["updated_at"]
    assert again["sources"] == ["cli", "console"]
    stored = json.loads(index.read_text(encoding="utf-8"))
    assert [item["project_id"] for item in stored["projects"]] == ["p-1"]
    assert stored["projects"][0]["path"] == (tmp_path / "one").as_posix()


def test_a_thin_record_does_not_erase_what_an_earlier_caller_knew(tmp_path: Path) -> None:
    index = tmp_path / "projects.json"
    record_project(project_id="p-1", path=tmp_path / "one", name="One", objective="first", index=index, now=1_000)
    entry = record_project(project_id="p-1", path=tmp_path / "one", source="console", index=index, now=2_000)
    assert entry["name"] == "One"
    assert entry["objective"] == "first"


def test_a_damaged_index_is_rebuilt_rather_than_trusted(tmp_path: Path) -> None:
    index = tmp_path / "projects.json"
    index.write_text("{not json at all", encoding="utf-8")
    assert load_index(index)["projects"] == []

    record_project(project_id="p-2", path=tmp_path / "two", index=index, now=1_000)
    assert [item["project_id"] for item in load_index(index)["projects"]] == ["p-2"]


def test_a_missing_index_is_an_empty_list(tmp_path: Path) -> None:
    assert load_index(tmp_path / "absent.json")["projects"] == []
