"""User-facing offline migration stays explicit and never prints old secrets."""

import json
from pathlib import Path

from tests.unit.test_credential_migration import SECRET, TICKET, _legacy
from typer.testing import CliRunner

from tsunagou.cli.app import app


def test_migration_cli_preview_confirm_and_live_writer_refusal(tmp_path: Path) -> None:
    db, migration = _legacy(tmp_path)
    runner = CliRunner()
    arguments = ["daemon", "migrate-credentials", "--coordination-root", str(tmp_path)]
    preview = runner.invoke(app, arguments + ["--dry-run"])
    assert preview.exit_code == 0, preview.output
    plan = json.loads(preview.output)
    assert plan["status"] == "preview" and not migration.marker.exists()
    confirm = arguments + ["--confirm-plan-digest", plan["plan_digest"]]
    db.acquire_process_lock()
    try:
        busy = runner.invoke(app, confirm)
        assert busy.exit_code == 4 and json.loads(busy.output)["status"] == "error"
    finally:
        db.release_process_lock()
    applied = runner.invoke(app, confirm)
    assert applied.exit_code == 0, applied.output
    report = json.loads(applied.output)
    assert report["status"] == "completed"
    assert report["completed_at"].endswith("Z")
    assert report["recovery_action"] == "enroll_and_appoint_again"
    replay = runner.invoke(app, confirm)
    assert replay.exit_code == 0 and json.loads(replay.output) == report
    for result in (preview, busy, applied, replay):
        assert SECRET not in result.output and TICKET not in result.output


def test_migration_cli_requires_same_plan_and_rejects_ambiguous_flags(tmp_path: Path) -> None:
    _, migration = _legacy(tmp_path)
    runner = CliRunner()
    arguments = ["daemon", "migrate-credentials", "--coordination-root", str(tmp_path)]
    changed = runner.invoke(app, arguments + ["--confirm-plan-digest", "sha256:incorrect"])
    assert changed.exit_code == 4
    assert json.loads(changed.output)["code"] == "migration_plan_changed"
    ambiguous = runner.invoke(app, arguments + ["--dry-run", "--confirm-plan-digest", "sha256:incorrect"])
    assert ambiguous.exit_code == 2
    assert not migration.marker.exists()
