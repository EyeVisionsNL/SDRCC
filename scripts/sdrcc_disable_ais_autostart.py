#!/usr/bin/env python3
"""Disable boot autostart for the exact AIS services managed by FlexGround."""
from __future__ import annotations

import json
import subprocess


SERVICES = ("ais-catcher.service", "ais-catcher-control.service")
SAFE_DISABLED_STATES = {"disabled", "masked"}
SYSTEMCTL = "/usr/bin/systemctl"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=30, check=False)


def disable_ais_autostart(run=_run) -> dict:
    load_states = {}
    for service in SERVICES:
        observed = run([SYSTEMCTL, "show", service, "--property=LoadState", "--value"])
        load_state = (observed.stdout or "").strip()
        load_states[service] = load_state or "unknown"
        if observed.returncode != 0 or load_state in {"", "not-found"}:
            return {
                "ok": False,
                "message": f"Service unit not found: {service}",
                "load_states": load_states,
            }

    changed = run([SYSTEMCTL, "disable", *SERVICES])
    enabled_states = {}
    for service in SERVICES:
        observed = run([SYSTEMCTL, "is-enabled", service])
        enabled_states[service] = (observed.stdout or "").strip() or "unknown"

    ok = changed.returncode == 0 and all(
        state in SAFE_DISABLED_STATES for state in enabled_states.values()
    )
    detail = (changed.stderr or changed.stdout or "").strip()
    return {
        "ok": ok,
        "message": (
            "AIS-Catcher and Control are disabled at boot. Running services were not stopped."
            if ok else detail or "Unable to verify disabled AIS autostart state."
        ),
        "load_states": load_states,
        "enabled_states": enabled_states,
        "runtime_state_changed": False,
    }


def main() -> int:
    payload = disable_ais_autostart()
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
