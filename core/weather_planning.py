#!/usr/bin/env python3
"""Central Weather Planning configuration for SDRCC."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any
import yaml

ROOT = Path(__file__).resolve().parent.parent
STATION_FILE = ROOT / "config" / "station.yaml"
SATELLITES_FILE = ROOT / "config" / "satellites.yaml"
_LOCK = RLock()
DEFAULT_MINIMUM_ELEVATION = 40.0
MIN_ALLOWED_ELEVATION = 5.0
MAX_ALLOWED_ELEVATION = 90.0


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} bevat geen geldige YAML-structuur")
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    yaml.safe_load(temp.read_text(encoding="utf-8"))
    temp.replace(path)


def _normalize(value: Any) -> float:
    try:
        elevation = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Minimale elevatie moet een getal zijn.") from exc
    if not MIN_ALLOWED_ELEVATION <= elevation <= MAX_ALLOWED_ELEVATION:
        raise ValueError(
            f"Minimale elevatie moet tussen {MIN_ALLOWED_ELEVATION:.0f}° en "
            f"{MAX_ALLOWED_ELEVATION:.0f}° liggen."
        )
    return round(elevation, 1)


def _sync_satellites(minimum_elevation: float) -> int:
    data = _read_yaml(SATELLITES_FILE)
    satellites = data.get("satellites") if isinstance(data.get("satellites"), dict) else data
    changed = 0
    if isinstance(satellites, dict):
        for config in satellites.values():
            if not isinstance(config, dict) or "min_elevation" not in config:
                continue
            if float(config.get("min_elevation", -1)) != minimum_elevation:
                config["min_elevation"] = minimum_elevation
                changed += 1
    if changed:
        _write_yaml(SATELLITES_FILE, data)
    return changed


def get_config(*, synchronize: bool = True) -> dict[str, Any]:
    with _LOCK:
        station = _read_yaml(STATION_FILE)
        planning = station.get("weather_planning", {})
        value = _normalize(planning.get("minimum_elevation", DEFAULT_MINIMUM_ELEVATION))
        synced = _sync_satellites(value) if synchronize else 0
        return {
            "minimum_elevation": value,
            "minimum_allowed": MIN_ALLOWED_ELEVATION,
            "maximum_allowed": MAX_ALLOWED_ELEVATION,
            "satellites_updated": synced,
        }


def set_config(payload: dict[str, Any]) -> dict[str, Any]:
    value = _normalize(payload.get("minimum_elevation"))
    with _LOCK:
        station = _read_yaml(STATION_FILE)
        planning = station.setdefault("weather_planning", {})
        if not isinstance(planning, dict):
            planning = {}
            station["weather_planning"] = planning
        planning["minimum_elevation"] = value
        _write_yaml(STATION_FILE, station)
        synced = _sync_satellites(value)
        return {
            "minimum_elevation": value,
            "minimum_allowed": MIN_ALLOWED_ELEVATION,
            "maximum_allowed": MAX_ALLOWED_ELEVATION,
            "satellites_updated": synced,
        }
