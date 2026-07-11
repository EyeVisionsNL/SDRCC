#!/usr/bin/env python3

from pathlib import Path
from zoneinfo import ZoneInfo
import subprocess
import time

from core import passes
from core import config as config_core
from core import process_manager
from core import state
from core.device_manager import get_conflicting_service, get_weather_device

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "recordings"


def check_recording_allowed():
    current_state = state.get_sdr2_state()
    device = get_weather_device()

    if current_state["profile"] not in {"weather", "adsb"}:
        return False, (
            f"SDR2 staat nu op profiel '{current_state['profile']}'.\n"
            "Opnemen is alleen toegestaan vanuit het profiel "
            "weather of adsb."
        )

    if device and device["id"] == "sdr2" and current_state["locked"]:
        return False, "SDR2 is gelocked en mag nu niet gebruikt worden."

    if device and device["id"] == "sdr2" and current_state["status"] != "idle":
        return False, (
            f"SDR2 is niet vrij.\n"
            f"Status : {current_state['status']}\n"
            f"Process: {current_state['process']}"
        )

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

    device = get_weather_device()

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

    rf = config_core.get_weather_rf_config()
    if rf["gain_mode"] == "manual":
        command.extend(["--gain", str(rf["gain_db"])])
    if rf["dc_block"]:
        command.append("--dc_block")
    if rf["iq_swap"]:
        command.append("--iq_swap")

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

    conflict_service = get_conflicting_service(data["device"]["id"])
    conflict_was_active = bool(conflict_service and service_is_active(conflict_service))

    print("Preparing Weather receiver...")
    print("-----------------------------")
    print("Recorder     :", data["device"]["name"])
    print("Serial       :", data["device"]["serial"])
    print("Conflict     :", conflict_service or "geen")

    if conflict_was_active:
        print()
        print(f"Stopping {conflict_service}...")
        if not set_service_state(conflict_service, "stop"):
            return False
        if not wait_for_service_stopped(conflict_service):
            print(f"{conflict_service} stopte niet volledig.")
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

        if conflict_was_active and conflict_service:
            print(f"Starting {conflict_service}...")
            set_service_state(conflict_service, "start")

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


def analyze_satdump_result(returncode, stdout="", stderr="", output_path=None):
    """Classificeer SatDump en lever een compacte missiesamenvatting."""
    import re

    combined = f"{stdout or ''}\n{stderr or ''}"
    upper = combined.upper()

    cadu_bytes = 0
    image_count = 0
    if output_path:
        output_dir = Path(output_path)
        if output_dir.exists():
            cadu_bytes = sum(
                item.stat().st_size
                for item in output_dir.rglob("*.cadu")
                if item.is_file()
            )
            image_count = sum(
                1
                for pattern in ("*.png", "*.jpg", "*.jpeg")
                for item in output_dir.rglob(pattern)
                if item.is_file()
            )

    cadu_size = 8192
    frames = cadu_bytes // cadu_size

    snr_values = [
        float(value)
        for value in re.findall(r"SNR\s*:\s*(-?\d+(?:\.\d+)?)\s*DB", upper)
    ]
    peak_snr = max(snr_values) if snr_values else None

    metrics = {
        "peak_snr_db": peak_snr,
        "frames": frames,
        "cadu_bytes": cadu_bytes,
        "image_count": image_count,
    }

    if returncode != 0:
        detail = f"SatDump stopte met foutcode {returncode}"
        return {
            "success": False,
            "result": "FAILED",
            "detail": detail,
            "error": detail,
            **metrics,
        }

    if cadu_bytes > 0 or "DEFRAMER : SYNC" in upper:
        detail = (
            f"Decode voltooid; {frames} frames, "
            f"{cadu_bytes} bytes CADU-data, {image_count} afbeelding(en)"
        )
        return {
            "success": True,
            "result": "SUCCESS",
            "detail": detail,
            "error": None,
            **metrics,
        }

    if "NOSYNC" in upper and peak_snr is not None:
        return {
            "success": False,
            "result": "NO SYNC",
            "detail": (
                "Signaal gezien, maar geen decoder-lock; "
                f"piek-SNR {peak_snr:.2f} dB, 0 frames"
            ),
            "error": None,
            **metrics,
        }

    return {
        "success": False,
        "result": "NO SIGNAL",
        "detail": "Geen bruikbaar LRPT-signaal, frames of afbeeldingen gevonden",
        "error": None,
        **metrics,
    }

