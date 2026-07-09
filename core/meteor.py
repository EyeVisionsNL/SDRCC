#!/usr/bin/env python3

from pathlib import Path
from core.config import get_enabled_satellites

TLE_FILE = Path(__file__).resolve().parent.parent / "data" / "tle" / "weather.tle"


def get_all_tle_names():
    satellites = []

    if not TLE_FILE.exists():
        return satellites

    with open(TLE_FILE, "r", encoding="utf-8") as file:
        lines = file.readlines()

    for i in range(0, len(lines), 3):
        if i < len(lines):
            name = lines[i].strip()
            if name:
                satellites.append(name)

    return satellites


def get_configured_meteors():
    tle_names = get_all_tle_names()
    enabled = get_enabled_satellites()

    found = []

    for name, config in enabled.items():
        if name in tle_names:
            found.append((name, config))

    return found


def print_satellites():
    found = get_configured_meteors()

    print("Configured weather satellites")
    print("-----------------------------")

    if not found:
        print("Geen geconfigureerde METEOR-satellieten gevonden in TLE.")
        return

    for name, config in found:
        print(f"✔ {name}")
        print(f"  Frequency : {config['frequency'] / 1e6:.3f} MHz")
        print(f"  Mode      : {config['mode']}")
        print(f"  Decoder   : {config['decoder']}")
        print(f"  Min Elev  : {config['min_elevation']}°")
        print()

    print(f"Totaal: {len(found)}")
