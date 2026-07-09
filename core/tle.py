#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime

TLE_DIR = Path(__file__).resolve().parent.parent / "data" / "tle"
TLE_FILE = TLE_DIR / "weather.tle"


def exists():
    """Controleer of het TLE-bestand bestaat."""
    return TLE_FILE.exists()


def last_update():
    """Geef de laatste wijzigingsdatum terug."""
    if not exists():
        return None

    timestamp = TLE_FILE.stat().st_mtime
    return datetime.fromtimestamp(timestamp)


def age_hours():
    """Leeftijd van het TLE-bestand in uren."""
    if not exists():
        return None

    delta = datetime.now() - last_update()
    return round(delta.total_seconds() / 3600, 1)


def status():

    print("TLE Database")
    print("----------------")

    if not exists():
        print("Status : Missing")
        print("File   :", TLE_FILE)
        return

    print("Status : Present")
    print("File   :", TLE_FILE)
    print("Updated:", last_update().strftime("%Y-%m-%d %H:%M:%S"))
    print("Age    :", f"{age_hours()} hours")
