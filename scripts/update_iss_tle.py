#!/usr/bin/env python3
"""Download and validate the current ISS TLE from CelesTrak."""

from __future__ import annotations

import argparse
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "tle" / "iss.tle"


def validate_tle(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError("CelesTrak gaf geen geldig drie-regelig ISS TLE-blok terug")

    name, line1, line2 = lines[:3]
    if not line1.startswith("1 25544") or not line2.startswith("2 25544"):
        raise ValueError("Ontvangen TLE hoort niet bij NORAD 25544 (ISS)")

    # Keep the canonical name expected by voice_targets.yaml.
    return "ISS (ZARYA)\n" + line1 + "\n" + line2 + "\n"


def update_tle(output: Path, url: str = DEFAULT_URL, timeout: int = 20) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "SDRCC/0.28 ISS TLE updater"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8", errors="strict")

    normalized = validate_tle(content)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output.parent,
        prefix=".iss.tle.",
        delete=False,
    ) as handle:
        handle.write(normalized)
        temp_path = Path(handle.name)

    temp_path.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    path = update_tle(args.output, args.url)
    print(f"ISS TLE bijgewerkt: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
