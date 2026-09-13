#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(ok, label):
    if not ok:
        raise AssertionError(label)
    print(f"PASS: {label}")


def main():
    from core import config, traffic_voice

    version = (ROOT / "VERSION").read_text().strip()
    check(version == "0.56.0w", "candidate version is 0.56.0w")
    raw = config.load_traffic_voice()
    check(traffic_voice.validate_configuration(raw)["ok"], "Traffic Voice configuration validates")
    settings = traffic_voice.get_receiver_settings(raw)
    check(settings["scan_interval_ms"] == int(raw["traffic_voice"]["backend"].get("scan_interval_ms", 200)), "scan interval is exposed by settings API")

    for bad in (50, 125, 550):
        try:
            traffic_voice.normalize_receiver_settings({"scan_interval_ms": bad}, payload=raw)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid scan interval {bad} was accepted")
    print("PASS: invalid scan intervals fail closed")

    candidate = deepcopy(raw)
    candidate["traffic_voice"]["backend"]["scan_interval_ms"] = 100
    with patch.object(config, "load_traffic_voice", return_value=candidate):
        rendered = traffic_voice.render_rtlsdr_airband_config()
    check("scan_interval_ms = 100;" in rendered, "runtime config receives selected 100 ms scan interval")

    html = (ROOT / "dashboard/templates/index.html").read_text()
    js = (ROOT / "dashboard/static/js/traffic_voice.js").read_text()
    provision = (ROOT / "scripts/install/provision_external.sh").read_text()
    check('id="traffic-voice-scan-interval"' in html, "scan speed slider is directly available in Traffic Voice controls")
    check('scan_interval_ms: Number(byId("traffic-voice-scan-interval")' in js, "browser sends scan interval through existing settings action")
    check('patch_rtlsdr_airband_scan_interval.py' in provision, "clean installer applies scan interval patch")
    check('SDRCC v0.56.0w scan-interval patch' in provision, "clean installer provenance requires scan interval patch")

    patcher = ROOT / "scripts/install/patch_rtlsdr_airband_scan_interval.py"
    fixture = """bool multiple_output_threads = false;\nbool log_scan_activity = false;\nchar* stats_filepath = NULL;\n\nvoid f(){\n    while (!do_exit) {\n        SLEEP(200);\n        if (dev->channels[0].axcindicate == NO_SIGNAL) {\n        }\n    }\n}\n\nvoid p(){\n        if (root.exists("log_scan_activity") && (bool)root["log_scan_activity"] == true)\n            log_scan_activity = true;\n        if (root.exists("stats_filepath"))\n            stats_filepath = strdup(root["stats_filepath"]);\n}\n"""
    with TemporaryDirectory(prefix="sdrcc-scan-patch-") as tmp:
        source = Path(tmp) / "rtl_airband.cpp"
        source.write_text(fixture)
        subprocess.run([sys.executable, str(patcher), str(source)], check=True)
        patched = source.read_text()
        check("int scan_interval_ms = 200;" in patched, "upstream patch adds safe 200 ms default")
        check("SLEEP(scan_interval_ms);" in patched, "upstream controller uses configurable interval")
        check('root.exists("scan_interval_ms")' in patched, "upstream config parser accepts generated setting")

    subprocess.run([sys.executable, "-m", "compileall", "-q", str(ROOT / "core"), str(ROOT / "dashboard")], check=True)
    print("PASS: Python compileall")
    print("VALIDATION PASS: v0.56.0w Traffic Voice configurable scan speed candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
