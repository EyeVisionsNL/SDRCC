#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import iss_voice, plugin_registry  # noqa: E402


def check(condition: bool, label: str, errors: list[str]) -> None:
    print(("PASS" if condition else "FAIL") + ": " + label)
    if not condition:
        errors.append(label)


def main() -> int:
    errors: list[str] = []
    plugin = plugin_registry.get_plugin("iss_voice") or {}
    station = yaml.safe_load((ROOT / "config/station.yaml").read_text()) or {}
    profiles = yaml.safe_load((ROOT / "config/profiles.yaml").read_text()) or {}
    satellites = yaml.safe_load((ROOT / "config/satellites.yaml").read_text()) or {}
    validation = iss_voice.validate_config()

    check(plugin.get("status") == "active", "ISS Voice plugin is active", errors)
    check(plugin.get("assignment_role") == "iss_voice", "assignment role is iss_voice", errors)
    check(plugin.get("executor") is None, "executor remains fail-closed", errors)
    check(plugin.get("dashboard", {}).get("assignment") is True, "dashboard assignment metadata enabled", errors)
    check(station.get("assignments", {}).get("iss_voice") in {"sdr1", "sdr2"}, "ISS Voice assigned to SDR1 or SDR2", errors)
    check("iss_voice" in profiles.get("profiles", {}), "ISS Voice profile exists", errors)
    check(validation.get("ok") is True, "ISS Voice config validates", errors)
    check("ISS (ZARYA)" not in satellites.get("satellites", {}), "ISS not injected into Weather/SatDump satellite list", errors)
    check(iss_voice.get_status().get("receiver_claim_enabled") is False, "no receiver claim in foundation", errors)
    check(iss_voice.get_status().get("planner_enabled") is False, "no Mission Queue mutation in foundation", errors)

    print()
    if errors:
        print(f"ISS Voice foundation validation FAILED ({len(errors)} errors)")
        return 1
    print("ISS Voice foundation validation PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
