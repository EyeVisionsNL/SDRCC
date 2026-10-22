#!/usr/bin/env python3
"""Offline regression checks for SDRCC's initial setup, no services changed."""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]


def require(ok, text):
    if not ok:
        raise AssertionError(text)
    print("PASS:", text)


def load_script(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def main():
    require(subprocess.run(["bash", "-n", str(ROOT / "install.sh")], check=False).returncode == 0,
            "installer bash syntax")
    for path in (
        "scripts/install/configure_station.py",
        "scripts/install/setup_ais.py",
        "core/config.py",
        "core/passes.py",
        "core/iss_passes.py",
        "core/mission_planner.py",
        "core/mission_scheduler.py",
        "core/satellite_view.py",
    ):
        ast.parse((ROOT / path).read_text(encoding="utf-8"))
    require(True, "all changed Python files parse")

    install = (ROOT / "install.sh").read_text()
    require("1/5 Station name" not in install and "--defer --apply" in install,
            "fresh installation no longer asks five position questions")
    require('if [[ -x "$PYTHON" && -f "$PROJECT_ROOT/VERSION"' in install,
            "existing installation still uses the managed update path")
    require("AIS_SETUP_ONLY" in install and 'setup_ais.py' in install,
            "existing AIS resume option preserved")

    setup = load_script("scripts/install/configure_station.py", "_sdrcc_installer_station_test")
    from core import config as config_core

    with tempfile.TemporaryDirectory() as tmp:
        station = Path(tmp) / "station.yaml"
        receivers = Path(tmp) / "receivers.yaml"
        station.write_text(yaml.safe_dump({
            "station": {"name": "SDRCC", "location": "Vlaardingen",
                        "latitude": 51.9, "longitude": 4.35, "altitude_m": 6}
        }))
        receivers.write_text(yaml.safe_dump({"receivers": {}}))
        original_station = config_core.STATION_CONFIG
        try:
            setup.STATION, setup.RECEIVERS = station, receivers
            config_core.STATION_CONFIG = station
            with mock.patch.object(sys, "argv", ["configure_station.py", "--defer", "--apply"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    require(setup.main() == 0, "deferred station setup succeeds without sudo")
            deferred = yaml.safe_load(station.read_text())["station"]
            require(deferred["position_configured"] is False and deferred["latitude"] == 0.0,
                    "demo coordinates marked explicitly unusable")
            require(config_core.home_position_configured() is False and
                    config_core.get_home_position()["configured"] is False,
                    "dashboard exposes pending Home Position status")

            with mock.patch.object(config_core, "_sync_readsb_home_position", return_value=None):
                position = config_core.set_home_position({
                    "name": "Test Station", "location": "Rotterdam",
                    "latitude": 51.9, "longitude": 4.3, "altitude_m": 7,
                })
            require(position["configured"] is True and position["name"] == "Test Station" and
                    config_core.home_position_configured() is True,
                    "saving Home Position activates real coordinates")
            persisted = yaml.safe_load(station.read_text())["station"]
            require(persisted["position_configured"] is True and persisted["latitude"] == 51.9,
                    "station setup persists correct position")

            persisted.pop("position_configured")
            station.write_text(yaml.safe_dump({"station": persisted}))
            require(config_core.home_position_configured() is True,
                    "legacy stations without marker remain configured")
        finally:
            config_core.STATION_CONFIG = original_station

    ais = load_script("scripts/install/setup_ais.py", "_sdrcc_installer_ais_test")
    with mock.patch.dict("os.environ", {"SUDO_USER": "root"}, clear=True):
        require(ais.open_local_wizard("http://127.0.0.1:8118/") is False,
                "no browser opened as root or without desktop")
    require("open_local_wizard(url)" in (ROOT / "scripts/install/setup_ais.py").read_text(),
            "upstream AIS-catcher wizard auto-open path present")
    with mock.patch.dict("os.environ", {
        "SUDO_USER": "tester", "SDRCC_SETUP_DISPLAY": ":0",
        "SDRCC_SETUP_XAUTHORITY": "/home/tester/.Xauthority",
    }, clear=True):
        with mock.patch.object(ais.shutil, "which", return_value="/usr/bin/xdg-open"), \
             mock.patch.object(ais.pwd, "getpwnam", return_value=SimpleNamespace(
                 pw_dir="/home/tester", pw_uid=1000)), \
             mock.patch.object(ais.subprocess, "Popen") as opened:
            require(ais.open_local_wizard("http://127.0.0.1:8118/") is True,
                    "desktop wizard attempts to open as the normal user")
            command = opened.call_args.args[0]
            environment = opened.call_args.kwargs["env"]
            require(command[:4] == ["runuser", "-u", "tester", "--"] and
                    environment["DISPLAY"] == ":0" and
                    environment["XAUTHORITY"] == "/home/tester/.Xauthority",
                    "display and Xauthority survive sudo without opening as root")

    manifest = json.loads((ROOT / "scripts/install/update_manifest.json").read_text())
    require("install.sh" in manifest and "core/config.py" in manifest,
            "managed update manifest includes changed installer and location logic")
    print("VALIDATION PASS: SDRCC first-install step 1 (offline checks)")


if __name__ == "__main__":
    main()
