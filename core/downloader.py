#!/usr/bin/env python3

from pathlib import Path
import requests

TLE_DIR = Path(__file__).resolve().parent.parent / "data" / "tle"
TLE_DIR.mkdir(parents=True, exist_ok=True)

TLE_FILE = TLE_DIR / "weather.tle"

# We halen alle actieve weather satellites op.
# Later filteren we alleen METEOR-M2-3 en METEOR-M2-4.
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle"


def download_tle():

    print("Downloading TLE database...")

    response = requests.get(TLE_URL, timeout=20)
    response.raise_for_status()

    with open(TLE_FILE, "w") as f:
        f.write(response.text)

    print("Download complete")
    print(TLE_FILE)

ISS_TLE_FILE = TLE_DIR / "iss.tle"
ISS_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"


def download_iss_tle():
    """Download the current ISS TLE atomically from CelesTrak."""
    response = requests.get(ISS_TLE_URL, timeout=20)
    response.raise_for_status()
    lines = [line.strip() for line in response.text.splitlines() if line.strip()]
    if len(lines) < 3 or not lines[1].startswith("1 25544") or not lines[2].startswith("2 25544"):
        raise ValueError("Downloaded ISS TLE is invalid")
    temp = ISS_TLE_FILE.with_suffix(".tle.tmp")
    temp.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")
    temp.replace(ISS_TLE_FILE)
    return ISS_TLE_FILE
