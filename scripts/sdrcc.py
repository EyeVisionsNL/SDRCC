#!/usr/bin/env python3

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import device_manager
from core import downloader
from core import meteor
from core import passes
from core import process_manager
from core import profiles
from core import rtl
from core import satdump
from core import satellites
from core import state
from core import system
from core import tle

VERSION = "0.4.0"


def print_header():
    print(f"\nSDR Control Center v{VERSION}")
    print("=" * 40)


def print_help():
    print("Gebruik:")
    print("  sdrcc status")
    print("  sdrcc doctor")
    print("  sdrcc devices")
    print("  sdrcc state")
    print("  sdrcc profiles")
    print("  sdrcc profile <naam>")
    print("  sdrcc processes")
    print("  sdrcc adsb-stop-preview")
    print("  sdrcc adsb-start-preview")
    print("  sdrcc adsb-stop")
    print("  sdrcc adsb-start")
    print("  sdrcc satellites")
    print("  sdrcc meteor")
    print("  sdrcc tle")
    print("  sdrcc update-tle")
    print("  sdrcc next")
    print("  sdrcc schedule")
    print("  sdrcc record-next")
    print("  sdrcc simulate-record")
    print("  sdrcc record")
    print("  sdrcc help")


def status():
    print_header()
    system.print_system()
    print()
    rtl.print_status()
    print()
    state.print_sdr2_state()


def doctor():
    print_header()
    system.print_system()
    print()
    rtl.print_status()
    print()
    device_manager.print_devices()
    print()
    state.print_sdr2_state()
    print()
    process_manager.print_process_status()
    print()
    profiles.print_profiles()
    print()
    satellites.print_satellites()
    print()
    meteor.print_satellites()
    print()
    tle.status()


def profile_cmd(profile_name):
    print_header()
    try:
        profile = profiles.set_active_profile(profile_name)
    except ValueError as err:
        print(err)
        print()
        profiles.print_profiles()
        return

    print("Active profile changed")
    print("-----------------------------")
    print("Profile :", profile_name)
    print("Name    :", profile["name"])
    print("Device  :", profile["device"])
    print()
    state.print_sdr2_state()


def main():
    if len(sys.argv) < 2:
        print_help()
        return

    command = sys.argv[1].lower()

    if command == "status":
        status()
    elif command == "doctor":
        doctor()
    elif command == "devices":
        print_header(); device_manager.print_devices()
    elif command == "state":
        print_header(); state.print_sdr2_state()
    elif command == "profiles":
        print_header(); profiles.print_profiles()
    elif command == "profile":
        if len(sys.argv) < 3:
            print("Gebruik: sdrcc profile <naam>")
            return
        profile_cmd(sys.argv[2].lower())
    elif command == "processes":
        print_header(); process_manager.print_process_status()
    elif command == "adsb-stop-preview":
        print_header(); process_manager.preview_stop("adsb")
    elif command == "adsb-start-preview":
        print_header(); process_manager.preview_start("adsb")
    elif command == "adsb-stop":
        print_header(); process_manager.stop_profile("adsb")
    elif command == "adsb-start":
        print_header(); process_manager.start_profile("adsb")
    elif command == "satellites":
        print_header(); satellites.print_satellites()
    elif command == "meteor":
        print_header(); meteor.print_satellites()
    elif command == "tle":
        print_header(); tle.status()
    elif command == "update-tle":
        print_header(); downloader.download_tle(); print(); tle.status()
    elif command == "next":
        print_header(); passes.print_next_pass()
    elif command == "schedule":
        print_header(); passes.print_schedule()
    elif command == "record-next":
        print_header(); satdump.print_record_preview()
    elif command == "simulate-record":
        print_header(); satdump.simulate_record()
    elif command == "record":
        print_header()
        success = satdump.record_now()
        raise SystemExit(0 if success else 1)
    elif command == "help":
        print_help()
    else:
        print(f"Onbekend commando: {command}")
        print()
        print_help()


if __name__ == "__main__":
    main()
