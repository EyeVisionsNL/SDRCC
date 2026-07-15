#!/usr/bin/env python3

import os
from pathlib import Path

from core import event_bus
from core import mission_engine
from core import passes
from core import receiver_manager
from core import tle
from core.device_manager import get_dynamic_device


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = PROJECT_ROOT / "data" / "recordings"


def _check(name, ok, detail):
    return {
        "name": name,
        "ok": bool(ok),
        "detail": str(detail),
    }


def run_preflight():
    checks = []

    mission_status = mission_engine.get_mission_status()
    active_job = mission_status.get("active_job")
    phase = mission_status.get("phase")

    checks.append(
        _check(
            "Mission Engine",
            active_job is None and phase == "READY",
            (
                "READY en geen actieve Mission Job"
                if active_job is None and phase == "READY"
                else f"Phase={phase}, active_job={active_job is not None}"
            ),
        )
    )

    device = get_dynamic_device()
    receiver_status = receiver_manager.get_status()
    reservation = receiver_status.get("reservation")
    receiver_available = bool(device) and (
        reservation is None or reservation.get("receiver_id") == device.get("id")
    )

    checks.append(
        _check(
            "Weather Receiver beschikbaarheid",
            receiver_available,
            (
                f"{device.get('number')} is beschikbaar"
                if receiver_available and device
                else f"Gereserveerd voor {reservation.get('mission_key', 'onbekend')}"
                if reservation
                else "Geen Weather Receiver beschikbaar"
            ),
        )
    )

    device_ok = bool(device and device.get("serial"))

    checks.append(
        _check(
            "Weather Receiver",
            device_ok,
            (
                f"{device.get('name')} / {device.get('serial')}"
                if device_ok
                else "Geen dynamische SDR met serienummer gevonden"
            ),
        )
    )

    next_pass = passes.get_next_pass()

    checks.append(
        _check(
            "Volgende passage",
            next_pass is not None,
            (
                next_pass.get("name", "-")
                if next_pass is not None
                else "Geen geschikte METEOR-passage gevonden"
            ),
        )
    )

    tle_ok = tle.exists()

    checks.append(
        _check(
            "TLE database",
            tle_ok,
            "Aanwezig" if tle_ok else "Ontbreekt",
        )
    )

    try:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        output_ok = os.access(RECORDINGS_DIR, os.W_OK)
    except Exception:
        output_ok = False

    checks.append(
        _check(
            "Opnamemap",
            output_ok,
            str(RECORDINGS_DIR),
        )
    )

    passed = all(item["ok"] for item in checks)
    failed = [
        item["name"]
        for item in checks
        if not item["ok"]
    ]

    result = {
        "passed": passed,
        "status": "OK" if passed else "FAILED",
        "detail": (
            "Alle preflightchecks zijn geslaagd"
            if passed
            else "Mislukt: " + ", ".join(failed)
        ),
        "checks": checks,
    }

    event_bus.publish_preflight(
        "SUCCESS" if passed else "WARNING",
        "Preflight geslaagd" if passed else "Preflight mislukt",
        result["detail"],
        data={
            "passed": passed,
            "failed_checks": failed,
            "checks": checks,
        },
    )

    return result
