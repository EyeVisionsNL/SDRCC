#!/usr/bin/env python3

from pathlib import Path
from zoneinfo import ZoneInfo
import subprocess
import time

from core import passes
from core import process_manager
from core import state
from core.device_manager import get_device

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "recordings"


def check_recording_allowed():
    current_state = state.get_sdr2_state()

    if current_state["profile"] not in {"weather", "adsb"}:
        return False, (
            f"SDR2 staat nu op profiel '{current_state['profile']}'.\n"
            "Opnemen is alleen toegestaan vanuit het profiel "
            "weather of adsb."
        )

    if current_state["locked"]:
        return False, "SDR2 is gelocked en mag nu niet gebruikt worden."

    if current_state["status"] != "idle":
        return False, (
            f"SDR2 is niet vrij.\n"
            f"Status : {current_state['status']}\n"
            f"Process: {current_state['process']}"
        )

    device = get_device("sdr1")

    if device is None:
        return False, "Geen dynamische SDR gevonden."

    if not device.get("serial"):
        return False, "Dynamische SDR heeft geen serienummer."

    return True, "OK"


def build_record_command():
    allowed, reason = check_recording_allowed()

    if not allowed:
        return {
            "allowed": False,
            "reason": reason,
        }

    next_pass = passes.get_next_pass()

    if next_pass is None:
        return None

    device = get_device("sdr1")

    start_local = next_pass["start"].astimezone(LOCAL_TZ)
    safe_name = next_pass["name"].replace(" ", "_").replace("/", "_")
    folder_name = f"{start_local.strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    output_path = OUTPUT_DIR / folder_name

    duration = next_pass["end"] - next_pass["start"]
    timeout_seconds = int(duration.total_seconds()) + 60

    command = [
        "satdump",
        "live",
        next_pass["pipeline"],
        str(output_path),
        "--source",
        "rtlsdr",
        "--serial",
        device["serial"],
        "--frequency",
        str(next_pass["frequency"]),
        "--samplerate",
        str(next_pass["sample_rate"]),
        "--timeout",
        str(timeout_seconds),
    ]

    return {
        "allowed": True,
        "reason": "OK",
        "pass": next_pass,
        "device": device,
        "output_path": output_path,
        "timeout_seconds": timeout_seconds,
        "command": command,
    }


def print_record_preview():
    data = build_record_command()

    print("SatDump record preview")
    print("-----------------------------")

    if data is None:
        print("Geen geschikte passage gevonden.")
        return

    if not data["allowed"]:
        print("Opname niet toegestaan.")
        print()
        print(data["reason"])
        return

    _print_record_data(data)


def simulate_record():
    data = build_record_command()

    print("SatDump simulation")
    print("-----------------------------")

    if data is None:
        print("Geen geschikte passage gevonden.")
        return

    if not data["allowed"]:
        print("Simulatie niet toegestaan.")
        print()
        print(data["reason"])
        return

    data["output_path"].mkdir(parents=True, exist_ok=True)

    print("Checks")
    print("  Profile   : OK")
    print("  SDR2      : OK")
    print("  Output dir: OK")
    print()

    _print_record_data(data)


def service_is_active(service_name):
    result = subprocess.run(
        ["systemctl", "is-active", service_name],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "active"


def set_service_state(service_name, action):
    result = subprocess.run(
        ["sudo", "-n", "systemctl", action, service_name],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(
            f"Serviceactie mislukt: {action} {service_name}"
        )

        if result.stdout.strip():
            print("STDOUT:", result.stdout.strip())

        if result.stderr.strip():
            print("STDERR:", result.stderr.strip())

        return False

    return True


def wait_for_service_stopped(service_name, timeout=15):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if not service_is_active(service_name):
            return True

        time.sleep(0.5)

    return False


def record_now():
    data = build_record_command()

    print("SatDump recording")
    print("-----------------------------")

    if data is None:
        print("Geen geschikte passage gevonden.")
        return False

    if not data["allowed"]:
        print("Opname niet toegestaan.")
        print()
        print(data["reason"])
        return False

    data["output_path"].mkdir(parents=True, exist_ok=True)

    ais_was_active = service_is_active("ais-catcher.service")

    print("Preparing Weather receiver...")
    print("-----------------------------")
    print("Recorder     :", data["device"]["name"])
    print("Serial       :", data["device"]["serial"])
    print("ADS-B        : blijft actief op SDR2")
    print("AIS actief   :", "YES" if ais_was_active else "NO")

    if ais_was_active:
        print()
        print("Stopping AIS-Catcher...")

        if not set_service_state("ais-catcher.service", "stop"):
            return False

        if not wait_for_service_stopped("ais-catcher.service"):
            print("AIS-Catcher stopte niet volledig.")
            return False

    # Geef libusb tijd om SDR1 vrij te geven.
    time.sleep(2)

    print()
    print("Starting SatDump...")
    _print_record_data(data)

    try:
        result = subprocess.run(data["command"])
        success = result.returncode == 0

        print()
        print("SatDump finished")
        print("-----------------------------")
        print("Result :", "OK" if success else "FAILED")
        print("Code   :", result.returncode)

        return success

    finally:
        print()
        print("Restoring receiver services...")
        print("-----------------------------")

        if ais_was_active:
            print("Starting AIS-Catcher...")
            set_service_state("ais-catcher.service", "start")

        # SDR2 bleef tijdens de hele opname ADS-B draaien.
        state.set_sdr2_state(
            status="idle",
            profile="adsb",
            locked=False,
            process=None,
        )


def _print_record_data(data):
    pass_data = data["pass"]

    print("Satellite  :", pass_data["name"])
    print("Frequency  :", f"{pass_data['frequency'] / 1e6:.3f} MHz")
    print("Mode       :", pass_data["mode"])
    print("Pipeline   :", pass_data["pipeline"])
    print("SampleRate :", pass_data["sample_rate"])
    print("Recorder   :", data["device"]["name"])
    print("Serial     :", data["device"]["serial"])
    print("Output     :", data["output_path"])

    if "timeout_seconds" in data:
        print("Timeout    :", f"{data['timeout_seconds']} seconds")

    print()
    print("Command:")
    print(" ".join(data["command"]))
