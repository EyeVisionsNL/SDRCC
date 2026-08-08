#!/usr/bin/env python3
"""Repair only the incorrect v0.54.0h-r1 METEOR default.

All other operator-selected frequencies are preserved. Future changes are made
through the per-satellite controls in Mission Planner.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import os

import yaml


R1_FORCED_VALUES = {
    "METEOR-M2 3": 137_100_000,
    "METEOR-M2 4": 137_900_000,
}
CORRECTED_PRIMARY_VALUES = {
    "METEOR-M2 3": 137_900_000,
    "METEOR-M2 4": 137_900_000,
}


def migrate(config_file: Path) -> tuple[bool, dict[str, int], str]:
    document = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    satellites = document.get("satellites")
    if not isinstance(satellites, dict):
        raise ValueError("config/satellites.yaml mist een satellites mapping")
    current = {}
    for name in R1_FORCED_VALUES:
        profile = satellites.get(name)
        if not isinstance(profile, dict):
            raise ValueError(f"Satellietprofiel ontbreekt: {name}")
        current[name] = int(profile.get("frequency") or 0)
    changed = current == R1_FORCED_VALUES
    reason = "repaired v0.54.0h-r1 forced M2-3 default" if changed else "preserved operator selections"
    if changed:
        satellites["METEOR-M2 3"]["frequency"] = CORRECTED_PRIMARY_VALUES["METEOR-M2 3"]
    if changed:
        temporary = config_file.with_suffix(".yaml.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(document, handle, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, config_file.stat().st_mode & 0o777)
            temporary.replace(config_file)
            directory_fd = os.open(config_file.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
    values = {
        name: int(satellites[name]["frequency"])
        for name in R1_FORCED_VALUES
    }
    return changed, values, reason


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    changed, values, reason = migrate(args.root / "config" / "satellites.yaml")
    state = "updated" if changed else "unchanged"
    print(
        f"PASS: METEOR RF profiles {state} ({reason}); "
        f"M2-3={values['METEOR-M2 3']} Hz, M2-4={values['METEOR-M2 4']} Hz"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
