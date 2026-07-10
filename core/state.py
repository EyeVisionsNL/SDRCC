#!/usr/bin/env python3

from datetime import datetime
from pathlib import Path
import json

STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

SDR2_STATE_FILE = STATE_DIR / "sdr2.json"

_UNSET = object()


DEFAULT_STATE = {
    "device": "sdr2",
    "status": "idle",
    "profile": "weather",
    "locked": False,
    "process": None,
    "updated": None,
}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_sdr2_state():
    if not SDR2_STATE_FILE.exists():
        return DEFAULT_STATE.copy()

    try:
        with open(SDR2_STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        current_state = DEFAULT_STATE.copy()
        current_state.update(data)
        return current_state

    except Exception:
        return DEFAULT_STATE.copy()


def set_sdr2_state(
    status=_UNSET,
    profile=_UNSET,
    locked=_UNSET,
    process=_UNSET,
):
    current_state = get_sdr2_state()

    if status is not _UNSET:
        current_state["status"] = status

    if profile is not _UNSET:
        current_state["profile"] = profile

    if locked is not _UNSET:
        current_state["locked"] = locked

    if process is not _UNSET:
        current_state["process"] = process

    current_state["updated"] = _now()

    with open(SDR2_STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(current_state, file, indent=2)

    return current_state


def is_sdr2_available():
    current_state = get_sdr2_state()

    return (
        current_state["status"] == "idle"
        and current_state["locked"] is False
    )


def print_sdr2_state():
    current_state = get_sdr2_state()

    print("SDR2 State")
    print("-----------------------------")
    print("Status  :", current_state["status"])
    print("Profile :", current_state["profile"])
    print("Locked  :", "YES" if current_state["locked"] else "NO")
    print("Process :", current_state["process"])
    print("Updated :", current_state["updated"])
