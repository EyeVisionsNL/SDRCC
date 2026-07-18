#!/usr/bin/env python3

"""VOICE mission timeline model with manual live receiver runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core import config as config_core
from core import mission_queue
from core import voice_receiver
from core import weather_planning

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
        return "RESERVING_RECEIVER", "Ready to reserve the configured Voice receiver."
    if now_epoch < start_epoch - 20:
        return "SERVICE_HANDOVER", "Ready for live service handover."
    if now_epoch < start_epoch:
        return "TUNING", "Ready to tune rtl_fm to the ISS Voice frequency."
    if now_epoch <= end_epoch:
        return "LISTENING", "ISS is above the horizon; manual live listening is available."
    if now_epoch <= end_epoch + 30:
        return "FINISHING", "Pass has ended; future execution will restore services here."
    return "COMPLETE", "Planned VOICE pass is complete."


def _voice_default_receiver() -> str:
    assignments = config_core.get_receiver_assignments()
    receiver = str(assignments.get("voice") or "auto").upper()
    return receiver if receiver in {"AUTO", "SDR1", "SDR2"} else "AUTO"


def _normalized_receiver(*values: Any) -> str:
    """Return the first usable receiver value, falling back to Voice assignment.

    Mission Queue may expose placeholder values such as ``NOT ASSIGNED`` in
    ``configured_receiver`` before runtime reservation. Those placeholders must
    never override the configured Voice receiver from station.yaml.
    """
    for value in values:
        receiver = str(value or "").strip().upper()
        if receiver in {"AUTO", "SDR1", "SDR2"}:
            return receiver
    return _voice_default_receiver()


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
        "receiver": _normalized_receiver(
            item.get("active_receiver"),
            item.get("reserved_receiver"),
            item.get("configured_receiver"),
            item.get("receiver"),
        ),
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
        "execution_enabled": True,
        "automatic_start_enabled": False,
        "service_handover_enabled": True,
        "audio_enabled": True,
    }


def get_status(hours_ahead: int = 48) -> dict[str, Any]:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    payload = mission_queue.get_payload(limit=50, hours_ahead=hours_ahead)
    minimum = float(weather_planning.get_config().get("minimum_elevation", 40.0))
    voice_items = [
        item for item in payload.get("queue", [])
        if str(item.get("mission_type") or "").upper() == "VOICE"
        and not item.get("skipped")
        and float(item.get("max_elevation") or 0.0) >= minimum
    ]
    active_or_next = next(
        (item for item in voice_items if int(item.get("end_epoch") or 0) >= now_epoch - 30),
        None,
    )
    return {
        "ok": True,
        "version": "v0.29.0d3a",
        "observer_only": False,
        "automatic_start_enabled": False,
        "automation_scope": "WEATHER_AUTO_VOICE_MANUAL",
        "now_epoch": now_epoch,
        "voice_count": len(voice_items),
        "mission": _serialize_timeline(active_or_next, now_epoch) if active_or_next else None,
        "receiver_runtime": voice_receiver.get_status().get("runtime"),
    }
