#!/usr/bin/env python3
"""Disable FlexGround boot autostart without stopping the running dashboard."""
from __future__ import annotations

import json
import subprocess


SERVICE = "sdrcc.service"
SYSTEMCTL = "/usr/bin/systemctl"
SAFE_DISABLED_STATES = {"disabled", "masked"}


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=30, check=False)


def disable_self_autostart(run=_run) -> dict:
    loaded = run([SYSTEMCTL, "show", SERVICE, "--property=LoadState", "--value"])
    load_state = (loaded.stdout or "").strip()
    if loaded.returncode != 0 or load_state in {"", "not-found"}:
        return {"ok": False, "message": f"Service unit not found: {SERVICE}"}

    changed = run([SYSTEMCTL, "disable", SERVICE])
    observed = run([SYSTEMCTL, "is-enabled", SERVICE])
    enabled_state = (observed.stdout or "").strip() or "unknown"
    ok = changed.returncode == 0 and enabled_state in SAFE_DISABLED_STATES
    detail = (changed.stderr or changed.stdout or "").strip()
    return {
        "ok": ok,
        "message": (
            "FlexGround is disabled at boot. The running dashboard was not stopped."
            if ok else detail or "Unable to verify disabled FlexGround autostart state."
        ),
        "load_state": load_state,
        "enabled_state": enabled_state,
        "runtime_state_changed": False,
    }


def main() -> int:
    payload = disable_self_autostart()
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
