#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "dashboard/templates/index.html").read_text()
css = (ROOT / "dashboard/static/css/home_position.css").read_text()

def check(ok, message):
    if not ok:
        print(f"FAIL: {message}")
        raise SystemExit(1)
    print(f"PASS: {message}")

check((ROOT / "VERSION").read_text().strip() == "0.56.0m",
      "release remains 0.56.0m")
check('class="card home-position-card compact-card"' not in html,
      "standalone Home Position card is removed")
check('<details class="card system-maintenance-card-v0540f"' in html,
      "existing Advanced Maintenance themed disclosure remains")
maintenance = html.split('<div class="system-maintenance-body-v0540f">', 1)[1]
check('id="home-position-form"' in maintenance,
      "Home Position form is inside Advanced Maintenance")
check('home-position-maintenance' in maintenance,
      "Home Position uses bounded maintenance layout")
check('STATION SETUP' in maintenance,
      "Home Position has maintenance-context badge")
check('home-position-maintenance-copy' in html,
      "title and description use compact inline heading")
check('grid-template-columns:' in css and 'minmax(300px, 1.55fr)' in css,
      "desktop Home Position controls use one compact row")
check('system-maintenance-card-v0540f' in css,
      "CSS documents inherited existing maintenance theme")
check('--panel-accent' not in css and '--panel-corner-accent' not in css,
      "hotfix does not invent a second System theme")
check('id="home-position-location"' in html and
      'id="home-position-latitude"' in html and
      'id="home-position-longitude"' in html and
      'id="home-position-altitude"' in html,
      "all Home Position controls are retained")
check('id="home-position-browser"' in html and 'id="home-position-save"' in html,
      "browser and save actions are retained")
check((ROOT / "docs/home-position-maintenance-polish-v0560m-r3.md").exists(),
      "r3 documentation is present")

print("VALIDATION PASS: SDRCC v0.56.0m-r3 Home Position Maintenance Polish")
