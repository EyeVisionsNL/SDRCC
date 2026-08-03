#!/usr/bin/env python3
"""Persistent per-satellite Mission Planner pass-window configuration.

The historic module name is retained as a compatibility layer. Planning values
are owned by the existing satellite/profile configuration files; this module
only validates and updates those values atomically.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import RLock
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATION_FILE = ROOT / "config" / "station.yaml"
SATELLITES_FILE = ROOT / "config" / "satellites.yaml"
ISS_CONFIG_FILE = ROOT / "config" / "iss_voice.yaml"
_LOCK = RLock()

DEFAULT_MINIMUM_PEAK_ELEVATION = 40.0
DEFAULT_BEGIN_ELEVATION = 10.0
DEFAULT_CLOSE_ELEVATION = 10.0
MIN_ALLOWED_ELEVATION = 0.0
MIN_ALLOWED_PEAK_ELEVATION = 5.0
MAX_ALLOWED_ELEVATION = 90.0

PROFILE_DEFINITIONS = {
    "meteor_m2_3": {
        "label": "METEOR-M2 3",
        "satellite_name": "METEOR-M2 3",
        "mission_type": "weather",
        "config_file": "config/satellites.yaml",
    },
    "meteor_m2_4": {
        "label": "METEOR-M2 4",
        "satellite_name": "METEOR-M2 4",
        "mission_type": "weather",
        "config_file": "config/satellites.yaml",
    },
    "iss_voice": {
        "label": "ISS Voice",
        "satellite_name": "ISS (ZARYA)",
        "mission_type": "iss_voice",
        "config_file": "config/iss_voice.yaml",
    },
}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} does not contain a YAML mapping")
    return data


def _dump_yaml(data: dict[str, Any]) -> str:
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    checked = yaml.safe_load(text)
    if not isinstance(checked, dict):
        raise ValueError("Generated planning configuration is invalid")
    return text


def _write_pair_atomically(
    satellites_data: dict[str, Any],
    iss_data: dict[str, Any],
) -> None:
    payloads = {
        SATELLITES_FILE: _dump_yaml(satellites_data),
        ISS_CONFIG_FILE: _dump_yaml(iss_data),
    }
    previous = {
        path: path.read_bytes() if path.exists() else None
        for path in payloads
    }
    temps: dict[Path, Path] = {}
    try:
        for path, text in payloads.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".v0540d.tmp")
            with temp.open("w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists():
                os.chmod(temp, path.stat().st_mode & 0o777)
            temps[path] = temp
        for path in payloads:
            temps[path].replace(path)
    except Exception:
        for path, content in previous.items():
            if content is None:
                path.unlink(missing_ok=True)
                continue
            restore = path.with_suffix(path.suffix + ".restore.tmp")
            restore.write_bytes(content)
            restore.replace(path)
        raise
    finally:
        for temp in temps.values():
            temp.unlink(missing_ok=True)


def _number(value: Any, *, label: str, minimum: float) -> float:
    try:
        elevation = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not minimum <= elevation <= MAX_ALLOWED_ELEVATION:
        raise ValueError(
            f"{label} must be between {minimum:.0f}° and "
            f"{MAX_ALLOWED_ELEVATION:.0f}°"
        )
    return round(elevation, 1)


def _normalize_profile(raw: dict[str, Any], *, profile_id: str) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError(f"Planning profile {profile_id} must be a mapping")
    minimum_peak = _number(
        raw.get("minimum_peak_elevation"),
        label="Minimum peak elevation",
        minimum=MIN_ALLOWED_PEAK_ELEVATION,
    )
    begin = _number(
        raw.get("begin_elevation"),
        label="Begin elevation",
        minimum=MIN_ALLOWED_ELEVATION,
    )
    close = _number(
        raw.get("close_elevation"),
        label="Close elevation",
        minimum=MIN_ALLOWED_ELEVATION,
    )
    if begin > minimum_peak:
        raise ValueError(
            f"{PROFILE_DEFINITIONS[profile_id]['label']}: begin elevation "
            "cannot exceed minimum peak elevation"
        )
    if close > minimum_peak:
        raise ValueError(
            f"{PROFILE_DEFINITIONS[profile_id]['label']}: close elevation "
            "cannot exceed minimum peak elevation"
        )
    return {
        "minimum_peak_elevation": minimum_peak,
        "begin_elevation": begin,
        "close_elevation": close,
    }


def _station_default() -> float:
    station = _read_yaml(STATION_FILE)
    planning = station.get("weather_planning") or {}
    value = planning.get("minimum_elevation", DEFAULT_MINIMUM_PEAK_ELEVATION)
    try:
        return _number(
            value,
            label="Legacy minimum elevation",
            minimum=MIN_ALLOWED_PEAK_ELEVATION,
        )
    except ValueError:
        return DEFAULT_MINIMUM_PEAK_ELEVATION


def _default_window(minimum_peak: float) -> dict[str, float]:
    return {
        "minimum_peak_elevation": minimum_peak,
        "begin_elevation": min(DEFAULT_BEGIN_ELEVATION, minimum_peak),
        "close_elevation": min(DEFAULT_CLOSE_ELEVATION, minimum_peak),
    }


def _with_defaults(raw: Any, minimum_peak: float) -> dict[str, Any]:
    values = _default_window(float(minimum_peak))
    if isinstance(raw, dict):
        for key in values:
            if raw.get(key) is not None:
                values[key] = raw[key]
    return values


def _profile_from_data(
    profile_id: str,
    satellites_data: dict[str, Any],
    iss_data: dict[str, Any],
    *,
    legacy_default: float,
) -> dict[str, Any]:
    definition = PROFILE_DEFINITIONS[profile_id]
    if profile_id == "iss_voice":
        root = iss_data.get("iss_voice") or {}
        stored = root.get("planning") if isinstance(root, dict) else None
        fallback_peak = legacy_default
    else:
        satellites = satellites_data.get("satellites") or {}
        root = satellites.get(definition["satellite_name"]) or {}
        stored = root.get("planning") if isinstance(root, dict) else None
        fallback_peak = root.get("min_elevation", legacy_default) if isinstance(root, dict) else legacy_default
    values = _normalize_profile(
        _with_defaults(stored, float(fallback_peak)),
        profile_id=profile_id,
    )
    return {
        "profile_id": profile_id,
        **definition,
        **values,
        "source": f"{definition['config_file']}:planning",
    }


def get_config(*, synchronize: bool = False) -> dict[str, Any]:
    """Return all independent planning profiles in stable UI order."""
    with _LOCK:
        satellites_data = _read_yaml(SATELLITES_FILE)
        iss_data = _read_yaml(ISS_CONFIG_FILE)
        legacy_default = _station_default()
        profiles = {
            profile_id: _profile_from_data(
                profile_id,
                satellites_data,
                iss_data,
                legacy_default=legacy_default,
            )
            for profile_id in PROFILE_DEFINITIONS
        }
        if synchronize:
            ensure_defaults()
        compatibility_values = {
            profile["minimum_peak_elevation"] for profile in profiles.values()
        }
        compatibility_minimum = (
            compatibility_values.pop()
            if len(compatibility_values) == 1
            else profiles["meteor_m2_3"]["minimum_peak_elevation"]
        )
        return {
            "version": "0.54.0d",
            "scope": "per_satellite",
            "profiles": profiles,
            # Compatibility field for older read-only clients.
            "minimum_elevation": compatibility_minimum,
            "minimum_allowed": MIN_ALLOWED_PEAK_ELEVATION,
            "maximum_allowed": MAX_ALLOWED_ELEVATION,
            "angle_minimum_allowed": MIN_ALLOWED_ELEVATION,
            "satellites_updated": 0,
        }


def get_profile(reference: str) -> dict[str, Any]:
    normalized = str(reference or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "meteor_m2_3": "meteor_m2_3",
        "meteor_m2_4": "meteor_m2_4",
        "iss": "iss_voice",
        "iss_(zarya)": "iss_voice",
        "iss_voice": "iss_voice",
    }
    profile_id = aliases.get(normalized)
    if profile_id is None:
        for candidate, definition in PROFILE_DEFINITIONS.items():
            if str(reference) == definition["satellite_name"]:
                profile_id = candidate
                break
    if profile_id is None:
        raise ValueError(f"Unknown planning profile: {reference}")
    return get_config()["profiles"][profile_id]


def _apply_profile(
    profile_id: str,
    values: dict[str, float],
    satellites_data: dict[str, Any],
    iss_data: dict[str, Any],
) -> None:
    definition = PROFILE_DEFINITIONS[profile_id]
    stored = {
        "minimum_peak_elevation": values["minimum_peak_elevation"],
        "begin_elevation": values["begin_elevation"],
        "close_elevation": values["close_elevation"],
    }
    if profile_id == "iss_voice":
        root = iss_data.setdefault("iss_voice", {})
        if not isinstance(root, dict):
            raise ValueError("iss_voice.yaml does not contain an iss_voice mapping")
        root["planning"] = stored
        root["minimum_elevation"] = values["minimum_peak_elevation"]
        return
    satellites = satellites_data.setdefault("satellites", {})
    if not isinstance(satellites, dict):
        raise ValueError("satellites.yaml does not contain a satellites mapping")
    root = satellites.setdefault(definition["satellite_name"], {})
    if not isinstance(root, dict):
        raise ValueError(f"Satellite {definition['satellite_name']} has invalid configuration")
    root["planning"] = stored
    root["min_elevation"] = values["minimum_peak_elevation"]


def set_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist either all profiles or the legacy global value."""
    if not isinstance(payload, dict):
        raise ValueError("Planning payload must be a mapping")
    with _LOCK:
        current = get_config()["profiles"]
        requested = payload.get("profiles")
        updates: dict[str, dict[str, float]] = {}
        if isinstance(requested, dict):
            unknown = sorted(set(requested) - set(PROFILE_DEFINITIONS))
            if unknown:
                raise ValueError("Unknown planning profiles: " + ", ".join(unknown))
            for profile_id in PROFILE_DEFINITIONS:
                raw = requested.get(profile_id, current[profile_id])
                updates[profile_id] = _normalize_profile(raw, profile_id=profile_id)
        elif "minimum_elevation" in payload:
            # Compatibility for an older cached dashboard: apply its formerly
            # global value to every profile without changing begin/close angles.
            minimum = _number(
                payload.get("minimum_elevation"),
                label="Minimum peak elevation",
                minimum=MIN_ALLOWED_PEAK_ELEVATION,
            )
            for profile_id, profile in current.items():
                updates[profile_id] = _normalize_profile(
                    {
                        **profile,
                        "minimum_peak_elevation": minimum,
                        "begin_elevation": min(profile["begin_elevation"], minimum),
                        "close_elevation": min(profile["close_elevation"], minimum),
                    },
                    profile_id=profile_id,
                )
        else:
            raise ValueError("No planning profiles were supplied")

        satellites_data = _read_yaml(SATELLITES_FILE)
        iss_data = _read_yaml(ISS_CONFIG_FILE)
        for profile_id, values in updates.items():
            _apply_profile(profile_id, values, satellites_data, iss_data)
        _write_pair_atomically(satellites_data, iss_data)
        return get_config()


def ensure_defaults() -> dict[str, Any]:
    """Add only missing v0.54.0d fields; preserve all existing new values."""
    with _LOCK:
        satellites_data = _read_yaml(SATELLITES_FILE)
        iss_data = _read_yaml(ISS_CONFIG_FILE)
        legacy_default = _station_default()
        changed = False
        for profile_id in PROFILE_DEFINITIONS:
            definition = PROFILE_DEFINITIONS[profile_id]
            if profile_id == "iss_voice":
                root = iss_data.setdefault("iss_voice", {})
                if not isinstance(root, dict):
                    raise ValueError("iss_voice.yaml does not contain an iss_voice mapping")
                stored = root.get("planning")
                fallback_peak = legacy_default
            else:
                satellites = satellites_data.setdefault("satellites", {})
                root = satellites.setdefault(definition["satellite_name"], {})
                if not isinstance(root, dict):
                    raise ValueError(f"Satellite {definition['satellite_name']} has invalid configuration")
                stored = root.get("planning")
                fallback_peak = float(root.get("min_elevation", legacy_default))
            values = _normalize_profile(
                _with_defaults(stored, fallback_peak),
                profile_id=profile_id,
            )
            if not isinstance(stored, dict) or any(key not in stored for key in values):
                changed = True
            before = dict(root)
            root["planning"] = {
                "minimum_peak_elevation": values["minimum_peak_elevation"],
                "begin_elevation": values["begin_elevation"],
                "close_elevation": values["close_elevation"],
            }
            root["minimum_elevation" if profile_id == "iss_voice" else "min_elevation"] = values["minimum_peak_elevation"]
            changed = changed or before != root
        if changed:
            _write_pair_atomically(satellites_data, iss_data)
        result = get_config()
        result["changed"] = changed
        return result
