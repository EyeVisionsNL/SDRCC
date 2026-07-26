#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import sys
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATION_FILE = PROJECT_ROOT / "config" / "station.yaml"
REGISTRY_FILE = PROJECT_ROOT / "config" / "receivers.yaml"


def load(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save(path: Path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)
    temp.replace(path)


def main() -> int:
    station = load(STATION_FILE)
    if REGISTRY_FILE.exists():
        print(f"Receiver registry bestaat al: {REGISTRY_FILE}")
        return 0

    legacy_ids = [key for key in station if str(key).lower().startswith("sdr") and isinstance(station[key], dict) and station[key].get("serial")]
    if not legacy_ids:
        raise RuntimeError("Geen legacy receiverblokken met serienummers gevonden in station.yaml")

    assignments = station.get("assignments") or {}
    mission_assignments = station.get("mission_assignments") or {}
    defaults = station.get("receiver_defaults") or {}

    receivers = {}
    for index, legacy_id in enumerate(legacy_ids, start=1):
        item = station[legacy_id]
        capabilities = []
        for role, assigned in {**assignments, **mission_assignments}.items():
            if assigned == legacy_id and role not in capabilities:
                capabilities.append(str(role))
        for role in defaults.get(legacy_id, []) or []:
            if role not in capabilities:
                capabilities.append(str(role))
        if "weather" in capabilities and "live_rf" not in capabilities:
            capabilities.append("live_rf")
        if any(role in capabilities for role in ("weather", "iss_voice")) and "recording" not in capabilities:
            capabilities.append("recording")

        receiver_id = f"receiver{index:02d}"
        receivers[receiver_id] = {
            "name": str(item.get("name") or f"Receiver {index}"),
            "description": "Migrated from station.yaml",
            "number": f"RX{index:02d}",
            "enabled": True,
            "hardware": {
                "driver": "rtlsdr",
                "serial": str(item.get("serial")),
            },
            "aliases": [str(legacy_id).lower()],
            "capabilities": capabilities,
            "defaults": {"locked": bool(item.get("locked", False))},
        }

    registry = {
        "version": 1,
        "receivers": receivers,
    }
    save(REGISTRY_FILE, registry)

    # Static receiver identity has moved to receivers.yaml. Assignments and all
    # runtime policy deliberately remain in station.yaml.
    for legacy_id in legacy_ids:
        station.pop(legacy_id, None)
    save(STATION_FILE, station)

    print(f"Receiver registry gemaakt: {REGISTRY_FILE}")
    print(f"Gemigreerde receivers: {len(receivers)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"MIGRATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
