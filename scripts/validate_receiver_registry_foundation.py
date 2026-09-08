#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import config
from core import device_manager
from core import receiver_registry


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main():
    snapshot = receiver_registry.public_snapshot()
    receivers = snapshot["receivers"]
    check(snapshot["authority"] == "static_identity_only", "registry heeft alleen statische identity-authority")
    check(snapshot["runtime_state_in_registry"] is False, "runtime-status staat niet in de registry")
    check(len(receivers) >= 1, "minimaal één receiver aanwezig")
    check(len({r["id"] for r in receivers}) == len(receivers), "neutrale receiver-ID's zijn uniek")
    check(len({r["serial"] for r in receivers if r["serial"]}) == sum(bool(r["serial"]) for r in receivers), "serienummers zijn uniek")
    check(all(r["id"].startswith("receiver") for r in receivers), "gemigreerde IDs zijn neutraal")

    runtime_ids = receiver_registry.get_receiver_ids(compatibility=True)
    assignments = config.get_receiver_assignments()
    check(all(value is None or value in runtime_ids for value in assignments.values()), "assignments verwijzen naar geldige receivers")

    devices = device_manager.get_devices()
    check(len(devices) == snapshot["enabled_count"], "Device Manager leest de centrale registry")
    check(all(d.get("registry_id") for d in devices), "Device Manager publiceert registry_id")
    check(all(d.get("serial") == receiver_registry.get_receiver(d["registry_id"])["serial"] for d in devices), "Device Manager haalt serienummers uit de registry")

    station = config.load_station()
    legacy_identity_blocks = [
        key for key, value in station.items()
        if str(key).lower().startswith("sdr") and isinstance(value, dict) and "serial" in value
    ]
    check(not legacy_identity_blocks, "station.yaml bevat geen dubbele receiver-identiteit")

    # Prove that the registry is not tied to this station's serial numbers or to two devices.
    with TemporaryDirectory() as temp_dir:
        test_file = Path(temp_dir) / "receivers.yaml"
        test_file.write_text(yaml.safe_dump({
            "version": 1,
            "receivers": {
                "roof_rx": {
                    "name": "Roof receiver",
                    "hardware": {"driver": "rtlsdr", "serial": "OTHER-1001"},
                    "capabilities": ["weather"],
                },
                "voice_rx": {
                    "name": "Voice receiver",
                    "hardware": {"driver": "airspy", "serial": "OTHER-2002"},
                    "capabilities": ["iss_voice"],
                },
                "service_rx": {
                    "name": "Service receiver",
                    "hardware": {"driver": "rtlsdr", "serial": "OTHER-3003"},
                    "capabilities": ["ais", "adsb"],
                },
            },
        }, sort_keys=False), encoding="utf-8")
        original = receiver_registry.REGISTRY_FILE
        receiver_registry.REGISTRY_FILE = test_file
        try:
            generic = receiver_registry.get_receivers()
            check(len(generic) == 3, "registry ondersteunt een dynamisch aantal receivers")
            check({r["serial"] for r in generic} == {"OTHER-1001", "OTHER-2002", "OTHER-3003"}, "andere serienummers werken zonder codewijziging")
            check({r["driver"] for r in generic} == {"rtlsdr", "airspy"}, "datamodel is niet RTL-SDR-specifiek")
        finally:
            receiver_registry.REGISTRY_FILE = original

    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print("VALIDATION PASS")


if __name__ == "__main__":
    main()
