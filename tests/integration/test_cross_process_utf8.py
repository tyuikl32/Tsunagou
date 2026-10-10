"""Cross-process JSON pipes are UTF-8 on both ends — the Windows locale is not the codec.

The recorded defect (待改 21): a parent parses JSON a **child process** printed into a
captured pipe, and Windows decodes it with the locale codec (cp936/GBK here). It fails
in both directions — a Node child printing UTF-8 gives the parent
``UnicodeDecodeError: 'gbk' codec`` inside the reader thread and ``stdout is None``, so
the caller dies on ``json.loads(None)``; a Python child printing GBK gives a parent
reading UTF-8 mojibake.

The product rule this file pins down: **every cross-process JSON pipe in this project is
UTF-8, explicitly, on both ends. Never rely on the locale codec.** The callers' own
values — a Chinese ``roots[].name``, a Chinese ``contracts.accepted[].subject_ref``, a
confirmed ``goal.objective`` — are legitimate and must survive the pipe byte-for-byte.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node") or "node"
#: The parent's codec in the recorded failure. The fix must not depend on it.
LOCALE = "cp936"


def _stdout(completed: subprocess.CompletedProcess[str], *, what: str) -> str:
    """A ``None``/empty stdout means the reader thread died — say what really happened.

    The recorded symptom was ``TypeError: the JSON object must be str, bytes or
    bytearray, not NoneType``, which names neither the child nor the decode failure.
    """

    assert completed.stdout, (
        f"{what}: the child's stdout came back as {completed.stdout!r} "
        f"(returncode={completed.returncode}); its stderr was "
        f"{(completed.stderr or '<empty>').strip()[:600]!r}"
    )
    return completed.stdout


def _json_stdout(completed: subprocess.CompletedProcess[str], *, what: str) -> object:
    return json.loads(_stdout(completed, what=what))


def _utf8_pipe(cwd: Path) -> dict[str, str]:
    """An environment whose own default text codec is the locale, not UTF-8.

    ``PYTHONIOENCODING`` is what a real Windows parent hands a Python child by default,
    so a child that never pins UTF-8 writes the locale codec's bytes into the pipe.
    """

    env = {key: value for key, value in os.environ.items() if not key.startswith("TSUNAGOU_")}
    if os.environ.get("TSUNAGOU_PROJECT_INDEX"):
        env["TSUNAGOU_PROJECT_INDEX"] = os.environ["TSUNAGOU_PROJECT_INDEX"]
    env["PYTHONIOENCODING"] = LOCALE
    env["PYTHONPATH"] = os.pathsep.join([str(cwd), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return env


def _init_git_repository(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)


def test_a_node_child_prints_utf8_and_python_reads_it_back(tmp_path: Path) -> None:
    """The Node case: ``text=True`` alone decodes UTF-8 JSON with GBK and yields ``None``."""

    name = "中文根名"
    payload = json.dumps({"name": name}, ensure_ascii=False)

    broken = subprocess.run(
        [NODE, "-e", f"console.log({json.dumps(payload)})"],
        capture_output=True, text=True, timeout=60,
    )
    assert broken.returncode == 0, broken.stderr
    assert broken.stdout is None or json.loads(broken.stdout) != {"name": name}, (
        "without an explicit encoding the Node child's UTF-8 must not survive the pipe; "
        f"got stdout={broken.stdout!r} stderr={(broken.stderr or '').strip()[:400]!r}"
    )

    completed = subprocess.run(
        [NODE, "-e", f"console.log({json.dumps(payload)})"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert _json_stdout(completed, what="Node child's JSON") == {"name": name}


def test_the_cli_round_trips_a_caller_supplied_chinese_value(tmp_path: Path) -> None:
    """The real product path: a Chinese coordination root passes through the CLI's pipe.

    ``project bootstrap --json`` prints ``json.dumps(..., ensure_ascii=False)`` and echoes
    the caller's own coordination root back, so this is a caller-supplied Chinese value
    reaching real CLI output — the exact thing the locale codec used to restrict.
    """

    root = tmp_path / "中文 项目 根"
    _init_git_repository(root)

    def cli(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "tsunagou", "--json", *args],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=_utf8_pipe(tmp_path), timeout=120,
        )

    initialized = _json_stdout(
        cli("project", "init", "--coordination-root", str(root), "--name", "中文项目"),
        what="project init",
    )
    assert isinstance(initialized, dict) and initialized["status"] == "active"

    completed = cli(
        "project", "bootstrap", "--coordination-root", str(root),
        "--source-root", str(ROOT), "--host", "generic",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = _json_stdout(completed, what="project bootstrap")
    assert isinstance(result, dict)
    assert result["coordination_root"] == str(root), "调用方给的路径要逐字节读得回来"
    assert result["project_id"] == initialized["project_id"]

    # The pipe really carried UTF-8 bytes: ``ensure_ascii=False`` on the CLI side is what
    # makes this reachable, and reading those bytes as the locale codec is what broke.
    raw = subprocess.run(
        [sys.executable, "-m", "tsunagou", "--json", "project", "bootstrap",
         "--coordination-root", str(root), "--source-root", str(ROOT), "--host", "generic"],
        cwd=ROOT, capture_output=True, env=_utf8_pipe(tmp_path), timeout=120,
    )
    assert raw.returncode == 0, raw.stderr.decode("utf-8", "replace")
    assert "中文 项目 根".encode() in raw.stdout, "CLI 的 stdout 必须是 UTF-8 字节"
    assert json.loads(raw.stdout.decode("utf-8"))["coordination_root"] == str(root)


def test_the_cli_pins_its_stdio_instead_of_using_the_locale_codec(tmp_path: Path) -> None:
    """Write side: with a locale codec handed in, the CLI still writes UTF-8 bytes.

    A Python process whose ``PYTHONIOENCODING`` is the locale codec writes
    ``json.dumps(..., ensure_ascii=False)`` as GBK bytes — exactly the second direction of
    the defect, and what the entry-point pin exists to prevent. The broken control is the
    same CLI with the pin call removed from its entry point, run from a throwaway tree, so
    "without the pin" is a run and not a claim (and it keeps working after this fix is
    committed, unlike a control pinned to ``git show HEAD``).
    """

    pin_call = "        _pin_stdio_utf8()\n        app()"
    current = (ROOT / "src/tsunagou/cli/app.py").read_text(encoding="utf-8")
    assert pin_call in current, "the CLI entry must pin stdio before it runs the app"
    pinless = current.replace(pin_call, "        app()")
    assert pinless != current

    tree = tmp_path / "unpinned-tree"
    shutil.copytree(ROOT / "src/tsunagou", tree / "tsunagou")
    (tree / "tsunagou" / "__main__.py").write_text(
        pinless + "\n\nif __name__ == \"__main__\":\n    sys.exit(main())\n", encoding="utf-8",
    )

    root = tmp_path / "中文 项目 根"
    _init_git_repository(root)
    # ``project init`` is ASCII-only output; ``project bootstrap --json`` is the command
    # that echoes the caller's Chinese coordination root back through the pipe.
    init_args = [
        "tsunagou", "--json", "--project-root", str(root),
        "project", "init", "--coordination-root", str(root), "--name", "中文项目",
    ]
    bootstrap_args = [
        "tsunagou", "--json", "project", "bootstrap", "--coordination-root", str(root),
        "--source-root", str(ROOT), "--host", "generic",
    ]

    def run_the_cli(pythonpath: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
        env = _utf8_pipe(pythonpath)
        env["PYTHONPATH"] = os.pathsep.join([str(pythonpath), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        return subprocess.run(
            [sys.executable, "-m", *args], cwd=ROOT, capture_output=True, env=env, timeout=120,
        )

    broken = run_the_cli(tree, init_args)
    assert broken.returncode == 0, broken.stderr.decode(LOCALE, "replace")[:600]
    broken = run_the_cli(tree, bootstrap_args)
    assert broken.returncode == 0, broken.stderr.decode(LOCALE, "replace")[:600]
    assert "中文 项目 根".encode() not in broken.stdout, (
        "the control is only useful while the locale codec really is in the pipe: "
        f"stdout={broken.stdout[:200]!r}"
    )
    assert "中文 项目 根".encode(LOCALE) in broken.stdout, (
        "the pre-fix CLI must write the locale codec's bytes: "
        f"stdout={broken.stdout[:200]!r}"
    )
    with pytest.raises(UnicodeDecodeError):
        broken.stdout.decode("utf-8")

    fixed = run_the_cli(ROOT / "src", init_args)
    assert fixed.returncode == 0, fixed.stderr.decode("utf-8", "replace")[:600]
    fixed = run_the_cli(ROOT / "src", bootstrap_args)
    assert fixed.returncode == 0, fixed.stderr.decode("utf-8", "replace")[:600]
    assert "中文 项目 根".encode() in fixed.stdout, (
        "the CLI entry must pin stdout to UTF-8 so a locale-codec parent cannot corrupt it: "
        f"stdout={fixed.stdout[:200]!r}"
    )
    reported = json.loads(fixed.stdout.decode("utf-8"))
    assert reported["status"] == "bootstrapped" and reported["coordination_root"] == str(root)
