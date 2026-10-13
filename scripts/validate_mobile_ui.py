#!/usr/bin/env python3
"""Static regression checks for the existing SDRCC Mobile web dashboard."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "dashboard/static/mobile/index.html"
VERSION_PATH = ROOT / "VERSION"
MANIFEST_PATH = ROOT / "scripts/install/update_manifest.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for path in (HTML_PATH, VERSION_PATH):
        relative = path.relative_to(ROOT).as_posix()
        digest = sha256(path.read_bytes()).hexdigest()
        require(digest in manifest.get(relative, []),
                f"Update manifest does not approve current {relative} hash")

    scripts = re.findall(r"<script(?:\s[^>]*)?>([\s\S]*?)</script>", html, re.I)
    require(len(scripts) == 1, "Expected one inline Mobile script")
    script = scripts[0]
    require("class=\"mobile-brand-banner\"" in html and
            'class="mobile-radar"' in html and
            'prefers-reduced-motion:reduce' in html,
            "Compact SDRCC radar banner or reduced-motion accessibility missing")
    require("renderPhotoCredit(target,d)" in script and
            'const isDeBinnenvaart=source==="De Binnenvaart"' in script,
            "Mobile photographer credit correction missing")
    require('if(!/^\\d{9}$/.test(id)||id===lastPhotoMmsi)return;' in script,
            "Vessel MMSI validation must remain a digit regex")
    for marker in (
        'id="aismap"', 'id="adsbmap"', 'id="liveaudio"', 'id="replay"',
        'id="mission-auto-on"', 'id="mission-auto-off"',
        'id="mission-stop-active"', 'id="mobile-ais-map"',
        'id="ais-highlight-status"', 'id="recordings"',
        'function setMap(id,key)', 'function currentMissionStopAllowed(data)',
        'function renderAudioState(data)',
    ):
        require(marker in html, f"Existing Mobile feature disappeared: {marker}")

    # SDRCC Mobile visual polish must not change any receiver operations.
    require('id="ais-highlight-status" class="muted" role="status" aria-live="polite" hidden' in html,
            "Keep AIS highlight plumbing but hide its technical status copy")
    for old_copy in (
        "Een gevalideerde ATIS/AIS-match krijgt 15 seconden",
        "Start of stop de bestaande readsb-ontvanger",
        "AUTO schakelt de bestaande missieplanning in",
    ):
        require(old_copy not in html, f"Verbose mobile help text still visible: {old_copy}")
    scenes = {
        "marine": "marine-panorama.webp",
        "adsb": "aviation-panorama.webp",
        "sat": "satellite-panorama.webp",
        "missions": "overview-panorama.webp",
        "system": "overview-panorama.webp",
    }
    for tab, banner in scenes.items():
        require(f'body[data-mobile-tab="{tab}"]' in html,
                f"Missing distinct mobile tab styling: {tab}")
        require((ROOT / "dashboard/static/assets/banners" / banner).is_file(),
                f"Missing existing desktop panorama: {banner}")
    require('document.body.dataset.mobileTab=tab;' in script and
            'id="mobile-scene-title"' in html,
            "Mobile banner must follow selected tab without switching the live map")
    require('#system #mobile-map-settings + #mobile-install-help' in html and
            '#system #mobile-install-help + a.action' in html,
            "Only adjacent bottom System controls should receive extra spacing")
    require('#adsb-service-state.off{display:none}' in html,
            "Redundant stopped badge above ADS-B controls must be hidden")

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "mobile-script.js"
        path.write_text(script, encoding="utf-8")
        subprocess.run(["node", "--check", str(path)], check=True)

    # Exercise the exact photographer-credit helper with minimal DOM stand-ins.
    node_test = r"""
const vm = require("node:vm");
const assert = require("node:assert/strict");
function el(tag) {
  return {
    tag, children: [], textContent: "",
    append(...nodes) { this.children.push(...nodes); },
  };
}
const source = process.argv[1];
const start = source.indexOf("function photoSourceUrl(value){");
const end = source.indexOf("async function showPhoto(m){", start);
assert.ok(start >= 0 && end > start);
const sandbox = {URL, document: {createElement: el}};
vm.runInNewContext(source.slice(start,end), sandbox);
let binnenvaart = el("div");
sandbox.renderPhotoCredit(binnenvaart, {
  source: "De Binnenvaart", artist: "© Anna Fotograaf",
  page_url: "https://www.debinnenvaart.nl/schepen_home/"
});
assert.equal(binnenvaart.children.length, 1);
assert.equal(binnenvaart.children[0].children[0].textContent, "© Anna Fotograaf");
assert.equal(binnenvaart.children[0].children[0].tag, "a");
assert.ok(binnenvaart.children[0].children[0].href.startsWith("https://www.debinnenvaart.nl/"));
assert.ok(!JSON.stringify(binnenvaart).includes('"De Binnenvaart"'));
let noArtist = el("div");
sandbox.renderPhotoCredit(noArtist, {
  source: "De Binnenvaart", artist: "",
  page_url: "https://www.debinnenvaart.nl/schepen_home/"
});
assert.equal(noArtist.children.length,0);
let other = el("div");
sandbox.renderPhotoCredit(other, {
  source: "Binnenvaartspotter.nl", artist: "© Peter de Vries",
  page_url: "https://www.binnenvaartspotter.nl/schepen/"
});
assert.equal(other.children[0].children[0].textContent, "© Peter de Vries");
assert.equal(other.children[0].children[1].textContent, " · Binnenvaartspotter.nl");
console.log("PASS: mobile photographer credits and links");
"""
    subprocess.run(["node", "-e", node_test, script], check=True)
    print("PASS: mobile HTML script, SDRCC radar banner, receiver controls and update hashes")


if __name__ == "__main__":
    try:
        validate()
    except (AssertionError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
