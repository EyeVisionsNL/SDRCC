#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.downloader import download_iss_tle

path = download_iss_tle()
print(f"ISS TLE updated: {path}")
