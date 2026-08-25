#!/usr/bin/env python3

"""Mission Queue planning, operator overrides and conflict detection."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
import json

from core import event_bus, mission_planner, receiver_manager, tle
from core.config import get_assignment, get_scheduler_config

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
    return str(mission_planner.pass_key(item))


def get_pass_key(item: dict[str, Any] | None) -> str | None:
    return mission_planner.pass_key(item)


def _pinned_candidate(item: dict[str, Any]) -> dict[str, Any]:
    candidate = deepcopy(item)
    for field in ("start", "maximum", "end"):
        epoch = candidate.get(f"{field}_epoch")
        if epoch is None:
            raise ValueError(f"Pinned mission contract has no {field}_epoch")
        candidate[field] = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    return candidate


def _same_orbital_pass(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if str(first.get("plugin_id")) != str(second.get("plugin_id")):
        return False
    if str(first.get("name")) != str(second.get("name")):
        return False
    first_maximum = first.get("maximum")
    first_epoch = int(first_maximum.timestamp()) if hasattr(first_maximum, "timestamp") else int(first.get("maximum_epoch") or 0)
    second_maximum = second.get("maximum")
    second_epoch = int(second_maximum.timestamp()) if hasattr(second_maximum, "timestamp") else int(second.get("maximum_epoch") or 0)
    return abs(first_epoch - second_epoch) <= 1800


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
        "plugin_id": item.get("plugin_id", "weather"),
        "mission_type": item.get("mission_type", item.get("plugin_id", "weather")),
        "receiver_role": item.get("receiver_role", "weather"),
        "planner_source": item.get("planner_source", "weather_passes"),
        "automation_eligible": bool(item.get("automation_eligible", True)),
        "execution_enabled": bool(item.get("execution_enabled", True)),
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
        "minimum_peak_elevation": item.get("minimum_peak_elevation"),
        "begin_elevation": item.get("begin_elevation"),
        "close_elevation": item.get("close_elevation"),
        "planning_profile_id": item.get("planning_profile_id"),
        "planning_decision": item.get("planning_decision"),
        "planning_reason": item.get("planning_reason"),
        "norad_id": item.get("norad_id"),
        "tle_source": item.get("tle_source"),
        "tle_epoch": item.get("tle_epoch"),
        "tle_sha256": item.get("tle_sha256"),
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
        "conflicts": [],
        "blocked_by": None,
        "blocked_by_name": None,
        "blocked_by_receiver": None,
        "blocking": [],
        "conflict_scope": None,
        "overlap_seconds": 0,
        "overlap_warning": False,
        "status": "QUEUED",
    }


def _overlap_seconds(first: dict[str, Any], second: dict[str, Any]) -> int:
    return max(
        0,
        min(int(first["end_epoch"]), int(second["end_epoch"]))
        - max(int(first["start_epoch"]), int(second["start_epoch"])),
    )


def _apply_conflicts(
    queue: list[dict[str, Any]],
    *,
    active_pass_key: str | None = None,
) -> None:
    """Project the single automation lane onto the planned queue.

    Receiver identity remains visible in the conflict metadata, but SDRCC's
    current automation runtime can start only one mission at a time. The first
    chronological mission therefore keeps its normal NEXT/TARGET/ACTIVE state;
    only a later overlapping mission becomes BLOCKED. An actually active pass
    always wins over chronological projection.
    """
    candidates = [item for item in queue if not item.get("skipped")]
    active = next(
        (item for item in candidates if item.get("queue_key") == active_pass_key),
        None,
    )
    accepted: list[dict[str, Any]] = [active] if active is not None else []

    for item in candidates:
        if item is active:
            continue
        blocker = next(
            (
                accepted_item
                for accepted_item in accepted
                if _overlap_seconds(accepted_item, item) > 0
            ),
            None,
        )
        if blocker is None:
            accepted.append(item)
            accepted.sort(key=lambda value: (value["start_epoch"], value["queue_key"]))
            continue

        overlap = _overlap_seconds(blocker, item)
        same_receiver = bool(item.get("receiver")) and item.get("receiver") == blocker.get("receiver")
        scope = "receiver" if same_receiver else "mission_engine"
        blocker["conflict_with"].append(item["queue_key"])
        blocker["blocking"].append(item["queue_key"])
        blocker["conflicts"].append({
            "queue_key": item["queue_key"],
            "name": item.get("name"),
            "receiver": item.get("receiver"),
            "scope": scope,
            "overlap_seconds": overlap,
        })
        blocker["overlap_warning"] = True

        item["conflict_with"].append(blocker["queue_key"])
        item["conflicts"].append({
            "queue_key": blocker["queue_key"],
            "name": blocker.get("name"),
            "receiver": blocker.get("receiver"),
            "scope": scope,
            "overlap_seconds": overlap,
        })
        item["blocked_by"] = blocker["queue_key"]
        item["blocked_by_name"] = blocker.get("name")
        item["blocked_by_receiver"] = blocker.get("receiver")
        item["conflict_scope"] = scope
        item["overlap_seconds"] = overlap


def get_queue(
    limit: int = 10,
    hours_ahead: int = 48,
    *,
    active_pass_key: str | None = None,
    target_pass_key: str | None = None,
    controller_status: str | None = None,
    pinned_pass: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 50))
    receiver_status = receiver_manager.get_status()
    with _LOCK:
        state = _load_state()
        overrides = state["overrides"]
    raw = list(mission_planner.get_candidates(hours_ahead))
    if pinned_pass:
        pinned = _pinned_candidate(pinned_pass)
        raw = [item for item in raw if not _same_orbital_pass(item, pinned)]
        if int(pinned.get("end_epoch") or 0) >= int(datetime.now(timezone.utc).timestamp()) - 5:
            raw.append(pinned)
        raw.sort(key=lambda item: item["start"])
    queue = []
    live_keys = set()
    for item in raw[:safe_limit]:
        key = _key(item)
        live_keys.add(key)
        receiver_role = str(item.get("receiver_role") or item.get("plugin_id") or "weather")
        receiver_id = str(get_assignment(receiver_role) or "").lower()
        receiver = receiver_id.upper() if receiver_id else "-"
        base_priority = int(item.get("priority", 5))
        serialized = _serialize(item, overrides.get(key, {}), base_priority, receiver)
        reservation = receiver_status.get("reservations", {}).get(receiver_id) or {}
        reservation_matches = reservation.get("mission_key") == serialized["queue_key"]
        serialized["configured_receiver"] = receiver
        serialized["reserved_receiver"] = (reservation.get("receiver_id") or "").upper() if reservation_matches else None
        serialized["active_receiver"] = serialized["reserved_receiver"] if reservation_matches and reservation.get("status") == "ACTIVE" else None
        serialized["receiver_status"] = reservation.get("status") if reservation_matches else "CONFIGURED"
        queue.append(serialized)
    _apply_conflicts(queue, active_pass_key=active_pass_key)
    eligible = [item for item in queue if not item["skipped"]]
    next_key = eligible[0]["queue_key"] if eligible else None
    for item in queue:
        if item["queue_key"] == active_pass_key:
            item["status"] = "IN PROGRESS"
            item["live_mission_status"] = str(controller_status or "RECORDING").upper()
        elif item["skipped"]:
            item["status"] = "SKIPPED"
        elif item["blocked_by"]:
            item["status"] = "BLOCKED"
        elif item["queue_key"] == target_pass_key:
            item["status"] = "TARGET"
            item["live_mission_status"] = str(controller_status or "WAITING").upper()
        elif item["queue_key"] == next_key:
            item["status"] = "NEXT"
        else:
            item["status"] = "QUEUED"
        item.setdefault("live_mission_status", None)
        if item["skipped"]:
            item["decision"] = "SKIPPED"
            item["decision_reason"] = "Manually skipped by the operator."
            item["decision_class"] = "skipped"
        elif item["blocked_by"]:
            blocker_name = str(item.get("blocked_by_name") or item["blocked_by"])
            blocker_receiver = str(item.get("blocked_by_receiver") or "another receiver")
            if item.get("conflict_scope") == "receiver":
                reason = (
                    f"{item.get('receiver') or 'The receiver'} is already needed by "
                    f"{blocker_name}."
                )
            else:
                reason = (
                    "The single Mission Automation runtime is occupied by "
                    f"{blocker_name} on {blocker_receiver}."
                )
            item["decision"] = "BLOCKED"
            item["decision_reason"] = reason
            item["decision_class"] = "blocked"
        elif item["status"] in {"IN PROGRESS"}:
            item["decision"] = "ACTIVE"
            item["decision_reason"] = "Mission is currently active."
            item["decision_class"] = "active"
        elif item["status"] in {"TARGET", "NEXT"}:
            item["decision"] = "TARGET"
            item["decision_reason"] = "Selected as the next automated mission."
            item["decision_class"] = "target"
        else:
            item["decision"] = str(item.get("planning_decision") or "ELIGIBLE")
            item["decision_reason"] = str(
                item.get("planning_reason")
                or "Pass meets the current station planning policy."
            )
            item["decision_class"] = "eligible"
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
    pinned_pass: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated_at = datetime.now().astimezone()
    queue = get_queue(
        limit,
        hours_ahead,
        active_pass_key=active_pass_key,
        target_pass_key=target_pass_key,
        controller_status=controller_status,
        pinned_pass=pinned_pass,
    )
    return {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "generated_epoch": int(generated_at.timestamp()),
        "source": "multi-mission-planner",
        "planner_version": mission_planner.VERSION,
        "planner_authority": "planning_only",
        "sources": mission_planner.get_sources(hours_ahead),
        "ok": True,
        "count": len(queue),
        "limit": limit,
        "hours_ahead": hours_ahead,
        "minimum_elevation": mission_planner.get_policy()["minimum_elevation"],
        "planning_policy": mission_planner.get_policy(),
        "planning_profiles": mission_planner.get_policy()["profiles"],
        "tle_status": tle.get_status(),
        "conflicts": sum(1 for item in queue if item["status"] == "BLOCKED"),
        "blocked": sum(1 for item in queue if item["status"] == "BLOCKED"),
        "overlap_warnings": sum(1 for item in queue if item.get("overlap_warning")),
        "skipped": sum(1 for item in queue if item["status"] == "SKIPPED"),
        "queue": queue,
    }



def is_pass_skipped(pass_data: dict[str, Any] | None) -> bool:
    """Return whether the matching planned pass is skipped by Mission Queue."""
    if not pass_data:
        return False
    key = _key(pass_data)
    with _LOCK:
        state = _load_state()
        override = state.get("overrides", {}).get(key, {})
    return bool(override.get("skipped", False))

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
        "Mission Queue changed",
        f"{key}: {action}",
        data={"queue_key": key, "action": action, "override": changed},
    )
    return changed
