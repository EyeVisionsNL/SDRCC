#!/usr/bin/env python3

import sys
from pathlib import Path

# Voeg de projectmap toe aan het Python-pad
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import logger
from core import rtl
from core import satellites
from core import system

VERSION = "0.2.3"


def print_header():
    print(f"\nSDR Control Center v{VERSION}")
    print("=" * 40)


def print_help():
    print("Gebruik:")
    print("  python3 scripts/sdrcc.py status")
    print("  python3 scripts/sdrcc.py doctor")
    print("  python3 scripts/sdrcc.py satellites")
    print("  python3 scripts/sdrcc.py help")


def status():
    logger.info("Running status")

    print_header()
    system.print_system()

    print()
    rtl.print_status()


def doctor():
    logger.info("Running doctor")

    print_header()
    system.print_system()

    print()
    rtl.print_status()

    print()
    satellites.print_satellites()


def satellites_cmd():
    logger.info("Listing satellites")

    print_header()
    satellites.print_satellites()


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

    elif command == "satellites":
        satellites_cmd()

    elif command == "help":
        print_help()

    else:
        logger.warning(f"Unknown command: {command}")
        print(f"Onbekend commando: {command}")
        print()
        print_help()


if __name__ == "__main__":
    main()
