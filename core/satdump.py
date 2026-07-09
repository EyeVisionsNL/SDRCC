#!/usr/bin/env python3

from pathlib import Path
from zoneinfo import ZoneInfo

from core import passes
from core.device_manager import get_dynamic_device

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "recordings"


def build_record_command():
    next_pass = passes.get_next_pass()

    if next_pass is None:
        return None

    device = get_dynamic_device()

    if device is None:
        raise RuntimeError("Geen vrije SDR gevonden.")

    start_local = next_pass["start"].astimezone(LOCAL_TZ)

    safe_name = (
        next_pass["name"]
        .replace(" ", "_")
        .replace("/", "_")
    )

    folder_name = (
        f"{start_local.strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    )

    output_path = OUTPUT_DIR / folder_name

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
    ]

    return {
        "pass": next_pass,
        "device": device,
        "output_path": output_path,
        "command": command,
    }


def print_record_preview():
    data = build_record_command()

    print("SatDump record preview")
    print("-----------------------------")

    if data is None:
        print("Geen geschikte passage gevonden.")
        return

    pass_data = data["pass"]

    print("Satellite  :", pass_data["name"])
    print("Frequency  :", f"{pass_data['frequency'] / 1e6:.3f} MHz")
    print("Mode       :", pass_data["mode"])
    print("Pipeline   :", pass_data["pipeline"])
    print("SampleRate :", pass_data["sample_rate"])

    print("Recorder   :", data["device"]["name"])
    print("Serial     :", data["device"]["serial"])

    print("Output     :", data["output_path"])

    print()
    print("Command:")
    print(" ".join(data["command"]))
