#!/usr/bin/env python3
"""Regression tests for station Home Position -> readsb synchronisation."""

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "readsb_position",
    ROOT / "scripts/sdrcc_sync_readsb_position.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def check(label, condition):
    if not condition:
        raise SystemExit(f"FAIL: {label}")
    print(f"PASS: {label}")


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "readsb"
    path.write_text(
        'RECEIVER_OPTIONS="--device-type rtlsdr --device 24006572 --gain auto"\n'
        'DECODER_OPTIONS="--max-range 300 --lat 1.000000 --lon 2.000000 --write-json-every 1"\n'
    )

    before_receiver = path.read_text().splitlines()[0]

    changed = module.sync_file(path, 51.9126, 4.3417)
    text = path.read_text()

    check("existing readsb configuration changed", changed)
    check(
        "ADS-B dongle serial preserved",
        text.splitlines()[0] == before_receiver,
    )
    check("--lat synchronized", "--lat 51.912600" in text)
    check("--lon synchronized", "--lon 4.341700" in text)
    check("old latitude removed", "--lat 1.000000" not in text)
    check("old longitude removed", "--lon 2.000000" not in text)
    check("other decoder options preserved", "--max-range 300" in text)
    check("JSON option preserved", "--write-json-every 1" in text)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "readsb"
    path.write_text(
        'RECEIVER_OPTIONS="--device-type rtlsdr --device UNBOUND_ADSB --gain auto"\n'
    )

    module.sync_file(path, 51.0, 4.0)
    text = path.read_text()

    check(
        "DECODER_OPTIONS created when missing",
        'DECODER_OPTIONS="--lat 51.000000 --lon 4.000000"' in text,
    )
    check("UNBOUND_ADSB preserved", "--device UNBOUND_ADSB" in text)


print("PASS: readsb Home Position regression suite")
