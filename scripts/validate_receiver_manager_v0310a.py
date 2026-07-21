#!/usr/bin/env python3
"""Non-destructive validation for v0.31.0a Receiver Manager."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import receiver_manager
from core.device_manager import get_devices


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> int:
    devices = get_devices()
    check(len(devices) >= 2, "at least two configured receivers found")
    sdr1, sdr2 = devices[0]["id"], devices[1]["id"]

    original_state_file = receiver_manager.STATE_FILE
    original_publish = receiver_manager.event_bus.publish_receiver

    with tempfile.TemporaryDirectory(prefix="sdrcc-rm-v0310a-") as temp_dir:
        test_state = Path(temp_dir) / "receiver_manager.json"
        receiver_manager.STATE_FILE = test_state
        receiver_manager.event_bus.publish_receiver = lambda *args, **kwargs: None
        try:
            # Legacy migration.
            test_state.write_text(json.dumps({
                "reservation": {
                    "receiver_id": sdr1,
                    "mission_key": "legacy-A",
                    "status": "ACTIVE",
                },
                "last_release": None,
            }), encoding="utf-8")
            migrated = receiver_manager._load_state()
            check("reservation" not in migrated, "legacy singular key removed in memory")
            check(sdr1 in migrated["reservations"], "legacy reservation migrated")

            # Clean state for independent reservation tests.
            test_state.unlink()
            receiver_manager.reserve(sdr1, mission_key="mission-A")
            status = receiver_manager.get_status()
            check(sdr1 in status["reservations"], "SDR1 reservation created")
            check(receiver_manager.is_available(sdr2), "SDR2 remains available")

            receiver_manager.reserve(sdr2, mission_key="mission-B")
            status = receiver_manager.get_status()
            check(len(status["reservations"]) == 2, "two reservations coexist")

            try:
                receiver_manager.reserve(sdr1, mission_key="mission-C")
            except RuntimeError:
                print("PASS: conflicting SDR1 reservation rejected")
            else:
                raise AssertionError("conflicting SDR1 reservation was accepted")

            try:
                receiver_manager.reserve(sdr2, mission_key="mission-A")
            except RuntimeError:
                print("PASS: mission cannot move silently to another receiver")
            else:
                raise AssertionError("mission moved silently to another receiver")

            receiver_manager.activate(mission_key="mission-A", mission_id="A-1")
            status = receiver_manager.get_status()
            check(status["reservations"][sdr1]["status"] == "ACTIVE", "SDR1 activated")
            check(status["reservations"][sdr2]["status"] == "RESERVED", "SDR2 unaffected by SDR1 activation")

            receiver_manager.release(mission_key="mission-A", detail="test release A")
            status = receiver_manager.get_status()
            check(sdr1 not in status["reservations"], "SDR1 released")
            check(sdr2 in status["reservations"], "SDR2 remains reserved")

            receiver_manager.release(mission_key="mission-B", detail="test release B")
            status = receiver_manager.get_status()
            check(not status["reservations"], "all test reservations released")
            check(set(status["available_receivers"]) >= {sdr1, sdr2}, "both receivers available")

            written = json.loads(test_state.read_text(encoding="utf-8"))
            check("reservations" in written, "new state format persisted")
            check("reservation" not in written, "legacy state format not persisted")
        finally:
            receiver_manager.STATE_FILE = original_state_file
            receiver_manager.event_bus.publish_receiver = original_publish

    print("SUCCESS: v0.31.0a Receiver Manager validation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
