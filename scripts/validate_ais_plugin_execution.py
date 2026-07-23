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
ais = next(item for item in snapshot["plugins"] if item["plugin_id"] == "ais")
adsb = next(item for item in snapshot["plugins"] if item["plugin_id"] == "adsb")
check(snapshot["manager_version"] == "0.44.0b", "Plugin Manager-versie is v0.44.0b")
check(snapshot["execution_enablement"]["enabled_plugins"] == ["ais"], "alleen AIS is execution-enabled")
check(ais["control"]["enabled"] is True, "AIS-control is ingeschakeld")
check(ais["control"]["actions"] == ["start", "stop", "restart"], "AIS-acties zijn begrensd")
check(adsb["control"]["enabled"] is False, "ADS-B blijft uitgeschakeld in deze release")
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

    response = client.post('/api/plugin-manager/ais/action', json={'action': 'restart'})
    payload = response.get_json()
    check(response.status_code == 200 and payload["ok"] is True, "AIS Plugin Manager-route voert bestaande actie uit")
    check(calls == [("restart", "ais-catcher.service")], "AIS-plan delegeert exact naar ais-catcher.service")

    response = client.post('/api/plugin-manager/adsb/action', json={'action': 'restart'})
    check(response.status_code == 409, "ADS-B faalt gesloten")

    response = client.post('/api/plugin-manager/ais/action', json={'action': 'delete'})
    check(response.status_code == 400, "onbekende AIS-actie faalt gesloten")
finally:
    dashboard_app.run_systemctl = original_run
    dashboard_app.service_state = original_state

source = Path(dashboard_app.__file__).read_text()
route_block = source.split('def api_plugin_manager_action', 1)[1].split('@app.route("/api/plugin-capabilities"', 1)[0]
check('run_systemctl(' not in route_block, "Plugin Manager-route bevat geen eigen systemctl-call")
check('handle_service_action(' in route_block, "Plugin Manager-route hergebruikt bestaande service-authority")

print({
    "status": "ok",
    "version": "0.44.0b",
    "enabled_plugins": ["ais"],
    "authority": "existing_dashboard_systemctl_path",
    "delegated_service": "ais-catcher.service",
})
