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
VERSION = "0.54.0d"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def get_policy() -> dict[str, Any]:
    """Return the per-satellite policy used by all planning providers."""
    settings = weather_planning.get_config()
    return {
        "version": settings["version"],
        "scope": "per_satellite",
        "profiles": settings["profiles"],
        "minimum_allowed": float(settings["minimum_allowed"]),
        "angle_minimum_allowed": float(settings["angle_minimum_allowed"]),
        "maximum_allowed": float(settings["maximum_allowed"]),
        "source": "config/satellites.yaml + config/iss_voice.yaml",
        # Compatibility field for older read-only consumers.
        "minimum_elevation": float(settings["minimum_elevation"]),
    }


def pass_key(item: dict[str, Any] | None) -> str | None:
    """Build the one stable key used by Planner, Queue and execution."""
    if not item:
        return None
    start = item.get("start")
    if hasattr(start, "timestamp"):
        epoch = int(start.timestamp())
    else:
        epoch = int(item.get("start_epoch") or 0)
    plugin_id = str(item.get("plugin_id") or item.get("mission_type") or "weather")
    return f"{plugin_id}:{item.get('name', '-')}:{epoch}"


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
    enabled = bool(config.get("enabled", False))
    planner_enabled = bool(config.get("planner_enabled", False))
    execution_enabled = bool(config.get("execution_enabled", False))
    backend_enabled = bool(config.get("execution_backend_enabled", False))
    receiver_claim_enabled = bool(config.get("receiver_claim_enabled", False))
    automation_eligible = all(
        (
            enabled,
            planner_enabled,
            execution_enabled,
            backend_enabled,
            receiver_claim_enabled,
        )
    )
    candidates = []
    for raw in iss_passes.get_passes(hours_ahead):
        item = deepcopy(raw)
        item.update(
            {
                "plugin_id": "iss_voice",
                "mission_type": str(config.get("mission_type", "iss_voice")),
                "receiver_role": "iss_voice",
                "planner_source": "iss_passes",
                "automation_eligible": automation_eligible,
                "execution_enabled": execution_enabled and backend_enabled,
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
    profiles = policy["profiles"]
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in candidates:
        item = deepcopy(raw)
        profile_id = str(item.get("planning_profile_id") or "")
        profile = profiles.get(profile_id)
        if not isinstance(profile, dict):
            item["planning_decision"] = "INVALID_PROFILE"
            item["planning_reason"] = f"No planning profile exists for {profile_id or 'this pass'}."
            rejected.append(item)
            continue
        minimum = float(profile["minimum_peak_elevation"])
        elevation = float(item.get("max_elevation") or 0.0)
        item["min_elevation"] = minimum
        item["minimum_peak_elevation"] = minimum
        item["begin_elevation"] = float(profile["begin_elevation"])
        item["close_elevation"] = float(profile["close_elevation"])
        item["planning_limit_elevation"] = minimum
        item["planning_policy_source"] = profile["source"]

        if elevation < minimum:
            item["planning_decision"] = "BELOW_LIMIT"
            item["planning_reason"] = (
                f"Maximum elevation {elevation:.1f}° is below the "
                f"{minimum:.1f}° {profile['label']} peak limit."
            )
            rejected.append(item)
            continue

        item["planning_decision"] = "ELIGIBLE"
        item["planning_reason"] = (
            f"Pass meets the {profile['label']} policy; window "
            f"{item['begin_elevation']:.1f}° rising to "
            f"{item['close_elevation']:.1f}° falling."
        )
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
    profiles = policy["profiles"]
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
            "planning_profiles": {
                key: profiles[key]
                for key in ("meteor_m2_3", "meteor_m2_4")
            },
            "candidate_count": built["approved_counts"]["weather"],
            "rejected_count": built["rejected_counts"]["weather"],
            "raw_candidate_count": len(weather_raw),
            "state": "active",
            "detail": "Weather provider using independent METEOR pass-window profiles.",
        },
        {
            "plugin_id": "iss_voice",
            "mission_type": str(iss_config.get("mission_type", "iss_voice")),
            "enabled": bool(iss_config.get("enabled", False)),
            "planner_enabled": bool(iss_config.get("planner_enabled", False)),
            "execution_enabled": bool(
                iss_config.get("enabled", False)
                and iss_config.get("planner_enabled", False)
                and iss_config.get("execution_enabled", False)
                and iss_config.get("execution_backend_enabled", False)
                and iss_config.get("receiver_claim_enabled", False)
            ),
            "receiver_role": "iss_voice",
            "receiver": get_assignment("iss_voice"),
            "satellite_name": iss_config.get("satellite_name", "ISS (ZARYA)"),
            "planning_profiles": {"iss_voice": profiles["iss_voice"]},
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
    """Return all candidates approved by the station planning policy.

    Planning approval does not imply runtime execution permission. Consumers that
    execute missions must use :func:`get_executable_candidates`.
    """
    return _build(hours_ahead)["approved"]


def get_executable_candidates(hours_ahead: int = 48) -> list[dict[str, Any]]:
    """Return the unified, chronological queue of executable missions.

    This is the only Mission Scheduler input. Providers remain responsible for
    publishing their execution contract; the scheduler does not special-case a
    plugin or mission type.
    """
    candidates = [
        item
        for item in get_candidates(hours_ahead)
        if item.get("automation_eligible", False)
        and item.get("execution_enabled", False)
    ]
    candidates.sort(key=lambda item: item["start"])
    return candidates


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
