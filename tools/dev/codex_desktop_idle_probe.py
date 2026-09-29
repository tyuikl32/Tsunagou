"""Run from an enrolled test conversation to check IPC after that turn ends.

This is a transport experiment, not the product A2A/inbox acceptance. It uses
only the calling host's inherited identity and writes no raw host identifiers.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from tsunagou.hostwake.codex_desktop import NativeAppToolsClient
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.time import format_timestamp, now_ms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    thread = os.environ["CODEX_THREAD_ID"]
    client = NativeAppToolsClient(os.environ["CODEX_APP_TOOLS_PIPE_PATH"], thread)
    record = {"started_at": format_timestamp(now_ms()), "caller_digest": canonical_digest(thread),
              "pid": os.getpid(), "status": "waiting_for_caller_idle", "sender": "detached_python_process"}

    def save() -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    def read() -> dict:
        return client.call_tool("read_thread", {"threadId": thread, "turnLimit": 1,
                                                "includeOutputs": False, "maxOutputCharsPerItem": 200})

    save()
    try:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            view = read()
            if view["thread"]["status"].get("type") in {"idle", "notLoaded"}:
                record["caller_idle_at"] = format_timestamp(now_ms())
                record["prior_turn_digest"] = canonical_digest(view["turns"][0]["id"])
                break
            time.sleep(2)
        else:
            raise TimeoutError("caller_did_not_finish")
        client.call_tool("send_message_to_thread", {
            "threadId": thread, "hostId": "local",
            "prompt": "Tsunagou FX3 idle-caller transport probe. Your previous turn has ended. "
                      "Reply with exactly FX3_IDLE_CALLER_WAKE_OK. Do not call tools or modify files.",
        })
        record.update(status="accepted", accepted_at=format_timestamp(now_ms()))
        save()
        while time.monotonic() < deadline:
            view = read()
            turn = view["turns"][0]
            if canonical_digest(turn["id"]) != record["prior_turn_digest"] and turn.get("status") == "completed":
                replies = [item.get("text", "") for item in turn.get("items", []) if item.get("type") == "agentMessage"]
                if "FX3_IDLE_CALLER_WAKE_OK" in replies:
                    record.update(status="completed", completed_at=format_timestamp(now_ms()),
                                  new_turn_digest=canonical_digest(turn["id"]), reply="FX3_IDLE_CALLER_WAKE_OK")
                    save()
                    return 0
            time.sleep(2)
        raise TimeoutError("probe_response_not_completed")
    except Exception as exc:
        record.update(status="failed", finished_at=format_timestamp(now_ms()),
                      error_code=getattr(exc, "code", type(exc).__name__))
        save()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
