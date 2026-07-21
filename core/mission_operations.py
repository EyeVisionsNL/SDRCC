"""Unified operational snapshot for the SDRCC mission dashboard.

This module is intentionally read-only. It combines state owned by the
Mission Engine, Live RF, Receiver Manager and Scheduler
without moving ownership away from those modules.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from core import live_rf
from core import mission_engine
from core import mission_result
from core import mission_scheduler
from core import receiver_manager


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalise_mission_snapshot(mission: dict[str, Any]) -> dict[str, Any]:
    """Normalize historic outcomes without mutating Mission Engine state."""
    normalized = deepcopy(mission)

    history = normalized.get("history")
    if isinstance(history, list):
        normalized["history"] = [
            mission_result.normalize_history_mission(item)
            if isinstance(item, dict)
            else item
            for item in history
        ]

    last_result = normalized.get("last_result")
    if isinstance(last_result, dict):
        normalized["last_result"] = mission_result.normalize_history_mission(last_result)

    active_job = normalized.get("active_job")
    if isinstance(active_job, dict) and active_job.get("ended_at"):
        normalized["active_job"] = mission_result.normalize_history_mission(active_job)

    return normalized


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _mission_summary(
    mission: dict[str, Any],
    rf: dict[str, Any],
    receiver: dict[str, Any],
) -> dict[str, Any] | None:
    active_job = mission.get("active_job")
    last_result = mission.get("last_result")
    rf_active = bool(rf.get("active"))
    source = active_job if isinstance(active_job, dict) else last_result

    if not isinstance(source, dict) and not rf_active:
        return None
    source = source if isinstance(source, dict) else {}

    reservation = receiver.get("reservation")
    reserved_device = reservation.get("device") if isinstance(reservation, dict) else None
    configured = receiver.get("configured_receiver")

    summary = {
        "mission_id": _coalesce(rf.get("mission_id"), source.get("mission_id")),
        "active": bool(active_job or rf_active),
        "satellite": _coalesce(rf.get("satellite"), source.get("satellite")),
        "receiver": _coalesce(
            rf.get("receiver"),
            source.get("receiver"),
            reserved_device.get("number") if isinstance(reserved_device, dict) else None,
            configured.get("number") if isinstance(configured, dict) else None,
        ),
        "receiver_serial": _coalesce(
            rf.get("serial"),
            source.get("receiver_serial"),
            reserved_device.get("serial") if isinstance(reserved_device, dict) else None,
            configured.get("serial") if isinstance(configured, dict) else None,
        ),
        "frequency": _coalesce(rf.get("frequency_hz"), source.get("frequency")),
        "frequency_mhz": source.get("frequency_mhz"),
        "sample_rate": _coalesce(rf.get("sample_rate"), source.get("sample_rate")),
        "mode": source.get("mode"),
        "pipeline": source.get("pipeline"),
        "status": _coalesce(rf.get("state") if rf_active else None, source.get("status")),
        "result": _coalesce(rf.get("result"), source.get("result")),
        "success": source.get("success"),
        "detail": _coalesce(rf.get("detail"), source.get("detail")),
        "error": source.get("error"),
        "started_at": _coalesce(rf.get("started_at"), source.get("started_at")),
        "ended_at": _coalesce(rf.get("ended_at"), source.get("ended_at")),
        "duration_seconds": _coalesce(
            rf.get("elapsed_seconds") if rf_active else None,
            source.get("duration_seconds"),
        ),
        "remaining_seconds": rf.get("remaining_seconds"),
        "peak_snr_db": _coalesce(rf.get("peak_snr_db"), source.get("peak_snr_db")),
        "snr_db": rf.get("snr_db"),
        "ber": rf.get("ber"),
        "viterbi": rf.get("viterbi"),
        "deframer": rf.get("deframer"),
        "frames": max(int(rf.get("frames") or 0), int(source.get("frames") or 0)),
        "cadu_bytes": max(int(rf.get("cadu_bytes") or 0), int(source.get("cadu_bytes") or 0)),
        "image_count": max(int(rf.get("image_count") or 0), int(source.get("image_count") or 0)),
        "output_path": _coalesce(rf.get("output_path"), source.get("output_path")),
        "receiver_status": (
            str(reservation.get("status")) if isinstance(reservation, dict) else "AVAILABLE"
        ),
    }

    if summary["frequency_mhz"] is None and summary["frequency"] is not None:
        try:
            summary["frequency_mhz"] = round(float(summary["frequency"]) / 1_000_000, 6)
        except (TypeError, ValueError):
            pass

    return summary


def get_snapshot() -> dict[str, Any]:
    """Return one timestamped snapshot for all mission-operation widgets."""
    mission = _normalise_mission_snapshot(mission_engine.get_mission_status())
    rf = live_rf.get_status()
    receiver = receiver_manager.get_status()
    scheduler = mission_scheduler.get_scheduler_status()

    return {
        "ok": True,
        "generated_at": _now_text(),
        "mission": mission,
        "live_rf": rf,
        "receiver_manager": receiver,
        "scheduler": scheduler,
        "summary": _mission_summary(mission, rf, receiver),
    }
