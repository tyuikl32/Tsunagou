"""Actual Windows Job close versus detached daemon; no desktop restart is simulated."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest


def _run_inside_job(root: Path, report: Path, scenario: str) -> None:
    """Disposable process owns the Job's only handle; exiting kills its members."""
    import ctypes
    import importlib
    from ctypes import wintypes
    from datetime import UTC, datetime

    from typer.testing import CliRunner

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(key, ctypes.c_uint64) for key in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    def own_job(allow_breakaway):
        job = kernel.CreateJobObjectW(None, None)
        assert job, ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimit()
        # These policies are on our own disposable Job, never on a host/sandbox Job.
        limits.BasicLimitInformation.LimitFlags = 0x2000 | (0x800 if allow_breakaway else 0)
        assert kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)), ctypes.WinError(ctypes.get_last_error())
        assert kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()), ctypes.WinError(ctypes.get_last_error())
        return job

    outer = own_job(False) if scenario == "nested_denied" else None
    job = own_job(scenario != "denied")
    cli_module = importlib.import_module("tsunagou.cli.app")
    if scenario == "legacy":
        original = subprocess.Popen

        def old_flags(*args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) & ~subprocess.CREATE_BREAKAWAY_FROM_JOB
            return original(*args, **kwargs)

        subprocess.Popen = old_flags
    started_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    result = CliRunner().invoke(cli_module.app, ["--project-root", str(root), "daemon", "start", "--host-wake", "disabled"])
    report.write_text(json.dumps({"scenario": scenario, "started_at": started_at,
                                 "finished_at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                                 "exit_code": result.exit_code, "output": result.output}), encoding="utf-8")
    # Close the final handle: helper and inherited children die. The new daemon
    # must continue serving HTTP after this process has actually exited.
    kernel.CloseHandle(outer or job)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job object and process creation flags")
@pytest.mark.parametrize("scenario", ["legacy", "detached", "denied", "nested_denied"])
def test_daemon_parent_job_exit(tmp_path: Path, scenario: str) -> None:
    import importlib

    cli_module = importlib.import_module("tsunagou.cli.app")
    root = tmp_path / "project"
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    report = tmp_path / "job-result.json"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("TSUNAGOU_", "CODEX_"))}
    # The child starts from a clean TSUNAGOU_ slate on purpose. The machine-level project
    # index is not what this test exercises, and without keeping its override the child
    # registers a throwaway project in the developer's own ~/.tsunagou/projects.json.
    if os.environ.get("TSUNAGOU_PROJECT_INDEX"):
        env["TSUNAGOU_PROJECT_INDEX"] = os.environ["TSUNAGOU_PROJECT_INDEX"]
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--job-helper", str(root), str(report), scenario],
                            env=env, capture_output=True, text=True, timeout=40,
                            creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.CREATE_NO_WINDOW)
    assert report.is_file(), result.stderr or result.stdout
    recorded = json.loads(report.read_text(encoding="utf-8"))
    outcome = json.loads(recorded["output"])
    if scenario == "denied":
        assert recorded["exit_code"] == 1, recorded
        assert outcome["error"] == "daemon_launch_failed" and outcome["os_error"] == 5
        assert not (root / ".tsunagou/local/endpoint.json").exists()
        return
    assert recorded["exit_code"] == 0, recorded
    if scenario in {"legacy", "nested_denied"}:
        # nested_denied documents a Windows limitation, NOT a passed O2 case:
        # leaving the inner Job cannot override an outer Job's prohibition.
        assert not cli_module._daemon_process_running(outcome["pid"])
        return
    try:
        assert cli_module._daemon_process_running(outcome["pid"])
        with urllib.request.urlopen(outcome["url"] + "/api/v1/health", timeout=5) as response:
            health = json.load(response)
        assert health["runtime"]["pid"] == outcome["pid"]
        assert health["runtime"]["runtime_id"] == outcome["runtime_id"]
        assert outcome["project_id"] in health["runtime"]["project_ids"]
    finally:
        stopped = subprocess.run([sys.executable, "-m", "tsunagou", "--project-root", str(root), "daemon", "stop"],
                                 env=env, capture_output=True, text=True, timeout=20)
        assert stopped.returncode == 0, stopped.stdout or stopped.stderr
        assert json.loads(stopped.stdout)["status"] == "stopped"
    repeated = subprocess.run([sys.executable, "-m", "tsunagou", "--project-root", str(root), "daemon", "stop"],
                              env=env, capture_output=True, text=True, timeout=20)
    assert repeated.returncode == 0, repeated.stdout or repeated.stderr
    assert json.loads(repeated.stdout)["status"] == "already_stopped"
    assert (root / ".tsunagou/local/endpoint.json").exists()
    assert (root / ".tsunagou/local/daemon-projects.json").exists()


if __name__ == "__main__" and sys.argv[1] == "--job-helper":
    _run_inside_job(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
