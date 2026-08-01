#!/usr/bin/env python3
"""Migrate SDRCC receiver role policy to one persistent assignments mapping."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent
STATION_FILE = ROOT / "config" / "station.yaml"
REGISTRY_FILE = ROOT / "config" / "receivers.yaml"
ROLES = ("weather", "ais", "adsb", "iss_voice")
REQUIRED_CAPABILITIES = (
    "weather",
    "ais",
    "adsb",
    "iss_voice",
    "live_rf",
    "recording",
)


def load_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} moet een YAML mapping zijn")
    return data


def registry_aliases(registry: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    receivers = registry.get("receivers")
    if not isinstance(receivers, dict) or not receivers:
        raise ValueError("Receiver Registry bevat geen receivers")
    aliases = {}
    serials = set()
    for canonical, receiver in receivers.items():
        if not isinstance(receiver, dict):
            raise ValueError(f"Receiver {canonical} is geen mapping")
        hardware = receiver.get("hardware") or {}
        serial = str(hardware.get("serial") or "").strip()
        if not serial or serial in serials:
            raise ValueError(f"Receiver {canonical} heeft geen uniek serienummer")
        serials.add(serial)
        receiver_aliases = receiver.get("aliases") or []
        if isinstance(receiver_aliases, str):
            receiver_aliases = [receiver_aliases]
        runtime_id = str(receiver_aliases[0] if receiver_aliases else canonical).strip().lower()
        aliases[str(canonical).strip().lower()] = runtime_id
        for alias in receiver_aliases:
            aliases[str(alias).strip().lower()] = runtime_id
    return aliases, receivers


def normalize_receiver(value: Any, aliases: dict[str, str]) -> str | None:
    if value in (None, "", "none", "null"):
        return None
    normalized = str(value).strip().lower()
    if normalized not in aliases:
        raise ValueError(f"Onbekende receiver in assignment: {value}")
    return aliases[normalized]


def build_migration(
    station: dict[str, Any],
    registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    aliases, receivers = registry_aliases(registry)
    raw_assignments = station.get("assignments") or {}
    if not isinstance(raw_assignments, dict):
        raise ValueError("assignments moet een mapping zijn")
    assignments = dict(raw_assignments)
    sources = {role: "assignments" for role in assignments if role in ROLES}

    legacy_missions = station.get("mission_assignments") or {}
    if isinstance(legacy_missions, dict):
        for role in ("weather", "iss_voice"):
            if role not in assignments and role in legacy_missions:
                assignments[role] = legacy_missions[role]
                sources[role] = "mission_assignments"

    legacy_defaults = station.get("receiver_defaults") or {}
    if isinstance(legacy_defaults, dict):
        for raw_receiver, raw_plugins in legacy_defaults.items():
            plugins = [raw_plugins] if isinstance(raw_plugins, str) else (raw_plugins or [])
            for plugin in plugins:
                role = str(plugin or "").strip().lower()
                if role in {"ais", "adsb"} and role not in assignments:
                    assignments[role] = raw_receiver
                    sources[role] = "receiver_defaults"

    for role in ROLES:
        if role not in assignments:
            raise ValueError(f"Assignment ontbreekt: {role}")
        assignments[role] = normalize_receiver(assignments[role], aliases)
        if assignments[role] is None:
            raise ValueError(f"Assignment mag niet leeg zijn: {role}")
    if assignments["ais"] == assignments["adsb"]:
        raise ValueError("AIS en ADS-B kunnen niet dezelfde receiver gebruiken")

    migrated_station = dict(station)
    migrated_station["assignments"] = assignments
    migrated_station.pop("mission_assignments", None)
    migrated_station.pop("receiver_defaults", None)

    migrated_registry = dict(registry)
    migrated_receivers = {}
    for canonical, raw in receivers.items():
        receiver = dict(raw)
        existing = receiver.get("capabilities") or []
        if isinstance(existing, str):
            existing = [existing]
        receiver["capabilities"] = [
            *[str(value) for value in existing if str(value) not in REQUIRED_CAPABILITIES],
            *REQUIRED_CAPABILITIES,
        ]
        migrated_receivers[canonical] = receiver
    migrated_registry["receivers"] = migrated_receivers

    report = {
        "ok": True,
        "version": "0.54.0a",
        "assignment_authority": "config/station.yaml:assignments",
        "assignments": {role: assignments[role] for role in ROLES},
        "sources": sources,
        "removed_sections": [
            key for key in ("mission_assignments", "receiver_defaults") if key in station
        ],
        "identity_changed": False,
        "capabilities_normalized": True,
    }
    return migrated_station, migrated_registry, report


def atomic_yaml(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".v0540a.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    station = load_mapping(STATION_FILE)
    registry = load_mapping(REGISTRY_FILE)
    migrated_station, migrated_registry, report = build_migration(station, registry)
    report["changed"] = migrated_station != station or migrated_registry != registry
    report["mode"] = "apply" if args.apply else "check"
    if args.apply and report["changed"]:
        atomic_yaml(STATION_FILE, migrated_station)
        atomic_yaml(REGISTRY_FILE, migrated_registry)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
