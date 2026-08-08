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
from core import mission_scheduler
from core import receiver_manager

VERSION = "0.54.0l"
AUTHORITY = "observer_only"


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalise_mission_snapshot(mission: dict[str, Any]) -> dict[str, Any]:
    """Kopieer de snapshot zonder resultaten opnieuw te classificeren."""
    return deepcopy(mission)


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _receiver_runtime_entry(receiver: dict[str, Any], receiver_id: Any) -> dict[str, Any]:
    """Resolve one existing Receiver Manager projection without owning identity."""
    key = str(receiver_id or "").strip()
    if not key:
        return {}
    for mapping_name in ("receivers", "canonical_receivers"):
        mapping = receiver.get(mapping_name)
        if not isinstance(mapping, dict):
            continue
        direct = mapping.get(key)
        if isinstance(direct, dict):
            return direct
        for entry in mapping.values():
            if not isinstance(entry, dict):
                continue
            device = entry.get("device")
            if not isinstance(device, dict):
                continue
            identities = {
                str(device.get(identity) or "").strip()
                for identity in ("id", "runtime_id", "registry_id", "canonical_id")
            }
            if key in identities:
                return entry
    return {}


def _mission_summary(
    mission: dict[str, Any],
    rf: dict[str, Any],
    receiver: dict[str, Any],
) -> dict[str, Any] | None:
    active_job = mission.get("active_job")
    rf_active = bool(rf.get("active"))
    source = active_job if isinstance(active_job, dict) else {}
    active_rf = rf if rf_active else {}

    # Mission Operations is a live workspace. Historical results have their own
    # bounded viewer below the live console and must never be projected back into
    # the active mission. In particular, stale Live RF fields and an ISS
    # last_result previously combined into a fictitious WEATHER/SATDUMP mission.
    if not active_job and not rf_active:
        return None

    reservation = receiver.get("reservation")
    reserved_device = reservation.get("device") if isinstance(reservation, dict) else None
    configured = receiver.get("configured_receiver")

    summary = {
        "mission_id": _coalesce(active_rf.get("mission_id"), source.get("mission_id")),
        "active": True,
        "mission_type": _coalesce(source.get("mission_type"), source.get("plugin_id"), "weather"),
        "plugin_id": _coalesce(source.get("plugin_id"), source.get("mission_type"), "weather"),
        "satellite": _coalesce(active_rf.get("satellite"), source.get("satellite")),
        "receiver": _coalesce(
            active_rf.get("receiver"),
            source.get("receiver"),
            reserved_device.get("number") if isinstance(reserved_device, dict) else None,
            configured.get("number") if isinstance(configured, dict) else None,
        ),
        "receiver_id": source.get("receiver_id"),
        "receiver_serial": _coalesce(
            active_rf.get("serial"),
            source.get("receiver_serial"),
            reserved_device.get("serial") if isinstance(reserved_device, dict) else None,
            configured.get("serial") if isinstance(configured, dict) else None,
        ),
        "frequency": _coalesce(active_rf.get("frequency_hz"), source.get("frequency")),
        "frequency_mhz": source.get("frequency_mhz"),
        "sample_rate": _coalesce(active_rf.get("sample_rate"), source.get("sample_rate")),
        "mode": source.get("mode"),
        "pipeline": _coalesce(active_rf.get("pipeline"), source.get("pipeline")),
        "status": _coalesce(active_rf.get("state"), source.get("status"), mission.get("state")),
        "result": _coalesce(active_rf.get("result"), source.get("result")),
        "success": source.get("success"),
        "detail": _coalesce(active_rf.get("detail"), source.get("detail")),
        "error": source.get("error"),
        "started_at": _coalesce(active_rf.get("started_at"), source.get("started_at")),
        "ended_at": None,
        "duration_seconds": _coalesce(
            active_rf.get("elapsed_seconds"),
            source.get("duration_seconds"),
        ),
        "remaining_seconds": _coalesce(active_rf.get("remaining_seconds"), source.get("remaining_seconds")),
        "progress": source.get("progress"),
        "peak_snr_db": _coalesce(active_rf.get("peak_snr_db"), source.get("peak_snr_db")),
        "snr_db": active_rf.get("snr_db"),
        "ber": active_rf.get("ber"),
        "viterbi": active_rf.get("viterbi"),
        "deframer": active_rf.get("deframer"),
        "frames": max(int(active_rf.get("frames") or 0), int(source.get("frames") or 0)),
        "cadu_bytes": max(int(active_rf.get("cadu_bytes") or 0), int(source.get("cadu_bytes") or 0)),
        "image_count": max(int(active_rf.get("image_count") or 0), int(source.get("image_count") or 0)),
        "output_path": _coalesce(active_rf.get("output_path"), source.get("output_path")),
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

    recorder_bytes = audio_monitor.get("iq_bytes") if active and is_iss else None
    recorder_rate = audio_monitor.get("observed_byte_rate") if active and is_iss else None

    return {
        "mission": {
            "active": active,
            "mission_id": summary.get("mission_id"),
            "mission_type": _coalesce(
                summary.get("mission_type"),
                summary.get("plugin_id"),
                "weather" if active and summary.get("satellite") else None,
            ),
            "satellite": summary.get("satellite"),
            "state": _coalesce(summary.get("status"), "IDLE"),
            "detail": summary.get("detail"),
            "elapsed_seconds": summary.get("duration_seconds"),
            "remaining_seconds": summary.get("remaining_seconds"),
            "started_at": summary.get("started_at"),
            "ended_at": summary.get("ended_at"),
        },
        "rf": {
            "active": active and bool(rf.get("active") or iss.get("active")),
            "receiver": _coalesce(summary.get("receiver"), summary.get("receiver_id")) if active else None,
            "receiver_serial": summary.get("receiver_serial") if active else None,
            "receiver_state": receiver_state if active else "STANDBY",
            "frequency_hz": summary.get("frequency") if active else None,
            "sample_rate_hz": summary.get("sample_rate") if active else None,
            "mode": summary.get("mode") if active else None,
            "snr_db": None if is_iss else summary.get("snr_db"),
            "peak_snr_db": None if is_iss else summary.get("peak_snr_db"),
            "signal_metrics_available": not is_iss,
        },
        "recorder": {
            "active": active and bool(summary.get("output_path")),
            "type": ("wideband_iq" if is_iss else "satdump") if active else None,
            "status": (
                _coalesce(iss.get("phase"), "STANDBY")
                if is_iss
                else _coalesce(rf.get("state") if active else None, summary.get("status") if active else None, "STANDBY")
            ),
            "bytes": recorder_bytes,
            "byte_rate": recorder_rate,
            "metrics_available": bool(active and is_iss),
            "output_path": summary.get("output_path") if active else None,
        },
        "decoder": {
            "applicable": bool(active and not is_iss),
            "pipeline": summary.get("pipeline") if active and not is_iss else None,
            "status": "NOT APPLICABLE" if active and is_iss else _coalesce(summary.get("status") if active else None, "STANDBY"),
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
            "audio_max_clients": audio_monitor.get("max_clients"),
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
        iss_receiver_entry = _receiver_runtime_entry(receiver, iss.get("receiver_id"))
        iss_receiver_device = (
            iss_receiver_entry.get("device")
            if isinstance(iss_receiver_entry.get("device"), dict)
            else {}
        )
        iss_reservation = (
            iss_receiver_entry.get("reservation")
            if isinstance(iss_receiver_entry.get("reservation"), dict)
            else {}
        )
        summary = {
            "mission_id": iss.get("mission_id"),
            "active": True,
            "mission_type": "iss_voice",
            "plugin_id": "iss_voice",
            "satellite": iss.get("satellite") or "ISS (ZARYA)",
            "receiver": _coalesce(
                iss_receiver_device.get("number"),
                str(iss.get("receiver_id") or "").upper() or None,
            ),
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
            "remaining_seconds": iss.get("remaining_seconds"),
            "progress": iss.get("progress"),
            "output_path": iss.get("output_directory"),
            "receiver_status": _coalesce(iss_reservation.get("status"), "ACTIVE"),
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
