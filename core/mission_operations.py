"""Unified operational snapshot for the SDRCC mission dashboard.

This module is intentionally read-only. It combines state owned by the
Mission Engine, Live RF, Receiver Manager, Automation Controller and Scheduler
without moving ownership away from those modules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core import automation_controller
from core import live_rf
from core import mission_engine
from core import mission_scheduler
from core import receiver_manager


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _mission_summary(mission: dict[str, Any]) -> dict[str, Any] | None:
    active_job = mission.get("active_job")
    last_result = mission.get("last_result")
    source = active_job or last_result
    if not isinstance(source, dict):
        return None

    return {
        "mission_id": source.get("mission_id"),
        "active": bool(active_job),
        "satellite": source.get("satellite"),
        "receiver": source.get("receiver"),
        "receiver_serial": source.get("receiver_serial"),
        "frequency": source.get("frequency"),
        "frequency_mhz": source.get("frequency_mhz"),
        "mode": source.get("mode"),
        "pipeline": source.get("pipeline"),
        "status": source.get("status"),
        "result": source.get("result"),
        "success": source.get("success"),
        "detail": source.get("detail"),
        "error": source.get("error"),
        "started_at": source.get("started_at"),
        "ended_at": source.get("ended_at"),
        "duration_seconds": source.get("duration_seconds"),
        "peak_snr_db": source.get("peak_snr_db"),
        "frames": source.get("frames"),
        "cadu_bytes": source.get("cadu_bytes"),
        "image_count": source.get("image_count"),
        "output_path": source.get("output_path"),
    }


def get_snapshot() -> dict[str, Any]:
    """Return one timestamped snapshot for all mission-operation widgets."""
    mission = mission_engine.get_mission_status()
    rf = live_rf.get_status()
    receiver = receiver_manager.get_status()
    controller = automation_controller.get_status()
    scheduler = mission_scheduler.get_scheduler_status()

    return {
        "ok": True,
        "generated_at": _now_text(),
        "mission": mission,
        "live_rf": rf,
        "receiver_manager": receiver,
        "automation_controller": controller,
        "scheduler": scheduler,
        "summary": _mission_summary(mission),
    }
