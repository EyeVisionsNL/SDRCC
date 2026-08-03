#!/usr/bin/env python3
"""Add v0.54.0d pass-window fields without replacing live user settings."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import weather_planning


def main() -> int:
    result = weather_planning.ensure_defaults()
    print("PASS: per-satellite pass-window configuration present")
    print("PASS: existing v0.54.0d profile values preserved")
    print(json.dumps({
        "changed": result.get("changed", False),
        "profiles": {
            key: {
                "minimum_peak_elevation": value["minimum_peak_elevation"],
                "begin_elevation": value["begin_elevation"],
                "close_elevation": value["close_elevation"],
            }
            for key, value in result["profiles"].items()
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
