#!/usr/bin/env python3
"""Generic multi-mission planning for SDRCC.

This module owns candidate aggregation and planning-policy decisions only.
It does not execute missions, claim receivers, or control services.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import yaml

from core import iss_passes, passes, weather_planning
from core.config import get_assignment, get_enabled_satellites

ROOT = Path(__file__).resolve().parent.parent
ISS_CONFIG_FILE = ROOT / "config" / "iss_voice.yaml"
VERSION = "0.47.0a"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def get_policy() -> dict[str, Any]:
    """Return the single planning policy used by every mission provider."""
    settings = weather_planning.get_config()
    return {
        "minimum_elevation": float(settings["minimum_elevation"]),
        "minimum_allowed": float(settings["minimum_allowed"]),
        "maximum_allowed": float(settings["maximum_allowed"]),
        "source": "config/station.yaml:weather_planning.minimum_elevation",
        "scope": "all_mission_types",
    }


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


def _iss_config() -> dict[str, Any]:
    root = _read_yaml(ISS_CONFIG_FILE)
    config = root.get("iss_voice", {}) if isinstance(root.get("iss_voice"), dict) else {}
    return config


def _iss_voice_candidates(hours_ahead: int) -> list[dict[str, Any]]:
    config = _iss_config()
    priority = int(config.get("planning_priority", 3))
    candidates = []
    for raw in iss_passes.get_passes(hours_ahead):
        item = deepcopy(raw)
        item.update(
            {
                "plugin_id": "iss_voice",
                "mission_type": str(config.get("mission_type", "iss_voice")),
                "receiver_role": "iss_voice",
                "planner_source": "iss_passes",
                "automation_eligible": False,
                "execution_enabled": False,
                "priority": priority,
            }
        )
        candidates.append(item)
    return candidates


def _provider_candidates(hours_ahead: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "weather": _weather_candidates(hours_ahead),
        "iss_voice": _iss_voice_candidates(hours_ahead),
    }


def _apply_policy(
    candidates: list[dict[str, Any]],
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    minimum = float(policy["minimum_elevation"])
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in candidates:
        item = deepcopy(raw)
        elevation = float(item.get("max_elevation") or 0.0)
        item["min_elevation"] = minimum
        item["planning_limit_elevation"] = minimum
        item["planning_policy_source"] = policy["source"]

        if elevation < minimum:
            item["planning_decision"] = "BELOW_LIMIT"
            item["planning_reason"] = (
                f"Maximum elevation {elevation:.1f}° is below the "
                f"{minimum:.1f}° station planning limit."
            )
            rejected.append(item)
            continue

        item["planning_decision"] = "ELIGIBLE"
        item["planning_reason"] = "Pass meets the current station planning policy."
        approved.append(item)

    approved.sort(key=lambda item: item["start"])
    rejected.sort(key=lambda item: item["start"])
    return approved, rejected


def _build(hours_ahead: int) -> dict[str, Any]:
    policy = get_policy()
    providers = _provider_candidates(hours_ahead)
    all_candidates = [item for values in providers.values() for item in values]
    approved, rejected = _apply_policy(all_candidates, policy)

    approved_counts = {
        plugin_id: sum(1 for item in approved if item.get("plugin_id") == plugin_id)
        for plugin_id in providers
    }
    rejected_counts = {
        plugin_id: sum(1 for item in rejected if item.get("plugin_id") == plugin_id)
        for plugin_id in providers
    }
    return {
        "policy": policy,
        "providers": providers,
        "approved": approved,
        "rejected": rejected,
        "approved_counts": approved_counts,
        "rejected_counts": rejected_counts,
    }


def get_sources(hours_ahead: int = 48) -> list[dict[str, Any]]:
    built = _build(hours_ahead)
    policy = built["policy"]
    iss_config = _iss_config()
    iss_status = iss_passes.get_status()
    weather_raw = built["providers"]["weather"]
    iss_raw = built["providers"]["iss_voice"]
    return [
        {
            "plugin_id": "weather",
            "mission_type": "weather",
            "enabled": True,
            "planner_enabled": True,
            "execution_enabled": True,
            "receiver_role": "weather",
            "receiver": get_assignment("weather"),
            "minimum_elevation": policy["minimum_elevation"],
            "candidate_count": built["approved_counts"]["weather"],
            "rejected_count": built["rejected_counts"]["weather"],
            "raw_candidate_count": len(weather_raw),
            "state": "active",
            "detail": "Existing Weather pass provider using the station planning policy.",
        },
        {
            "plugin_id": "iss_voice",
            "mission_type": str(iss_config.get("mission_type", "iss_voice")),
            "enabled": bool(iss_config.get("enabled", False)),
            "planner_enabled": bool(iss_config.get("planner_enabled", False)),
            "execution_enabled": False,
            "receiver_role": "iss_voice",
            "receiver": get_assignment("iss_voice"),
            "satellite_name": iss_config.get("satellite_name", "ISS (ZARYA)"),
            "minimum_elevation": policy["minimum_elevation"],
            "candidate_count": built["approved_counts"]["iss_voice"],
            "rejected_count": built["rejected_counts"]["iss_voice"],
            "raw_candidate_count": len(iss_raw),
            "state": iss_status["state"],
            "detail": iss_status["detail"],
            "tle_present": iss_status["tle_present"],
            "tle_age_hours": iss_status["tle_age_hours"],
            "norad_id": iss_status["norad_id"],
        },
    ]


def get_candidates(hours_ahead: int = 48) -> list[dict[str, Any]]:
    """Return only candidates approved by the single station planning policy."""
    return _build(hours_ahead)["approved"]


def get_rejected_candidates(hours_ahead: int = 48) -> list[dict[str, Any]]:
    """Return rejected candidates for diagnostics; never used as Mission Queue input."""
    return _build(hours_ahead)["rejected"]


def get_plan(hours_ahead: int = 48) -> dict[str, Any]:
    built = _build(hours_ahead)
    return {
        "version": VERSION,
        "authority": "planning_only",
        "hours_ahead": int(hours_ahead),
        "policy": built["policy"],
        "count": len(built["approved"]),
        "rejected_count": len(built["rejected"]),
        "sources": get_sources(hours_ahead),
        "candidates": built["approved"],
    }
