#!/usr/bin/env python3

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import device_manager
from core import downloader
from core import logger
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

VERSION = "0.3.11"


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
    print("  sdrcc satellites")
    print("  sdrcc meteor")
    print("  sdrcc tle")
    print("  sdrcc update-tle")
    print("  sdrcc next")
    print("  sdrcc schedule")
    print("  sdrcc record-next")
    print("  sdrcc simulate-record")
    print("  sdrcc help")


def status():
    logger.info("Running status")
    print_header()
    system.print_system()
    print()
    rtl.print_status()
    print()
    state.print_sdr2_state()


def doctor():
    logger.info("Running doctor")
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


def devices_cmd():
    print_header()
    device_manager.print_devices()


def state_cmd():
    print_header()
    state.print_sdr2_state()


def profiles_cmd():
    print_header()
    profiles.print_profiles()


def processes_cmd():
    print_header()
    process_manager.print_process_status()


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


def satellites_cmd():
    print_header()
    satellites.print_satellites()


def meteor_cmd():
    print_header()
    meteor.print_satellites()


def tle_cmd():
    print_header()
    tle.status()


def update_tle_cmd():
    print_header()
    downloader.download_tle()
    print()
    tle.status()


def next_cmd():
    print_header()
    passes.print_next_pass()


def schedule_cmd():
    print_header()
    passes.print_schedule()


def record_next_cmd():
    print_header()
    satdump.print_record_preview()


def simulate_record_cmd():
    print_header()
    satdump.simulate_record()


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
        devices_cmd()
    elif command == "state":
        state_cmd()
    elif command == "profiles":
        profiles_cmd()
    elif command == "profile":
        if len(sys.argv) < 3:
            print("Gebruik: sdrcc profile <naam>")
            return
        profile_cmd(sys.argv[2].lower())
    elif command == "processes":
        processes_cmd()
    elif command == "satellites":
        satellites_cmd()
    elif command == "meteor":
        meteor_cmd()
    elif command == "tle":
        tle_cmd()
    elif command == "update-tle":
        update_tle_cmd()
    elif command == "next":
        next_cmd()
    elif command == "schedule":
        schedule_cmd()
    elif command == "record-next":
        record_next_cmd()
    elif command == "simulate-record":
        simulate_record_cmd()
    elif command == "help":
        print_help()
    else:
        print(f"Onbekend commando: {command}")
        print()
        print_help()


if __name__ == "__main__":
    main()
