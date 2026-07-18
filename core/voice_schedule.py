#!/usr/bin/env python3

"""Persistent operator planning for ISS Voice recordings.

This module only stores and validates recording intentions. Execution is
introduced in a later version after the planner UI has been accepted.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core import config as config_core
from core import mission_queue
from core import weather_planning

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "state" / "voice_schedule.json"


def _load() -> dict[str, dict[str, Any]]:
    if not STATE_FILE.exists():
        return {}
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save(items: dict[str, dict[str, Any]]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_FILE)


def _voice_passes(hours_ahead: int = 48) -> list[dict[str, Any]]:
    minimum = float(weather_planning.get_config().get("minimum_elevation", 40.0))
    queue = mission_queue.get_payload(limit=100, hours_ahead=hours_ahead).get("queue", [])
    return [
        item for item in queue
        if str(item.get("mission_type") or "").upper() == "VOICE"
        and not item.get("skipped")
        and float(item.get("max_elevation") or 0.0) >= minimum
    ]


def _find_pass(queue_key: str, hours_ahead: int = 168) -> dict[str, Any]:
    for item in _voice_passes(hours_ahead):
        if str(item.get("queue_key") or "") == queue_key:
            return item
    raise ValueError("The selected ISS pass no longer exists or is below the minimum elevation.")


def _parse_local(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid start or stop time.") from exc


def set_item(payload: dict[str, Any]) -> dict[str, Any]:
    queue_key = str(payload.get("queue_key") or "").strip()
    if not queue_key:
        raise ValueError("queue_key is required.")
    item = _find_pass(queue_key)

    use_custom_window = bool(payload.get("use_custom_window", False))
    start_value = str(payload.get("start") or item.get("start") or "")
    stop_value = str(payload.get("stop") or item.get("end") or "")
    start_dt = _parse_local(start_value)
    stop_dt = _parse_local(stop_value)
    if stop_dt <= start_dt:
        raise ValueError("The stop time must be after the start time.")

    pass_start = _parse_local(str(item.get("start")))
    pass_end = _parse_local(str(item.get("end")))
    if stop_dt < pass_start or start_dt > pass_end:
        raise ValueError("The recording window must overlap the ISS pass.")

    receiver = str(payload.get("receiver") or "auto").lower()
    if receiver not in {"auto", "sdr1", "sdr2"}:
        raise ValueError("Invalid receiver selection.")

    planned = {
        "queue_key": queue_key,
        "target": item.get("name") or "ISS (ZARYA)",
        "frequency_mhz": item.get("frequency_mhz") or 145.8,
        "max_elevation": item.get("max_elevation"),
        "pass_start": item.get("start"),
        "pass_end": item.get("end"),
        "start": start_value,
        "stop": stop_value,
        "use_custom_window": use_custom_window,
        "receiver": receiver,
        "record_audio": True,
        "live_monitor": bool(payload.get("live_monitor", False)),
        "status": "SCHEDULED",
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    items = _load()
    items[queue_key] = planned
    _save(items)
    return planned


def remove_item(queue_key: str) -> None:
    items = _load()
    items.pop(str(queue_key or ""), None)
    _save(items)


def get_payload(hours_ahead: int = 48) -> dict[str, Any]:
    minimum = float(weather_planning.get_config().get("minimum_elevation", 40.0))
    passes = _voice_passes(hours_ahead)
    schedules = _load()
    valid_keys = {str(item.get("queue_key") or "") for item in passes}
    visible_schedules = {key: value for key, value in schedules.items() if key in valid_keys}
    assignments = config_core.get_receiver_assignments()
    default_receiver = str(assignments.get("voice") or "auto").lower()
    if default_receiver not in {"auto", "sdr1", "sdr2"}:
        default_receiver = "auto"
    return {
        "ok": True,
        "minimum_elevation": minimum,
        "default_receiver": default_receiver,
        "passes": passes,
        "schedules": visible_schedules,
        "recording_execution_enabled": False,
        "message": "Voice recordings can be scheduled; automatic execution will follow after UI acceptance.",
    }
