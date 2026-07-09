#!/usr/bin/env python3

from datetime import datetime
from pathlib import Path
import json

STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

SDR2_STATE_FILE = STATE_DIR / "sdr2.json"


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

        state = DEFAULT_STATE.copy()
        state.update(data)
        return state

    except Exception:
        return DEFAULT_STATE.copy()


def set_sdr2_state(status=None, profile=None, locked=None, process=None):
    state = get_sdr2_state()

    if status is not None:
        state["status"] = status

    if profile is not None:
        state["profile"] = profile

    if locked is not None:
        state["locked"] = locked

    if process is not None:
        state["process"] = process

    state["updated"] = _now()

    with open(SDR2_STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    return state


def is_sdr2_available():
    state = get_sdr2_state()
    return state["status"] == "idle" and state["locked"] is False


def print_sdr2_state():
    state = get_sdr2_state()

    print("SDR2 State")
    print("-----------------------------")
    print("Status  :", state["status"])
    print("Profile :", state["profile"])
    print("Locked  :", "YES" if state["locked"] else "NO")
    print("Process :", state["process"])
    print("Updated :", state["updated"])
