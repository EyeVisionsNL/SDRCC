#!/usr/bin/env python3
"""Explicit, bounded ISS Voice IQ capture lifecycle.

Receiver Manager remains reservation authority. The dashboard remains the only
systemd-control authority and injects service read/action callbacks. This module
never schedules a mission and never enables automatic ISS execution.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from core import device_manager, execution_factory, execution_journal
from core import receiver_manager
from core import iss_voice
from core import wideband_iq_recorder

ServiceState = Callable[[str], dict[str, Any]]
ServiceAction = Callable[[str, str], Any]
ServiceWait = Callable[[str, str, int], bool]

MAX_CONTROLLED_SECONDS = 30


def _mission_id() -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return f"iss_controlled_{stamp}_{uuid4().hex[:6]}"


def execute_controlled_capture(
    *,
    duration_seconds: int,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
    mission_id: str | None = None,
) -> dict[str, Any]:
    """Run one explicit bounded capture and always restore prior runtime state."""
    duration = int(duration_seconds)
    if duration < 1 or duration > MAX_CONTROLLED_SECONDS:
        raise ValueError(f"duration_seconds moet 1..{MAX_CONTROLLED_SECONDS} zijn")

    validation = iss_voice.validate_config()
    if not validation["ok"]:
        raise RuntimeError("ISS Voice-config ongeldig: " + "; ".join(validation["errors"]))
    config = validation["config"]
    if not bool(config.get("controlled_capture_enabled")):
        raise RuntimeError("Controlled capture is uitgeschakeld")

    device = device_manager.get_assigned_device("iss_voice")
    if device is None:
        raise RuntimeError("Geen receiver toegewezen aan ISS Voice")

    capture_id = mission_id or _mission_id()
    mission_key = f"iss_voice:controlled:{capture_id}"
    stopped_services: list[str] = []
    handover_started = False
    execution_id: str | None = None
    capture: dict[str, Any] | None = None
    failure: Exception | None = None

    observed = execution_factory.build_plan_with_journal(
        "iss_voice",
        {
            "mode": "controlled_capture",
            "duration_seconds": duration,
            "receiver_role": "iss_voice",
            "target": config.get("satellite_name"),
        },
    )
    execution_id = observed["execution_id"]
    execution_journal.append_event_once(
        execution_id, "ACCEPTED", source="controlled_iq_capture",
        details={"mission_id": capture_id, "receiver_id": device["id"]},
    )

    try:
        conflicts = device_manager.get_conflicting_services(
            device["id"], exclude_role="iss_voice"
        )
        manager_status = receiver_manager.begin_handover(
            device["id"],
            mission_key=mission_key,
            mission_id=capture_id,
            reason="ISS Voice controlled IQ capture",
            services=conflicts,
            service_state=service_state,
            service_action=service_action,
            wait_for_service=wait_for_service,
        )
        handover_started = True
        reservation = (manager_status.get("reservations") or {}).get(device["id"]) or {}
        stopped_services = [
            item.get("service")
            for item in (reservation.get("handover") or {}).get("services") or []
            if item.get("stopped_by_sdrcc")
        ]

        receiver_manager.activate(mission_key=mission_key, mission_id=capture_id)
        execution_journal.append_event_once(
            execution_id, "STARTED", source="controlled_iq_capture",
            details={
                "mission_id": capture_id,
                "receiver_id": device["id"],
                "stopped_services": list(stopped_services),
            },
        )

        spec = wideband_iq_recorder.build_spec(
            mission_id=capture_id,
            receiver_serial=device["serial"],
            frequency_hz=int(config["downlink_frequency_hz"]),
            sample_rate_hz=int(config["rf_sample_rate_hz"]),
            duration_seconds=duration,
            gain_db=iss_voice.capture_gain_db(config),
            ppm=int(config.get("ppm") or 0),
        )
        capture = wideband_iq_recorder.execute_capture(
            spec, services_confirmed_stopped=True
        )
        if not capture.get("complete"):
            raise RuntimeError(
                "IQ-opname onvolledig: returncode="
                f"{capture.get('returncode')}, bytes={capture.get('actual_bytes')}"
            )

        execution_journal.append_event_once(
            execution_id, "FINISHED", source="controlled_iq_capture",
            details={
                "mission_id": capture_id,
                "iq_path": capture.get("iq_path"),
                "actual_bytes": capture.get("actual_bytes"),
            },
        )
    except Exception as exc:
        failure = exc
        if execution_id:
            execution_journal.append_event_once(
                execution_id, "FAILED", source="controlled_iq_capture",
                details={"mission_id": capture_id, "error": str(exc)},
            )
    finally:
        restore_errors: list[str] = []
        if handover_started:
            restored = receiver_manager.restore_handover(
                mission_key=mission_key,
                service_state=service_state,
                service_action=service_action,
                wait_for_service=wait_for_service,
                detail=(
                    "ISS controlled capture afgerond"
                    if failure is None else
                    "ISS controlled capture hersteld na fout"
                ),
            )
            restore_errors.extend(restored.get("errors") or [])

        if restore_errors:
            message = "Herstel onvolledig: " + "; ".join(restore_errors)
            if failure is None:
                failure = RuntimeError(message)
            else:
                failure = RuntimeError(f"{failure}; {message}")

    if failure is not None:
        raise failure

    return {
        "ok": True,
        "version": "0.46.0c",
        "mode": "controlled_capture",
        "automatic_execution": False,
        "mission_id": capture_id,
        "execution_id": execution_id,
        "receiver": device,
        "stopped_and_restored_services": stopped_services,
        "capture": capture,
    }
