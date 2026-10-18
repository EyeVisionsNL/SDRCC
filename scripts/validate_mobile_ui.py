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
    require('if(!/^\\d{9}$/.test(id))return;' in script and
            'const key=[id,name.toUpperCase(),imo,eni].join("|")' in script and
            'lastPhotoRetryAfter=Date.now()+30*60*1000' in script,
            "Vessel MMSI must stay a nine-digit regex and photo retries must respect updated identity")
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
    require('#system #mobile-map-settings + a.action' in html and
            'id="mobile-install-help"' not in html and
            'mobileDeferredInstallPrompt' not in script and
            'beforeinstallprompt' not in script,
            "Obsolete PWA install card must be removed from System")
    require('#adsb-service-state.off{display:none}' in html,
            "Redundant stopped badge above ADS-B controls must be hidden")

    require('<html lang="en">' in html and
            "ATIS/AIS match confirmed. Map stays in place." in html and
            "ATIS/AIS-koppeling bevestigd" not in html,
            "Mobile visual text and ATIS card must be in English")
    require('let atisCardPulseTimer=null;' in script and
            "if(atisCardPulseTimer!==null)clearTimeout(atisCardPulseTimer);" in script and
            "String(data.atis?.latest?.received_at||\"\")" in script and
            "},30000);" in script,
            "Every new ATIS transmission must replace the previous 30s panel pulse")
    require('panel.classList.add(["on","off","bad"].includes(tone)' in script and
            "state-on" in html and "state-off" in html and "state-bad" in html,
            "SDRCC status must update card borders, not just labels")
    require('.control-buttons .start:not(:disabled)' in html and
            '.control-buttons .stop:not(:disabled)' in html and
            '--mobile-accent:#7dd3fc' in html,
            "Buttons must use state and Marine must be light blue")
    highlight_source = (ROOT / "dashboard/static/mobile/atis-highlight.pjs").read_text()
    require("expires: Date.now() + 30000" in highlight_source and
            "lastEvent = eventId;" in highlight_source and
            "endHighlight();" in highlight_source and
            "view.setCenter" not in highlight_source and
            "view.setZoom" not in highlight_source,
            "AIS-Catcher ATIS ring must last 30 seconds, replace older events, and not pan")
    mobile_manifest = json.loads(
        (ROOT / "dashboard/static/mobile/manifest.webmanifest").read_text())
    require(mobile_manifest.get("lang") == "en",
            "Installed Mobile PWA manifest must be English")

    # Sat shows the real planned missions in read-only mode. No new planner controls.
    require('id="sat-mission-queue-panel"' in html and
            'id="sat-mission-queue"' in html and
            'id="sat-mission-queue-summary"' in html and
            "Upcoming Missions" in html,
            "Missing Satellite Mission Queue panel")
    require('readMobileJson("/api/mission-queue?limit=50&hours=48",20000)' in script and
            'function renderUpcomingMissionQueue(payload)' in script and
            'if(!$("sat").hidden)void refreshMobileMissionQueue();' in script and
            "MOBILE_MISSION_QUEUE_REFRESH_MS=60000" in script and
            'postMobileJson("/api/mission-queue"' not in script,
            "Mobile must poll the real Mission Queue with GET and never mutate the plan")
    require('item.status||"").toUpperCase()!=="SKIPPED"' in script and
            'Number(item.end_epoch)>=now-30' in script and
            'stationMissionTime(item.start)' in script,
            "Skipped/completed passes and station times must be treated correctly")
    node_queue_test = r"""
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = process.argv[1];
const start = source.indexOf("function stationMissionTime(value){");
const end = source.indexOf("function renderMission(data){",start);
assert.ok(start > 0 && end > start);
function element(tag) {
  return {tag,children:[],className:"",dataset:{},textContent:"",
    append(...elements){this.children.push(...elements)}};
}
const root={children:[],replaceChildren(){this.children=[]},
  append(element){this.children.push(element)}};
const summary={textContent:""};
const nodes={"sat-mission-queue":root,"sat-mission-queue-summary":summary};
const sandbox={document:{createElement:element},$:id=>nodes[id],
  Date:{now:()=>1000000000000}};
vm.runInNewContext(source.slice(start,end),sandbox);
assert.equal(sandbox.stationMissionTime("2026-10-13 19:30:00"),"13 Oct · 19:30");
const queue=[
  {name:"ISS (ZARYA)",start:"2026-10-13 19:30:00",
    end:"2026-10-13 19:39:00",start_epoch:1000000150,end_epoch:1000001000,
    status:"NEXT",receiver:"SDR2",max_elevation:54.3,frequency_mhz:145.800},
  {name:"METEOR-M2 4",start:"2026-10-13 20:20:00",
    end:"2026-10-13 20:31:00",start_epoch:1000001500,end_epoch:1000002200,
    status:"BLOCKED",receiver:"SDR1",max_elevation:31.5},
  {name:"Skipped",start_epoch:1000002300,end_epoch:1000002600,
    status:"SKIPPED",skipped:true},
  {name:"Expired",start_epoch:999000000,end_epoch:999000600,status:"QUEUED"}
];
sandbox.renderUpcomingMissionQueue({queue,ok:true});
assert.equal(root.children.length,2);
assert.equal(root.children[0].children[0].children[0].textContent,"ISS (ZARYA)");
assert.equal(root.children[0].dataset.state,"NEXT");
assert.ok(root.children[0].children[2].textContent.includes("145.800 MHz"));
assert.equal(root.children[1].dataset.state,"BLOCKED");
assert.ok(summary.textContent.includes("2 planned passes"));
sandbox.renderUpcomingMissionQueue({queue:[],ok:true});
assert.equal(root.children.length,0);
assert.ok(summary.textContent.startsWith("No upcoming"));
console.log("PASS: Upcoming Missions read-only status and station times");
"""
    subprocess.run(["node", "-e", node_queue_test, script],check=True)

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
    # Simulate AIS-Catcher's plugin bridge without a browser or RF device.
    # A new event replaces the previous feature and 30s expiry. It cannot pan.
    bridge_test = r"""
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = process.argv[1];
let clock = 100000, timer, onMessage, managedSource, managedLayer, emergencySource, emergencyLayer, panned = 0, replies = [];
const parent = {postMessage: (msg) => replies.push(msg)};
const win = {
  parent, location: null,
  addEventListener: (event, fn) => {if(event==="message")onMessage=fn},
  setTimeout: (fn) => { fn(); return 1; },
  setInterval: (fn) => {timer=fn; return 7;},
  clearInterval: () => {timer=null},
};
const ol = {
  source: {Vector: class {
    constructor(){ this.items=[]; }
    addFeature(feature){ this.items.push(feature) }
    clear(){ this.items=[] }
    removeFeature(feature){ this.items=this.items.filter(item=>item!==feature) }
  }},
  layer: {Vector: class {
    constructor(options){this.visible=true;this.source=options.source}
    setVisible(v){this.visible=v}
    getVisible(){return this.visible}
    setOpacity(v){this.opacity=v}
  }},
  Feature: class {
    constructor(o){this.geometry=o.geometry}
    getGeometry(){return this.geometry}
    set() {}
    setStyle(styles){this.style=styles}
  },
  geom: {Point: class {
    constructor(coords){this.coords=coords}
    setCoordinates(coords){this.coords=coords}
  }},
  proj: {fromLonLat: x=>x},
  style: {Circle: class {}, Stroke: class {}, Fill: class {}, Style: class {}}
};
const context = {
  AISCatcher: {PLUGIN_API_VERSION: 5, addOverlayLayer(name, layer){
    if(name==="SDRCC ATIS Mobile"){managedLayer=layer;managedSource=layer.source}
    if(name==="SDRCC Emergency Vessels"){emergencyLayer=layer;emergencySource=layer.source}
  }, shipsDB: {}},
  ol, window: win,
  location: {protocol:"http:", hostname:"mini-pc"},
  Date: {now:()=>clock},
  console: {info(){}}
};
vm.runInNewContext(source, context);
assert.ok(onMessage);
assert.ok(managedSource && emergencySource,"Both isolated AIS map layers must be registered");
function send(event, id, mmsi){
  onMessage({source:parent,origin:"http://mini-pc:8080",
    data:{type:"sdrcc:atis-highlight:show",version:1,event_id:id,
      mmsi,latitude:51.91,longitude:4.35}});
}
send(null,"first","244700365");
assert.equal(managedSource.items.length,1);
assert.equal(managedLayer.visible,true);
clock+=29000;timer();
assert.equal(managedSource.items.length,1,"highlight should be alive at 29s");
send(null,"second","244700365");
assert.equal(managedSource.items.length,1,"new ATIS transmission must replace old ring");
clock+=29000;timer();
assert.equal(managedSource.items.length,1,"replacement should last its own 30s");
clock+=1000;timer();
assert.equal(managedSource.items.length,0,"replacement must expire at 30s");
assert.equal(managedLayer.visible,false);
assert.equal(panned,0);
assert.equal(replies.filter(x=>x.type==="sdrcc:atis-highlight:shown").length,2);
onMessage({source:parent,origin:"http://mini-pc:8080",data:{
  type:"sdrcc:emergency-highlight:sync",version:1,vessels:[
    {mmsi:"246333000",category:"knrm",latitude:51.91,longitude:4.35,remaining_seconds:300},
    {mmsi:"notmmsi",category:"knrm",latitude:51.91,longitude:4.35,remaining_seconds:300}
  ]
}});
assert.equal(emergencySource.items.length,1,"Only nine-digit AIS emergency MMSIs may be highlighted");
assert.equal(managedSource.items.length,0,"Emergency must not overwrite the ATIS overlay");
assert.equal(emergencyLayer.visible,true);
onMessage({source:parent,origin:"http://mini-pc:8080",data:{
  type:"sdrcc:emergency-highlight:sync",version:1,vessels:[]
}});
assert.equal(emergencySource.items.length,0,"Empty emergency sync must clear old vessel rings");
assert.equal(emergencyLayer.visible,false);
console.log("PASS: AIS-Catcher ATIS ring (30s) and independent emergency vessel overlay");
"""
    subprocess.run(
        ["node", "-e", bridge_test,
         (ROOT / "dashboard/static/mobile/atis-highlight.pjs").read_text()],
        check=True)
    print("PASS: mobile HTML script, SDRCC radar banner, receiver controls and update hashes")


if __name__ == "__main__":
    try:
        validate()
    except (AssertionError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
