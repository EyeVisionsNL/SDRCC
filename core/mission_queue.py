#!/usr/bin/env python3

"""Mission Queue planning, operator overrides and conflict detection."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
import json

from core import event_bus, passes, receiver_manager, weather_planning
from core.config import get_enabled_satellites, get_receiver_assignments, get_scheduler_config

STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "mission_queue.json"
_LOCK = RLock()
DEFAULT_STATE = {"overrides": {}}


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return deepcopy(DEFAULT_STATE)
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return deepcopy(DEFAULT_STATE)
        overrides = data.get("overrides", {})
        return {"overrides": overrides if isinstance(overrides, dict) else {}}
    except Exception:
        return deepcopy(DEFAULT_STATE)


def _save_state(state: dict[str, Any]) -> None:
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_FILE)


def _key(item: dict[str, Any]) -> str:
    start = item.get("start")
    if hasattr(start, "timestamp"):
        epoch = int(start.timestamp())
    else:
        epoch = int(item.get("start_epoch") or 0)
    return f"{item.get('name', '-')}:" + str(epoch)


def _quality(elevation: float, duration_seconds: int) -> dict[str, Any]:
    elevation = float(elevation or 0)
    if elevation >= 80:
        stars, label = 5, "UITSTEKEND"
    elif elevation >= 60:
        stars, label = 4, "ZEER GOED"
    elif elevation >= 40:
        stars, label = 3, "GOED"
    elif elevation >= 25:
        stars, label = 2, "MATIG"
    else:
        stars, label = 1, "LAAG"
    if duration_seconds < 120 and stars > 1:
        stars -= 1
        label = "KORT"
    return {"stars": stars, "label": label}


def _serialize(item: dict[str, Any], override: dict[str, Any], base_priority: int, receiver: str) -> dict[str, Any]:
    start = item["start"]
    maximum = item["maximum"]
    end = item["end"]
    now = datetime.now(timezone.utc)
    duration = int((end - start).total_seconds())
    priority_delta = int(override.get("priority_delta", 0))
    priority = max(1, min(9, int(base_priority) + priority_delta))
    frequency = item.get("frequency")
    scheduler = get_scheduler_config()
    start_epoch = int(start.timestamp())
    now_epoch = int(now.timestamp())
    preflight_epoch = start_epoch - int(scheduler["preflight_seconds"])
    prepare_epoch = start_epoch - int(scheduler["prepare_seconds"])
    lock_epoch = start_epoch - int(scheduler["lock_seconds"])
    return {
        "queue_key": _key(item),
        "name": item.get("name"),
        "start": start.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "maximum": maximum.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "end": end.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "start_epoch": start_epoch,
        "maximum_epoch": int(maximum.timestamp()),
        "end_epoch": int(end.timestamp()),
        "seconds_until_start": start_epoch - now_epoch,
        "eta_preflight_seconds": preflight_epoch - now_epoch,
        "eta_prepare_receiver_seconds": prepare_epoch - now_epoch,
        "eta_receiver_lock_seconds": lock_epoch - now_epoch,
        "eta_recording_seconds": start_epoch - now_epoch,
        "preflight_at_epoch": preflight_epoch,
        "prepare_receiver_at_epoch": prepare_epoch,
        "receiver_lock_at_epoch": lock_epoch,
        "duration_seconds": duration,
        "max_elevation": item.get("max_elevation"),
        "min_elevation": item.get("min_elevation"),
        "azimuth": item.get("azimuth"),
        "frequency": frequency,
        "frequency_mhz": round(frequency / 1_000_000, 3) if frequency else None,
        "sample_rate": item.get("sample_rate"),
        "pipeline": item.get("pipeline"),
        "mode": item.get("mode"),
        "decoder": item.get("decoder"),
        "receiver": receiver,
        "base_priority": int(base_priority),
        "priority_delta": priority_delta,
        "priority": priority,
        "skipped": bool(override.get("skipped", False)),
        "quality": _quality(item.get("max_elevation", 0), duration),
        "conflict_with": [],
        "status": "QUEUED",
    }


def _apply_conflicts(queue: list[dict[str, Any]]) -> None:
    for index, item in enumerate(queue):
        for other in queue[index + 1:]:
            if item["start_epoch"] < other["end_epoch"] and other["start_epoch"] < item["end_epoch"]:
                item["conflict_with"].append(other["queue_key"])
                other["conflict_with"].append(item["queue_key"])


def get_queue(
    limit: int = 10,
    hours_ahead: int = 48,
    *,
    active_pass_key: str | None = None,
    target_pass_key: str | None = None,
    controller_status: str | None = None,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 50))
    satellites = get_enabled_satellites()
    receiver = get_receiver_assignments().get("weather", "-").upper()
    receiver_status = receiver_manager.get_status()
    receiver_id = str(get_receiver_assignments().get("weather", "")).lower()
    reservation = receiver_status.get("reservations", {}).get(receiver_id) or {}
    with _LOCK:
        state = _load_state()
        overrides = state["overrides"]
    planning = weather_planning.get_config()
    minimum_elevation = float(planning["minimum_elevation"])
    raw = passes.get_passes(hours_ahead)
    queue = []
    live_keys = set()
    for item in raw[:safe_limit]:
        key = _key(item)
        live_keys.add(key)
        sat_cfg = satellites.get(item.get("name"), {})
        base_priority = int(sat_cfg.get("priority", 5))
        queue.append(_serialize(item, overrides.get(key, {}), base_priority, receiver))
    _apply_conflicts(queue)
    eligible = [item for item in queue if not item["skipped"]]
    next_key = eligible[0]["queue_key"] if eligible else None
    for item in queue:
        reservation_matches = reservation.get("mission_key") == item["queue_key"]
        item["configured_receiver"] = receiver
        item["reserved_receiver"] = (reservation.get("receiver_id") or "").upper() if reservation_matches else None
        item["active_receiver"] = item["reserved_receiver"] if reservation_matches and reservation.get("status") == "ACTIVE" else None
        item["receiver_status"] = reservation.get("status") if reservation_matches else "CONFIGURED"
        if item["queue_key"] == active_pass_key:
            item["status"] = "IN PROGRESS"
            item["live_mission_status"] = str(controller_status or "RECORDING").upper()
        elif item["queue_key"] == target_pass_key:
            item["status"] = "TARGET"
            item["live_mission_status"] = str(controller_status or "WAITING").upper()
        elif item["skipped"]:
            item["status"] = "SKIPPED"
        elif item["conflict_with"]:
            item["status"] = "CONFLICT"
        elif item["queue_key"] == next_key:
            item["status"] = "NEXT"
        else:
            item["status"] = "QUEUED"
        item.setdefault("live_mission_status", None)
    # Remove stale operator overrides after passages disappear from planning horizon.
    with _LOCK:
        stale = [key for key in overrides if key not in live_keys]
        if stale:
            for key in stale:
                overrides.pop(key, None)
            _save_state(state)
    return queue


def get_payload(
    limit: int = 10,
    hours_ahead: int = 48,
    *,
    active_pass_key: str | None = None,
    target_pass_key: str | None = None,
    controller_status: str | None = None,
) -> dict[str, Any]:
    generated_at = datetime.now().astimezone()
    queue = get_queue(
        limit,
        hours_ahead,
        active_pass_key=active_pass_key,
        target_pass_key=target_pass_key,
        controller_status=controller_status,
    )
    return {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "generated_epoch": int(generated_at.timestamp()),
        "source": "live-pass-planning",
        "ok": True,
        "count": len(queue),
        "limit": limit,
        "hours_ahead": hours_ahead,
        "minimum_elevation": weather_planning.get_config()["minimum_elevation"],
        "conflicts": sum(1 for item in queue if item["status"] == "CONFLICT"),
        "skipped": sum(1 for item in queue if item["status"] == "SKIPPED"),
        "queue": queue,
    }


def update_item(queue_key: str, *, action: str) -> dict[str, Any]:
    key = str(queue_key or "").strip()
    action = str(action or "").strip().lower()
    if not key:
        raise ValueError("queue_key ontbreekt")
    if action not in {"skip", "activate", "priority_up", "priority_down", "priority_reset"}:
        raise ValueError("Onbekende Mission Queue-actie")
    with _LOCK:
        state = _load_state()
        override = state["overrides"].setdefault(key, {})
        if action == "skip":
            override["skipped"] = True
        elif action == "activate":
            override["skipped"] = False
        elif action == "priority_up":
            override["priority_delta"] = min(8, int(override.get("priority_delta", 0)) + 1)
        elif action == "priority_down":
            override["priority_delta"] = max(-8, int(override.get("priority_delta", 0)) - 1)
        elif action == "priority_reset":
            override["priority_delta"] = 0
        _save_state(state)
        changed = deepcopy(override)
    event_bus.publish_automation(
        "INFO",
        "Mission Queue gewijzigd",
        f"{key}: {action}",
        data={"queue_key": key, "action": action, "override": changed},
    )
    return changed
