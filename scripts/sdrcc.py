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
from core import profiles
from core import rtl
from core import satdump
from core import satellites
from core import state
from core import system
from core import tle

VERSION = "0.3.7"


def print_header():
    print(f"\nSDR Control Center v{VERSION}")
    print("=" * 40)


def print_help():
    print("Gebruik:")
    print("  python3 scripts/sdrcc.py status")
    print("  python3 scripts/sdrcc.py doctor")
    print("  python3 scripts/sdrcc.py devices")
    print("  python3 scripts/sdrcc.py state")
    print("  python3 scripts/sdrcc.py profiles")
    print("  python3 scripts/sdrcc.py satellites")
    print("  python3 scripts/sdrcc.py meteor")
    print("  python3 scripts/sdrcc.py tle")
    print("  python3 scripts/sdrcc.py update-tle")
    print("  python3 scripts/sdrcc.py next")
    print("  python3 scripts/sdrcc.py schedule")
    print("  python3 scripts/sdrcc.py record-next")
    print("  python3 scripts/sdrcc.py help")


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
    profiles.print_profiles()
    print()
    satellites.print_satellites()
    print()
    meteor.print_satellites()
    print()
    tle.status()


def devices_cmd():
    logger.info("Listing SDR devices")
    print_header()
    device_manager.print_devices()


def state_cmd():
    logger.info("Showing SDR2 state")
    print_header()
    state.print_sdr2_state()


def profiles_cmd():
    logger.info("Listing profiles")
    print_header()
    profiles.print_profiles()


def satellites_cmd():
    logger.info("Listing satellites")
    print_header()
    satellites.print_satellites()


def meteor_cmd():
    logger.info("Listing configured METEOR satellites")
    print_header()
    meteor.print_satellites()


def tle_cmd():
    logger.info("Checking TLE database")
    print_header()
    tle.status()


def update_tle_cmd():
    logger.info("Updating TLE database")
    print_header()
    downloader.download_tle()
    print()
    tle.status()


def next_cmd():
    logger.info("Calculating next pass")
    print_header()
    passes.print_next_pass()


def schedule_cmd():
    logger.info("Calculating schedule")
    print_header()
    passes.print_schedule()


def record_next_cmd():
    logger.info("Showing SatDump record preview")
    print_header()
    satdump.print_record_preview()


def main():
    logger.info("SDRCC started")

    if len(sys.argv) < 2:
        print_help()
        return

    command = sys.argv[1].lower()
    logger.info(f"Command executed: {command}")

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
    elif command == "help":
        print_help()
    else:
        logger.warning(f"Unknown command: {command}")
        print(f"Onbekend commando: {command}")
        print()
        print_help()


if __name__ == "__main__":
    main()
