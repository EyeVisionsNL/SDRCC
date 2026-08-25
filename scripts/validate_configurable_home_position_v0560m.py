#!/usr/bin/env python3
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

def check(ok, message):
    if not ok:
        print(f"FAIL: {message}")
        raise SystemExit(1)
    print(f"PASS: {message}")

check((ROOT / "VERSION").read_text().strip() == "0.56.0m", "release version is 0.56.0m")

for rel in ("core/config.py", "core/satellite_view.py", "dashboard/app.py"):
    ast.parse((ROOT / rel).read_text())
    check(True, f"parseable {rel}")

config_text = (ROOT / "core/config.py").read_text()
app_text = (ROOT / "dashboard/app.py").read_text()
html = (ROOT / "dashboard/templates/index.html").read_text()
home_js = (ROOT / "dashboard/static/js/home_position.js").read_text()
radio_js = (ROOT / "dashboard/static/js/radio_view.js").read_text()
satellite_text = (ROOT / "core/satellite_view.py").read_text()

check("def normalize_home_position" in config_text, "bounded home-position validator exists")
check("def get_home_position" in config_text, "central home-position reader exists")
check("def set_home_position" in config_text, "central home-position writer exists")
check("save_station(data)" in config_text, "existing atomic station writer remains write boundary")
check('@app.route("/api/home-position", methods=["GET", "POST"])' in app_text,
      "bounded Home Position API is present")
check("Home Position is locked while a mission is active or preparing." in app_text,
      "Home Position writes are blocked during mission execution")
check("satellite_view_core.invalidate_cache()" in app_text,
      "Radio View observer cache is invalidated after save")
check("def invalidate_cache()" in satellite_text,
      "satellite observer exposes bounded cache invalidation")
check('id="home-position-form"' in html, "System Home Position form is present")
check('id="home-position-browser"' in html, "browser location control is present")
check('id="home-position-save"' in html, "explicit Save Home Position control is present")
check("navigator.geolocation.getCurrentPosition" in home_js,
      "browser location uses browser geolocation")
check("Press Save Home Position to apply it." in home_js,
      "browser location does not auto-save")
check('fetch("/api/home-position"' in home_js,
      "Home Position UI uses bounded API")
check("sdrcc:home-position-changed" in home_js and "sdrcc:home-position-changed" in radio_js,
      "Radio View gets immediate presentation refresh after save")
check('HOME · Vlaardingen' not in html,
      "Radio View no longer contains hardcoded Vlaardingen placeholder")
check("config/station.yaml:station" in app_text,
      "API declares existing station.yaml authority")
check('fetch("/api/home-position"' in home_js and "save_station(" not in home_js,
      "browser code uses API only and has no direct configuration writer")
check((ROOT / "docs/configurable-home-position-v0560m.md").exists(),
      "v0.56.0m documentation is present")

print("VALIDATION PASS: SDRCC v0.56.0m Configurable Home Position")
