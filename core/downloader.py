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
