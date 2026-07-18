#!/usr/bin/env python3

"""Read-only VOICE mission observer and timeline model.

v0.29.0a deliberately does not reserve receivers, stop services or start rtl_fm.
It converts the next planned VOICE pass into a stable mission-state payload for
Mission Planner and future Voice Mission execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core import mission_queue

VOICE_STATE_ORDER = [
    "WAIT_FOR_AOS",
    "PREPARING",
    "RESERVING_RECEIVER",
    "SERVICE_HANDOVER",
    "TUNING",
    "LISTENING",
    "FINISHING",
    "COMPLETE",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m {remainder:02d}s"
    return f"{minutes:d}m {remainder:02d}s"


def _state_for_pass(item: dict[str, Any], now_epoch: int) -> tuple[str, str]:
    start_epoch = int(item.get("start_epoch") or 0)
    end_epoch = int(item.get("end_epoch") or start_epoch)
    if now_epoch < start_epoch - 300:
        return "WAIT_FOR_AOS", "Waiting for the preparation window."
    if now_epoch < start_epoch - 120:
        return "PREPARING", "VOICE mission preparation window is active."
    if now_epoch < start_epoch - 60:
        return "RESERVING_RECEIVER", "Receiver reservation is modelled but not executed in v0.29.0a."
    if now_epoch < start_epoch - 20:
        return "SERVICE_HANDOVER", "Service handover is modelled but not executed in v0.29.0a."
    if now_epoch < start_epoch:
        return "TUNING", "Tuning phase is modelled; rtl_fm is not started yet."
    if now_epoch <= end_epoch:
        return "LISTENING", "ISS is above the horizon; audio execution arrives in v0.29.0b."
    if now_epoch <= end_epoch + 30:
        return "FINISHING", "Pass has ended; future execution will restore services here."
    return "COMPLETE", "Planned VOICE pass is complete."


def _serialize_timeline(item: dict[str, Any], now_epoch: int) -> dict[str, Any]:
    start_epoch = int(item.get("start_epoch") or 0)
    maximum_epoch = int(item.get("maximum_epoch") or start_epoch)
    end_epoch = int(item.get("end_epoch") or start_epoch)
    duration_seconds = max(0, end_epoch - start_epoch)
    if duration_seconds:
        progress = _clamp(((now_epoch - start_epoch) / duration_seconds) * 100.0)
        max_position = _clamp(((maximum_epoch - start_epoch) / duration_seconds) * 100.0)
    else:
        progress = 0.0
        max_position = 50.0
    state, detail = _state_for_pass(item, now_epoch)
    remaining_seconds = max(0, end_epoch - now_epoch) if now_epoch >= start_epoch else duration_seconds
    return {
        "mission_key": item.get("queue_key"),
        "mission_type": "VOICE",
        "target": item.get("name") or "ISS",
        "frequency": item.get("frequency"),
        "frequency_mhz": item.get("frequency_mhz"),
        "mode": item.get("mode") or "FM VOICE",
        "receiver": item.get("active_receiver") or item.get("reserved_receiver") or item.get("configured_receiver") or item.get("receiver") or "NOT ASSIGNED",
        "aos": item.get("start"),
        "maximum": item.get("maximum"),
        "los": item.get("end"),
        "aos_epoch": start_epoch,
        "maximum_epoch": maximum_epoch,
        "los_epoch": end_epoch,
        "duration_seconds": duration_seconds,
        "duration_label": _format_duration(duration_seconds),
        "seconds_until_aos": start_epoch - now_epoch,
        "seconds_remaining": remaining_seconds,
        "progress_percent": round(progress, 1),
        "maximum_position_percent": round(max_position, 1),
        "max_elevation": item.get("max_elevation"),
        "state": state,
        "state_order": VOICE_STATE_ORDER,
        "detail": detail,
        "execution_enabled": False,
        "service_handover_enabled": False,
        "audio_enabled": False,
    }


def get_status(hours_ahead: int = 48) -> dict[str, Any]:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    payload = mission_queue.get_payload(limit=50, hours_ahead=hours_ahead)
    voice_items = [
        item for item in payload.get("queue", [])
        if str(item.get("mission_type") or "").upper() == "VOICE" and not item.get("skipped")
    ]
    active_or_next = next(
        (item for item in voice_items if int(item.get("end_epoch") or 0) >= now_epoch - 30),
        None,
    )
    return {
        "ok": True,
        "version": "v0.29.0a",
        "observer_only": True,
        "automation_scope": "WEATHER_ONLY",
        "now_epoch": now_epoch,
        "voice_count": len(voice_items),
        "mission": _serialize_timeline(active_or_next, now_epoch) if active_or_next else None,
    }
