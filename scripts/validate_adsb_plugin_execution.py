#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import plugin_manager
from dashboard import app as dashboard_app


def check(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print(f"PASS: {message}")


snapshot = plugin_manager.get_snapshot(include_planned=True)
plugins = {item["plugin_id"]: item for item in snapshot["plugins"]}
ais = plugins["ais"]
adsb = plugins["adsb"]
weather = plugins["weather"]

check(snapshot["manager_version"] == "0.44.1", "Plugin Manager-versie is v0.44.1")
check(snapshot["execution_enablement"]["enabled_plugins"] == ["ais", "adsb"], "AIS en ADS-B zijn execution-enabled")
check(ais["control"]["enabled"] is True, "AIS blijft ingeschakeld")
check(adsb["control"]["enabled"] is True, "ADS-B-control is ingeschakeld")
check(adsb["control"]["actions"] == ["start", "stop", "restart"], "ADS-B-acties zijn begrensd")
check(adsb["control"]["endpoint"] == "/api/plugin-manager/adsb/action", "ADS-B endpoint is correct")
check(adsb["execution"]["executable"] is True, "ADS-B execution is uitvoerbaar")
check(adsb["execution"]["execution_mode"] == "delegated_service_control", "ADS-B gebruikt delegated service control")
check(weather["control"]["enabled"] is False, "Weather blijft uitgeschakeld")
check(snapshot["execution_enablement"]["new_service_controller"] is False, "geen nieuwe servicecontroller toegevoegd")

calls: list[tuple[str, str]] = []
original_run = dashboard_app.run_systemctl
original_state = dashboard_app.service_state
try:
    dashboard_app.run_systemctl = lambda action, service: (
        calls.append((action, service)) or SimpleNamespace(returncode=0, stdout="", stderr="")
    )
    dashboard_app.service_state = lambda service: {
        "service": service,
        "state": "active",
        "active": True,
        "enabled": True,
    }
    client = dashboard_app.app.test_client()

    response = client.post('/api/plugin-manager/adsb/action', json={'action': 'restart'})
    payload = response.get_json()
    check(response.status_code == 200 and payload["ok"] is True, "ADS-B Plugin Manager-route voert bestaande actie uit")
    check(calls == [("restart", "readsb.service")], "ADS-B delegeert exact naar readsb.service")

    response = client.post('/api/plugin-manager/weather/action', json={'action': 'restart'})
    check(response.status_code == 409, "Weather faalt gesloten")

    response = client.post('/api/plugin-manager/adsb/action', json={'action': 'delete'})
    check(response.status_code == 400, "onbekende ADS-B-actie faalt gesloten")
finally:
    dashboard_app.run_systemctl = original_run
    dashboard_app.service_state = original_state

source = Path(dashboard_app.__file__).read_text()
route_block = source.split('def api_plugin_manager_action', 1)[1].split('@app.route("/api/plugin-capabilities"', 1)[0]
check('run_systemctl(' not in route_block, "Plugin Manager-route bevat geen eigen systemctl-call")
check('handle_service_action(' in route_block, "Plugin Manager-route hergebruikt bestaande service-authority")

print({
    "status": "ok",
    "version": "0.44.1",
    "enabled_plugins": ["ais", "adsb"],
    "authority": "existing_dashboard_systemctl_path",
    "delegated_service": "readsb.service",
})
