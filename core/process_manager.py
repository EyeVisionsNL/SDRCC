#!/usr/bin/env python3

import subprocess

from core import profiles


def run_command(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )

        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    except Exception as error:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(error),
        }


def systemd_is_active(service_name):
    if not service_name:
        return False

    result = run_command(["systemctl", "is-active", service_name])
    return result["stdout"] == "active"


def process_contains(text):
    result = run_command(["pgrep", "-af", text])
    return result["stdout"]


def get_profile_process_status(profile_name):
    profile = profiles.get_profile(profile_name)

    if not profile:
        return None

    service = profile.get("service")

    active = False
    process = ""

    if service:
        active = systemd_is_active(service)

    if service == "readsb.service":
        process = process_contains("readsb")

    return {
        "profile": profile_name,
        "name": profile.get("name"),
        "service": service,
        "active": active,
        "process": process,
        "start": profile.get("start", []),
        "stop": profile.get("stop", []),
    }


def readsb_status():
    return get_profile_process_status("adsb")


def print_process_status():
    adsb = readsb_status()

    print("Processes")
    print("-----------------------------")

    if adsb is None:
        print("ADS-B profiel niet gevonden.")
        return

    print("Profile :", adsb["name"])
    print("Service :", adsb["service"])
    print("Status  :", "RUNNING" if adsb["active"] else "STOPPED")

    print()
    print("Configured commands")
    print("  Start :", " ".join(adsb["start"]) if adsb["start"] else "-")
    print("  Stop  :", " ".join(adsb["stop"]) if adsb["stop"] else "-")

    if adsb["process"]:
        print()
        print("Process:")
        print(adsb["process"])


def preview_stop(profile_name):
    profile = get_profile_process_status(profile_name)

    print("Stop preview")
    print("-----------------------------")

    if profile is None:
        print("Profiel niet gevonden.")
        return

    if not profile["stop"]:
        print("Geen stopcommando geconfigureerd.")
        return

    print("Would execute:")
    print(" ", " ".join(profile["stop"]))


def preview_start(profile_name):
    profile = get_profile_process_status(profile_name)

    print("Start preview")
    print("-----------------------------")

    if profile is None:
        print("Profiel niet gevonden.")
        return

    if not profile["start"]:
        print("Geen startcommando geconfigureerd.")
        return

    print("Would execute:")
    print(" ", " ".join(profile["start"]))
