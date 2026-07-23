#!/usr/bin/env python3
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import plugin_manager


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


snapshot = plugin_manager.get_snapshot(include_planned=True)
plugins = {item["plugin_id"]: item for item in snapshot["plugins"]}
ais = plugins["ais"]
adsb = plugins["adsb"]
weather = plugins["weather"]

require(snapshot["manager_version"] == "0.44.0b", "Plugin Manager-versie is v0.44.0b")
require(snapshot["execution_enablement"]["model_aligned"] is True, "effective execution-model is aligned")
require(snapshot["summary"]["execution_enabled_plugins"] == ["ais"], "alleen AIS is effectief execution-enabled")
require(snapshot["summary"]["execution_foundation_only"] is False, "manager rapporteert niet langer foundation-only")
require(snapshot["summary"]["execution_planning_only"] is False, "manager rapporteert niet langer planning-only")
require(ais["execution"]["executable"] is True, "AIS execution is executable")
require(ais["execution"]["foundation_only"] is False, "AIS execution is niet foundation-only")
require(ais["execution"]["execution_mode"] == "delegated_service_control", "AIS gebruikt delegated service control")
require(ais["execution_plan"]["executable"] is True, "AIS-plan is uitvoerbaar")
require(ais["execution_plan"]["planning_only"] is False, "AIS-plan is niet planning-only")
require(ais["control"]["authority"] == "existing_dashboard_systemctl_path", "AIS behoudt bestaande service-authority")
require(adsb["control"]["enabled"] is False, "ADS-B blijft uitgeschakeld")
require(adsb["execution"]["executable"] is False, "ADS-B blijft fail-closed")
require(weather["execution"]["executable"] is False, "Weather-uitvoering blijft ongewijzigd")

source = inspect.getsource(plugin_manager)
require("run_systemctl(" not in source, "Plugin Manager bevat geen run_systemctl-call")
require("subprocess." not in source and "import subprocess" not in source and "from subprocess" not in source, "Plugin Manager bevat geen subprocess-authority")

print(json.dumps({
    "status": "ok",
    "version": snapshot["manager_version"],
    "enabled_plugins": snapshot["summary"]["execution_enabled_plugins"],
    "ais_execution_mode": ais["execution"]["execution_mode"],
    "authority": ais["control"]["authority"],
}, indent=2))
