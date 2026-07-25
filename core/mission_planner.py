#!/usr/bin/env python3
"""Generic multi-mission planning foundation for SDRCC.

This module owns candidate aggregation only. It does not execute missions,
claim receivers, control services, or mutate the Mission Queue.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
import yaml

from core import passes
from core.config import get_assignment, get_enabled_satellites

ROOT = Path(__file__).resolve().parent.parent
ISS_CONFIG_FILE = ROOT / "config" / "iss_voice.yaml"
Provider = Callable[[int], list[dict[str, Any]]]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _weather_candidates(hours_ahead: int) -> list[dict[str, Any]]:
    candidates = []
    satellites = get_enabled_satellites()
    for raw in passes.get_passes(hours_ahead):
        item = deepcopy(raw)
        sat_cfg = satellites.get(str(item.get("name")), {})
        item.update(
            {
                "plugin_id": "weather",
                "mission_type": "weather",
                "receiver_role": "weather",
                "planner_source": "weather_passes",
                "automation_eligible": True,
                "execution_enabled": True,
                "priority": int(sat_cfg.get("priority", 5)),
            }
        )
        candidates.append(item)
    return candidates


def _iss_voice_status() -> dict[str, Any]:
    root = _read_yaml(ISS_CONFIG_FILE)
    config = root.get("iss_voice", {}) if isinstance(root.get("iss_voice"), dict) else {}
    return {
        "plugin_id": "iss_voice",
        "mission_type": str(config.get("mission_type", "iss_voice")),
        "enabled": bool(config.get("enabled", False)),
        "planner_enabled": bool(config.get("planner_enabled", False)),
        "execution_enabled": bool(config.get("execution_enabled", False)),
        "receiver_role": "iss_voice",
        "receiver": get_assignment("iss_voice"),
        "satellite_name": config.get("satellite_name", "ISS (ZARYA)"),
        "minimum_elevation": float(config.get("minimum_elevation", 20.0)),
        "candidate_count": 0,
        "state": "foundation_only",
        "detail": "ISS Voice pass provider is not enabled in v0.46.0e.",
    }


def get_sources(hours_ahead: int = 48) -> list[dict[str, Any]]:
    weather = _weather_candidates(hours_ahead)
    iss_voice = _iss_voice_status()
    return [
        {
            "plugin_id": "weather",
            "mission_type": "weather",
            "enabled": True,
            "planner_enabled": True,
            "execution_enabled": True,
            "receiver_role": "weather",
            "receiver": get_assignment("weather"),
            "candidate_count": len(weather),
            "state": "active",
            "detail": "Existing Weather pass provider.",
        },
        iss_voice,
    ]


def get_candidates(hours_ahead: int = 48) -> list[dict[str, Any]]:
    """Return candidates from all enabled providers in chronological order."""
    candidates = _weather_candidates(hours_ahead)
    # v0.46.0e intentionally registers ISS Voice without producing passes.
    # The next release can add a provider without changing queue/scheduler contracts.
    candidates.sort(key=lambda item: item["start"])
    return candidates


def get_plan(hours_ahead: int = 48) -> dict[str, Any]:
    candidates = get_candidates(hours_ahead)
    return {
        "version": "0.46.0e",
        "authority": "planning_only",
        "hours_ahead": int(hours_ahead),
        "count": len(candidates),
        "sources": get_sources(hours_ahead),
        "candidates": candidates,
    }
