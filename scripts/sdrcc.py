#!/usr/bin/env python3

import sys
from pathlib import Path

# Voeg de projectmap toe aan het Python-pad
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import rtl

VERSION = "0.2.0"


def main():
    if len(sys.argv) < 2:
        print("Gebruik:")
        print("  python3 scripts/sdrcc.py status")
        return

    command = sys.argv[1].lower()

    if command == "status":
        print(f"\nSDR Control Center v{VERSION}")
        print("=" * 40)
        rtl.print_status()
    else:
        print(f"Onbekend commando: {command}")


if __name__ == "__main__":
    main()
