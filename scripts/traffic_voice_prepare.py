#!/usr/bin/env python3
"""Render the current dynamic Marine Voice backend configuration atomically."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import traffic_voice


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    allowed_root = Path("/run/sdrcc-traffic-voice").resolve()
    try:
        output.relative_to(allowed_root)
    except ValueError as error:
        raise SystemExit("output must remain under /run/sdrcc-traffic-voice") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(traffic_voice.render_rtlsdr_airband_config())
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
