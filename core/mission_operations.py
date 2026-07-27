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
from core import iss_voice_runtime
from core import iss_voice_audio_monitor
from core import mission_engine
from core import mission_result
from core import mission_scheduler
from core import receiver_manager

VERSION = "0.53.0a"
AUTHORITY = "observer_only"


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


def _console_snapshot(
    summary: dict[str, Any] | None,
    mission: dict[str, Any],
    rf: dict[str, Any],
    receiver: dict[str, Any],
    scheduler: dict[str, Any],
    iss: dict[str, Any],
    audio_monitor: dict[str, Any],
) -> dict[str, Any]:
    """Project existing owner state into stable read-only dashboard sections."""
    summary = summary if isinstance(summary, dict) else {}
    active = bool(summary.get("active"))
    is_iss = (
        summary.get("mission_type") == "iss_voice"
        or summary.get("plugin_id") == "iss_voice"
        or bool(iss.get("active"))
    )
    observer = scheduler.get("observer") if isinstance(scheduler.get("observer"), dict) else {}
    reservation = receiver.get("reservation")
    receiver_state = (
        reservation.get("status")
        if isinstance(reservation, dict)
        else summary.get("receiver_status") or "AVAILABLE"
    )

    recorder_bytes = _coalesce(
        summary.get("iq_bytes"),
        audio_monitor.get("iq_bytes") if is_iss else None,
        rf.get("recording_bytes"),
        rf.get("bytes_written"),
    )
    recorder_rate = _coalesce(
        summary.get("iq_byte_rate"),
        audio_monitor.get("observed_byte_rate") if is_iss else None,
        rf.get("byte_rate"),
    )

    return {
        "mission": {
            "active": active,
            "mission_id": summary.get("mission_id"),
            "mission_type": _coalesce(
                summary.get("mission_type"),
                summary.get("plugin_id"),
                "weather" if summary.get("satellite") else None,
            ),
            "satellite": summary.get("satellite"),
            "state": _coalesce(summary.get("status"), observer.get("phase"), "IDLE"),
            "detail": _coalesce(summary.get("detail"), observer.get("detail")),
            "elapsed_seconds": summary.get("duration_seconds"),
            "remaining_seconds": summary.get("remaining_seconds"),
            "started_at": summary.get("started_at"),
            "ended_at": summary.get("ended_at"),
        },
        "rf": {
            "active": bool(rf.get("active") or iss.get("active")),
            "receiver": _coalesce(summary.get("receiver"), summary.get("receiver_id")),
            "receiver_serial": summary.get("receiver_serial"),
            "receiver_state": receiver_state,
            "frequency_hz": summary.get("frequency"),
            "sample_rate_hz": summary.get("sample_rate"),
            "mode": summary.get("mode"),
            "snr_db": None if is_iss else summary.get("snr_db"),
            "peak_snr_db": None if is_iss else summary.get("peak_snr_db"),
            "signal_metrics_available": not is_iss,
        },
        "recorder": {
            "active": active and bool(summary.get("output_path")),
            "type": "wideband_iq" if is_iss else "satdump",
            "status": (
                audio_monitor.get("stream_state")
                if is_iss
                else _coalesce(rf.get("state"), summary.get("status"), "STANDBY")
            ),
            "bytes": recorder_bytes,
            "byte_rate": recorder_rate,
            "output_path": summary.get("output_path"),
        },
        "decoder": {
            "applicable": not is_iss,
            "pipeline": summary.get("pipeline"),
            "status": "NOT APPLICABLE" if is_iss else _coalesce(summary.get("status"), "STANDBY"),
            "frames": summary.get("frames"),
            "cadu_bytes": summary.get("cadu_bytes"),
            "image_count": summary.get("image_count"),
            "ber": summary.get("ber"),
            "viterbi": summary.get("viterbi"),
            "deframer": summary.get("deframer"),
        },
        "runtime": {
            "authority": AUTHORITY,
            "scheduler_mode": scheduler.get("mode"),
            "scheduler_phase": observer.get("phase"),
            "receiver_state": receiver_state,
            "audio_monitor_state": audio_monitor.get("stream_state"),
            "audio_clients": audio_monitor.get("active_clients"),
            "generated_from_existing_owners": True,
        },
    }


def get_snapshot() -> dict[str, Any]:
    """Return one timestamped snapshot for all mission-operation widgets."""
    mission = _normalise_mission_snapshot(mission_engine.get_mission_status())
    rf = live_rf.get_status()
    receiver = receiver_manager.get_status()
    scheduler = mission_scheduler.get_scheduler_status()
    iss = iss_voice_runtime.get_status()
    audio_monitor = iss_voice_audio_monitor.get_status()
    summary = _mission_summary(mission, rf, receiver)
    if bool(iss.get("active")):
        summary = {
            "mission_id": iss.get("mission_id"),
            "active": True,
            "mission_type": "iss_voice",
            "plugin_id": "iss_voice",
            "satellite": iss.get("satellite") or "ISS (ZARYA)",
            "receiver": str(iss.get("receiver_id") or "").upper() or None,
            "receiver_id": iss.get("receiver_id"),
            "receiver_serial": iss.get("receiver_serial"),
            "frequency": iss.get("frequency_hz"),
            "frequency_mhz": round(float(iss.get("frequency_hz") or 0) / 1_000_000, 6),
            "sample_rate": iss.get("sample_rate_hz"),
            "mode": iss.get("mode"),
            "pipeline": "wideband_iq_offline_fm",
            "status": iss.get("phase"),
            "result": None,
            "success": None,
            "detail": iss.get("detail"),
            "error": iss.get("error"),
            "started_at": iss.get("started_at"),
            "ended_at": None,
            "duration_seconds": iss.get("elapsed_seconds"),
            "remaining_seconds": None,
            "output_path": iss.get("output_directory"),
            "receiver_status": "ACTIVE",
            "iq_bytes": audio_monitor.get("iq_bytes"),
            "iq_byte_rate": audio_monitor.get("observed_byte_rate"),
            "audio_monitor_state": audio_monitor.get("stream_state"),
        }

    console = _console_snapshot(summary, mission, rf, receiver, scheduler, iss, audio_monitor)

    return {
        "ok": True,
        "version": VERSION,
        "authority": AUTHORITY,
        "generated_at": _now_text(),
        "mission": mission,
        "live_rf": rf,
        "iss_voice": iss,
        "audio_monitor": audio_monitor,
        "receiver_manager": receiver,
        "scheduler": scheduler,
        "summary": summary,
        "console": console,
    }
