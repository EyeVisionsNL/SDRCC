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

    # Intelligence uses the existing server-rendered AI page, not a second AI engine.
    require('data-tab="intelligence"' in html and 'id="mobile-intelligence-frame"' in html
            and 'intelligenceFrame.src="/?mobile_intelligence=1"' in script
            and 'syncMobileIntelligence();' in script
            and 'body[data-mobile-tab="intelligence"]' in html,
            "Mobile Intelligence navigation missing")
    template = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    require("request.args.get('mobile_intelligence') == '1'" in template
            and 'class="mobile-intelligence-embed"' in template,
            "Mobile Intelligence must reuse desktop template")
    # Mobile and desktop must use exactly the same current Intelligence panorama.
    banner_css = (ROOT / "dashboard/static/css/banner_scenes.css").read_text(encoding="utf-8")
    desktop_scene = re.search(r'\.topbar\[data-banner-scene="intelligence"\]\s*\{\s*--banner-image:url\([\x27"]([^\x27"]+)[\x27"]\)', banner_css)
    mobile_scene = re.search(r'body\[data-mobile-tab="intelligence"\]\{[^}]*--mobile-scene:url\("([^"]+)"\)', html)
    require(desktop_scene is not None and mobile_scene is not None
            and desktop_scene.group(1) == mobile_scene.group(1),
            "Mobile Intelligence panorama must match desktop")
    banner = ROOT / ("dashboard" + desktop_scene.group(1))
    require(banner.is_file() and sha256(banner.read_bytes()).hexdigest()
            in manifest.get(banner.relative_to(ROOT).as_posix(), []),
            "Intelligence panorama missing or not approved in update manifest")
    # The same original artwork is composited on both surfaces; keep the dish
    # stationary and relocate only the UFO. Verify the embedded source hash.
    import base64
    import xml.etree.ElementTree as ET
    root = ET.fromstring(banner.read_text(encoding="utf-8"))
    ns = {"svg": "http://www.w3.org/2000/svg"}
    require(root.attrib.get("viewBox") == "0 0 1280 208", "Intelligence panorama geometry changed")
    image = root.find(".//svg:image", ns)
    embedded = image.attrib["{http://www.w3.org/1999/xlink}href"].split(",", 1)[1]
    source = ROOT / "dashboard/static/assets/banners/intelligence-night-panorama.webp"
    require(base64.b64decode(embedded, validate=True) == source.read_bytes(), "Original artwork changed")
    require(any(g.attrib.get("transform") == "translate(-120 20)" for g in root.findall("svg:g", ns)),
            "UFO should move left and down independently of the dish")
    polish = (ROOT / "dashboard/static/css/dashboard_polish.css").read_text(encoding="utf-8")
    require("background-image: var(--banner-image)" in polish and
            '.topbar[data-banner-scene="intelligence"] .topbar-visuals::before' in polish,
            "Desktop must render the actual panorama layer")
    require(re.search(r'\.topbar\[data-banner-scene="intelligence"\] \.topbar-visuals::before\s*\{\s*background-size: auto 100%;\s*background-position: right center;', polish),
            "Desktop Intelligence panorama must meet the right edge without SVG letterboxing")
    require(".mobile-brand-banner .mobile-radar{grid-column:1;grid-row:1;" in html and
            "#connection{grid-column:1;grid-row:2;" in html and
            ".mobile-brand-banner .mobile-brand-copy{grid-column:2;grid-row:1 / 3;" in html,
            "Connection indicator must sit below the radar, not over the artwork")
    # Real browser check: render the composed SVG into a canvas and verify
    # that both UFO regions change while the dish and shoreline remain intact.
    # Also check actual header geometry on phone-width viewports.
    import shutil
    chrome = next((p for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser") if (p := shutil.which(n))), None)
    if chrome:
        mobile_css = re.search(r"<style>([\s\S]*?)</style>", html).group(1)
        header = re.search(r'<header class="mobile-brand-banner"[\s\S]*?</header>', html).group(0)
        def data_url(file, mime):
            return "data:" + mime + ";base64," + base64.b64encode(file.read_bytes()).decode("ascii")
        artwork = [data_url(source, "image/webp"), data_url(banner, "image/svg+xml")]
        fixture_js = r"""
(async () => {
  const assert=(v,m)=>{if(!v)throw Error(m)};
  const load=src=>new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(Error("Banner image failed to load"));im.src=src});
  try {
    const images=await Promise.all(ART.map(load));
    const canvas=document.createElement("canvas");canvas.width=1280;canvas.height=208;
    const ctx=canvas.getContext("2d",{willReadFrequently:true});
    const pixels=images.map(im=>{ctx.clearRect(0,0,1280,208);ctx.drawImage(im,0,0);return ctx.getImageData(0,0,1280,208).data});
    function changed(x0,y0,x1,y1){
      let count=0;
      for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
        const i=(y*1280+x)*4;
        if(Math.max(...[0,1,2,3].map(k=>Math.abs(pixels[0][i+k]-pixels[1][i+k])))>18)count++;
      }
      return count;
    }
    assert(changed(1000,8,1110,65)>200,"Original UFO position not changed");
    assert(changed(820,25,920,80)>200,"New UFO position not visible");
    assert(changed(1135,70,1250,208)===0,"Dish/shoreline pixels changed");
    for(const width of [320,360,390,600]){
      const frame=document.createElement("iframe");frame.width=width;frame.height=140;
      const ready=new Promise(resolve=>frame.onload=resolve);
      frame.srcdoc=HEADER;document.body.append(frame);await ready;
      const d=frame.contentDocument;
      d.body.dataset.mobileTab="marine";
      const radar=d.querySelector(".mobile-radar"),badge=d.getElementById("connection"),copy=d.querySelector(".mobile-brand-copy");
      for(const state of ["● ONLINE","○ OFFLINE","◌ CONNECTING…"]){
        badge.textContent=state;
        const r=radar.getBoundingClientRect(),b=badge.getBoundingClientRect(),c=copy.getBoundingClientRect();
        assert(b.top>=r.bottom-1,"Badge overlaps radar at "+width);
        assert(Math.abs((b.left+b.right-r.left-r.right)/2)<2,"Badge not centered under radar at "+width);
        assert(b.right<c.left,"Badge overlaps brand text at "+width);
        assert(d.documentElement.scrollWidth<=width,"Horizontal overflow at "+width);
      }
      frame.remove();
    }
    // Check the actual CSS artwork geometry, not just the declared tab name.
    for(const width of [320,360,390,480,600]){
      const frame=document.createElement("iframe");frame.width=width;frame.height=140;
      const ready=new Promise(resolve=>frame.onload=resolve);
      frame.srcdoc=HEADER;document.body.append(frame);await ready;
      const d=frame.contentDocument,w=frame.contentWindow;
      const header=d.querySelector(".mobile-brand-banner");
      for(const [tab,asset,center,left,right] of [
        ["marine","marine-panorama.webp",.66,.56,.76],
        ["adsb","aviation-panorama.webp",.70,.57,.82],
        ["sat","satellite-panorama.webp",.72,.55,.89]
      ]){
        d.body.dataset.mobileTab=tab;
        const style=w.getComputedStyle(header);
        assert(style.backgroundImage.includes(asset),"Wrong image for "+tab);
        const scale=parseFloat(style.getPropertyValue("--mobile-art-width"))/100;
        const pos=parseFloat(style.getPropertyValue("--mobile-art-position"))/100;
        assert(style.backgroundSize.includes((scale*100)+"% auto"),"Wrong sizing for "+tab);
        const box=header.getBoundingClientRect();
        const iw=box.width*scale,offset=(box.width-iw)*pos;
        assert((offset+center*iw)/box.width>.68,"Subject not on right: "+tab);
        assert(offset+right*iw<box.width,"Subject clipped on right: "+tab);
        assert(offset+left*iw>box.width*.46,"Subject extends into radar/brand: "+tab);
      }
      d.body.dataset.mobileTab="intelligence";
      assert(w.getComputedStyle(header).backgroundSize==="cover, auto 100%","Mobile UFO changed");
      frame.remove();
    }
    document.body.dataset.bannerResult="PASS";
  }catch(e){document.body.dataset.bannerResult="FAIL";document.body.dataset.bannerError=e.message}
})();
"""
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / "banner.html"
            header_doc = '<!doctype html><html><head><meta charset="utf-8"><style>' + mobile_css + '</style></head><body>' + header + '</body></html>'
            fixture.write_text('<!doctype html><html><head><meta charset="utf-8"></head><body><script>const ART=' + json.dumps(artwork) + ';const HEADER=' + json.dumps(header_doc) + ';' + fixture_js + '</script></body></html>', encoding="utf-8")
            run = subprocess.run([chrome,"--headless","--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--no-first-run","--virtual-time-budget=8000","--dump-dom",fixture.as_uri()], capture_output=True, text=True, timeout=30)
            result = re.search(r"<body[^>]*>",run.stdout)
            require(run.returncode == 0 and result is not None and 'data-banner-result="PASS"' in result.group(0),
                    "Banner browser check: " + (result.group(0) if result else run.stderr[-1000:]))
    # Flask is available in the Local AI CI job. Validate both rendered variants
    # there without starting SDRCC or requiring receivers. The standalone Mobile
    # UI workflow also runs the static checks without a Flask dependency.
    try:
        from flask import Flask, render_template_string
    except ImportError:
        pass
    else:
        app = Flask(__name__)
        for path, embedded in (("/", False), ("/?mobile_intelligence=1", True)):
            with app.test_request_context(path):
                rendered = render_template_string(template, features={}, asset_version="test")
            require(rendered.count('id="tab-intelligence"') == 1 and
                    rendered.count('data-ai-view=') == 11,
                    "Both layouts must expose every Intelligence view exactly once")
            require(('class="mobile-intelligence-embed"' in rendered) == embedded,
                    "Mobile layout flag not respected")
            require(('/static/dashboard.js' in rendered) != embedded,
                    "Mobile layout must not initialize desktop receiver controls")
            require(("classList.add(\"active\")" in rendered) == embedded,
                    "Embedded page must initialize active")
    # 3D opens from Mobile without replacing the 2D AIS iframe or live audio.
    require('id="mobile-map-2d"' in html and
            'id="mobile-map-3d"' in html and
            'id="mobile-map-3d-frame"' in html and
            'const MOBILE_3D_MAP_URL="/map-lab?mode=3d&mobile=1";' in script and
            'history.pushState({sdrccMobileMap3d:true}' in script and
            'window.addEventListener("popstate"' in script and
            '$("mobile-map-3d-frame").src="about:blank";' in script,
            "Mobile 3D map navigation or native back support is missing")
    map_lab_script = (ROOT / "dashboard/static/js/traffic_map_lab.js").read_text(encoding="utf-8")
    map_lab_template = (ROOT / "dashboard/templates/traffic_map_lab.html").read_text(encoding="utf-8")
    require('let mode3d = mobileEmbedded3d;' in map_lab_script and
            'zoom: mobileEmbedded3d ? 15 : 11' in map_lab_script and
            'setMode(mode3d)' in map_lab_script and
            "mobile-map-embed" in map_lab_template,
            "Mobile map should start tilted while desktop Map Lab remains 2D")

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
