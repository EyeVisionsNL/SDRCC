#!/usr/bin/env node
"use strict";
/*
 * Offline MapLibre 6 regression for course-aligned traffic sprites.
 * The simulated map does not contact network, receivers, or an SDRCC server.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const source = fs.readFileSync(
    path.join(__dirname, "../dashboard/static/js/traffic_map_lab.js"), "utf8");
const markup = fs.readFileSync(
    path.join(__dirname, "../dashboard/templates/traffic_map_lab.html"), "utf8");
// The expanded map must not compete with a permanent 280px right sidebar.
assert(markup.includes('<details id="map-lab-legend" class="map-legend"'),
    "layer controls must live in a floating native details legend");
assert(markup.includes('<div class="map-stage">'));
assert(!markup.includes('<aside class="side">'), "legacy sidebar still steals map space");
// The map must start at the top, with 2D/3D, Reset and Refresh floating over it.
assert(!markup.includes('<header>'), "oversized page header still steals map height");
assert(!markup.includes('SDRCC Radio View'), "redundant dashboard link must be removed");
assert(!markup.includes('class="toolbar"'), "old toolbar must not reserve vertical space");
assert(markup.includes('#map{height:calc(100dvh - 58px)'), "map must fill available viewport height");
assert(markup.includes('.map-tools{position:absolute'), "floating controls must be on the map");
const mapIndex = markup.indexOf('<div id="map"');
const controlIndex = markup.indexOf('<div class="map-tools"');
const legendIndex = markup.indexOf('<details id="map-lab-legend"');
assert(mapIndex >= 0 && controlIndex > mapIndex && legendIndex > controlIndex,
    "map mode controls and legend must overlay the map in the same stage");
for (const id of ["mode-2d","mode-3d","reset-view","refresh-now"]) {
    assert.equal(markup.split('id="' + id + '"').length, 2, "missing/duplicate control " + id);
}
assert(!markup.includes('grid-template-columns:minmax(0,1fr) 280px'));
assert(markup.includes('.map-legend:not([open])'), "legend must be compact when closed");
assert(markup.includes('.legend-content{max-height:') === false ||
       markup.includes('.legend-content{padding:'), "expanded legend must scroll");
for (const id of ["layer-ais","layer-adsb","layer-station","layer-vts",
                  "layer-emergency","layer-atis","layer-tracks","track-status","track-duration","track-duration-value","show-names","feed-status"]) {
    assert(markup.includes('id="' + id + '"'), "missing existing control " + id);
}
const esm = 'await import("https://unpkg.com/maplibre-gl@6.14.0/dist/maplibre-gl.mjs")';
assert(source.includes(esm), "MapLibre 6 import unexpectedly changed");
assert(markup.includes('id="track-duration" type="range" min="1" max="60" step="1" value="15"'),
    "AIS track duration must be adjustable from 1 to 60 minutes");

const nodes = {};
const node = id => nodes[id] ||= {
    textContent: "", checked: true, listeners: {},
    addEventListener(event, cb) {this.listeners[event] = cb;},
    setAttribute() {},
    classList: {add() {}, remove() {}},
};
const canvas = () => {
    const rects = [];
    return {
        width: 0, height: 0,
        getContext: () => ({
            scale() {}, beginPath() {}, moveTo() {}, bezierCurveTo() {},
            lineTo() {}, quadraticCurveTo() {}, closePath() {},
            fill() {}, stroke() {}, fillRect(...values) {rects.push(values);},
            arc() {}, fillText() {},
            getImageData(x, y, width, height) {
                return {width, height, data: new Uint8ClampedArray(width * height * 4),
                    rects: rects.slice()};
            },
        }),
    };
};
const document = {
    hidden: false, getElementById: node,
    createElement(tag) {
        if (tag === "canvas") return canvas();
        return {
            tag, children: [], textContent:"", className:"",
            appendChild(child) {this.children.push(child); return child;},
            remove() {},
        };
    },
};
let instance;
let lastPopup;
class FakePopup {
    setLngLat(value) {this.position = value; return this;}
    setDOMContent(element) {this.element = element; return this;}
    addTo() {lastPopup = this; return this;}
}
class FakeMap {
    constructor() {
        instance = this;
        this.callbacks = {};
        this.layers = {};
        this.sources = {};
        this.images = {};
        this.layoutChanges = [];
        this.paintChanges = [];
        this.camera = {};
    }
    addControl() {}
    on(type, layer, handler) {
        const key = type + (typeof layer === "string" ? ":" + layer : "");
        this.callbacks[key] = typeof layer === "function" ? layer : handler;
    }
    addSource(id, options) {
        this.sources[id] = {options, data: options.data, setData(value) {this.data = value;}};
    }
    getSource(id) {return this.sources[id];}
    addImage(id, image, options) {
        assert.equal(options.pixelRatio, 2);
        assert.equal(image.width, 96);
        assert.equal(image.height, id.startsWith("sdrcc-name-") ? 48 : 96);
        if (id.startsWith("sdrcc-name-")) {
            assert(options.stretchX && options.stretchY, "label plates must support text fitting");
            assert.deepEqual(image.rects, [[0, 0, 48, 24]],
                "label must be a single uninterrupted class colour, without black frame");
        }
        this.images[id] = image;
    }
    getStyle() {return {layers: []};}
    addLayer(layer) {
        if (layer.id.endsWith("-icons")) {
            assert(Object.keys(this.images).length === 76,
                "14 nameplates, 56 ship, 4 offshore and 2 aircraft sprites");
        }
        this.layers[layer.id] = layer;
    }
    getLayer(id) {return this.layers[id];}
    setLayoutProperty(id, key, value) {
        this.layoutChanges.push({id, key, value});
    }
    setPaintProperty(id, key, value) {
        this.paintChanges.push({id, key, value});
    }
    easeTo(camera) {this.camera = camera;}
    jumpTo(camera) {this.camera = camera;}
    getCanvas() {return {style: {}};}
}

(async () => {
    const data = {
        ok: true, center: [4.28, 51.93],
        station: {name:"EyeVisions Home", lon:4.28, lat:51.93, altitude_m:12},
        ais: {available: true, source_count: 14, count: 14, unverified_count: 1,
            targets: [
                {type:"ais", id:"123456789", name:"Known ship",
                    lon:4.3, lat:51.9, course:132, hull_heading:134, speed_knots:6,
                    length_m:140, to_bow:110, to_stern:30,
                    to_port:9, to_starboard:10, hull_available:true, shipclass:6,
                    render_profile:"tanker",validation_state:"verified"},
                {type:"ais", id:"987654321", name:"Unverified ship",
                    lon:4.4, lat:51.91, course:90, speed_knots:7, shipclass:2,
                    validation_state:"unverified"},
                {type:"ais", id:"111222333", name:"No heading",
                    lon:4.31, lat:51.9, course:null, validation_state:"unknown"},
                {type:"ais",id:"992440001",name:"WTG 19",lon:4.33,lat:51.94,
                    render_profile:"offshore_wtg",is_offshore_structure:true,shipclass:12},
                {type:"ais",id:"992440002",name:"P15",lon:4.34,lat:51.94,
                    render_profile:"offshore_platform",is_offshore_structure:true,shipclass:11},
                {type:"ais",id:"244123999",name:"Cargo ship",lon:4.35,lat:51.93,
                    render_profile:"cargo",shipclass:2,shiptype:70,course:90,hull_heading:90,
                    to_bow:90,to_stern:20,to_port:7,to_starboard:8,hull_available:true},
                {type:"ais",id:"244555000",name:"MULTRATUG",lon:4.42,lat:51.94,
                    render_profile:"tug",shipclass:5,shiptype:52,course:160,hull_heading:160,
                    to_bow:14,to_stern:8,to_port:3,to_starboard:3,hull_available:true},
                {type:"ais",id:"244600015",name:"P15",lon:4.46,lat:51.96,
                    render_profile:"police",shipclass:5,shiptype:55,course:165,hull_heading:165,
                    to_bow:12,to_stern:8,to_port:2.5,to_starboard:2.5,hull_available:true},
                {type:"ais",id:"244020742",name:"MSTX 12",lon:4.48,lat:51.96,
                    render_profile:"watertaxi",shipclass:7,shiptype:1900,
                    course:86.3,hull_heading:86.3,speed_knots:19.7,
                    length_m:11,beam_m:3,to_bow:8,to_stern:3,
                    to_port:1.5,to_starboard:1.5,hull_available:true},
                {type:"ais",id:"244456065",name:"KRVE 65",lon:4.49,lat:51.96,
                    render_profile:"krve",shipclass:7,shiptype:1900,
                    course:75,hull_heading:75,speed_knots:13.4,
                    length_m:10,beam_m:3.6,to_bow:7,to_stern:3,
                    to_port:1.8,to_starboard:1.8,hull_available:true},
                {type:"ais",id:"992456974",name:"Q13A-A PLATFORM",
                    lon:4.13618,lat:52.19112,render_profile:"offshore_platform",
                    is_offshore_structure:true,shipclass:12,shiptype:0},
                {type:"ais",id:"244050469",name:"RPA12",
                    lon:4.34,lat:51.93,render_profile:"port_authority",
                    shipclass:5,shiptype:99,course:186.3,hull_heading:186.3,
                    speed_knots:4.5,length_m:28.8,beam_m:8.2,
                    to_bow:14.39,to_stern:14.39,to_port:4.1,to_starboard:4.1,
                    hull_available:true,hull_bearing_approximate:true,
                    hull_geometry_source:"Published dimensions; approximate AIS position offset"},
                {type:"ais",id:"244901101",name:"CLASS B PLEASURE",
                    lon:4.39,lat:51.94,shipclass:3,shiptype:37,
                    render_profile:"pleasure",course:76,hull_heading:76,
                    speed_knots:3.1,length_m:11,beam_m:3.2,
                    to_bow:5.5,to_stern:5.5,to_port:1.6,to_starboard:1.6,
                    hull_available:true,hull_geometry_source:
                        "Illustrative Class B pleasure hull; antenna offsets unavailable",
                    hull_bearing_approximate:true},
                {type:"ais",id:"244901102",name:"CLASS B REAL DIMENSIONS",
                    lon:4.40,lat:51.94,shipclass:3,shiptype:36,
                    render_profile:"pleasure",course:160,hull_heading:160,
                    length_m:9,beam_m:3,to_bow:6,to_stern:3,
                    to_port:1.4,to_starboard:1.6,hull_available:true,
                    hull_geometry_source:"AIS dimensions"},
            ]},
        adsb: {available: true, source_count: 1, count: 1, targets:[
            {type:"adsb", id:"4ca123", name:"TEST123",
                registration:"PH-BGX", aircraft_type:"B738", operator:"KLM",
                squawk:"4720", lon:4.5, lat:51.92, course:212, altitude_ft:24000},
        ]},
    };
    const highlights = {
        ok: true, read_only: true, emergency_vessels: [
            {mmsi:"123456789",category:"knrm",latitude:51.9,longitude:4.3,remaining_seconds:300},
            {mmsi:"987654321",category:"waterpolitie",latitude:51.91,longitude:4.4,remaining_seconds:90},
        ],
        atis_match: {mmsi:"123456789",atis_code:"9244050123",
            event_id:"9244050123|2026-10-23T11:34:56+02:00",
            latitude:51.9,longitude:4.3,remaining_seconds:25},
    };
    const vts = {
        ok: true, available: true, count: 1,
        geojson: {type:"FeatureCollection",features:[{
            type:"Feature", properties:{
                name:"Sector Botlek", vhfchannel:"61", color:"#e5007e",
            }, geometry:{type:"Polygon",coordinates:[[[
                4.25,51.88],[4.30,51.88],[4.30,51.90],[4.25,51.88]]]},
        }]},
    };
    const stored = new Map([["sdrcc.mapLab.legendOpen", "1"],
        ["sdrcc.mapLab.trackMinutes", "7"]]);
    let lastTrackUrl = "";
    const fakeWindow = {
        localStorage: {
            getItem(key) { return stored.get(key) ?? null; },
            setItem(key, value) { stored.set(key, value); },
        },
        __maplibreMock: {Map: FakeMap, Popup: FakePopup, NavigationControl: class {}, ScaleControl: class {}},
        setInterval() {},
    };
    node("layer-tracks").checked = false; // HTML default: tracks are opt-in
    const patched = source.replace(esm, "await Promise.resolve(window.__maplibreMock)");
    vm.runInNewContext(patched, {
        document, window: fakeWindow, setInterval() {},
        fetch: async url => {
            if (url.startsWith("/api/map-lab/ais-tracks?")) lastTrackUrl = url;
            return url === "/api/map-lab/vts-sectors"
            ? {ok:true, json:async () => vts}
            : url === "/api/map-lab/highlights"
            ? {ok:true, json:async () => highlights}
            : url.startsWith("/api/map-lab/ais-tracks?minutes=")
            ? {ok:true, json:async () => ({
                ok:true,available:true,track_count:2,point_count:5,
                geojson:{type:"FeatureCollection",features:[
                    {type:"Feature",properties:{mmsi:"244555000",shipclass:5},
                     geometry:{type:"LineString",coordinates:[[4.3,51.9],[4.42,51.94]]}},
                    {type:"Feature",properties:{mmsi:"123456789",shipclass:6},
                     geometry:{type:"LineString",coordinates:[[4.2,51.9],[4.25,51.93],[4.3,51.9]]}},
                ]},
            })}
            : url.startsWith("/api/map-lab/aircraft-photo/")
            ? {ok:true, json:async () => ({
                ok:true, image_url:"https://cdn.planespotters.net/mock.jpg",
                source_url:"https://www.planespotters.net/photo/123",
                photographer:"Example Photographer", source:"Planespotters.net",
            })}
            : {ok:true, json:async () => data};
        },
    });
    await new Promise(resolve => setImmediate(resolve));
    assert(instance, "map must be constructed");
    assert.equal(node("map-lab-legend").open, true, "stored legend preference ignored");
    node("map-lab-legend").open = false;
    node("map-lab-legend").listeners.toggle();
    assert.equal(stored.get("sdrcc.mapLab.legendOpen"), "0",
        "collapsing the legend must be persisted");
    assert.equal(node("track-duration").value, "7", "saved track duration ignored");
    assert.equal(node("track-duration-value").textContent, "7 min");
    instance.callbacks.load();
    await new Promise(resolve => setImmediate(resolve));

    assert.equal(Object.keys(instance.images).length, 76); // 56 AIS class symbols + 4 offshore + 14 labels + 2 planes
    assert(!instance.images["sdrcc-tug"], "tugs must reuse class icons at distant zoom");
    for(const id of ["sdrcc-offshore-wtg","sdrcc-offshore-wtg-unverified",
                     "sdrcc-offshore-platform","sdrcc-offshore-platform-unverified"]){
        assert(instance.images[id], "missing offshore symbol "+id);
    }
    for (const name of [
        "sdrcc-ship-6-moving", "sdrcc-ship-2-moving-unverified",
        "sdrcc-ship-1-still", "sdrcc-plane", "sdrcc-plane-no-course",
    ]) assert(instance.images[name], "missing " + name);
    for(const code of Array.from({length:14}, (_,i)=>i)){
        for(const movement of ["moving","still"]){
            assert(instance.images[`sdrcc-ship-${code}-${movement}`]);
            assert(instance.images[`sdrcc-ship-${code}-${movement}-unverified`]);
        }
    }

    for (let cls = 0; cls < 14; cls++)
        assert(instance.images["sdrcc-name-" + cls], "missing readable class nameplate");

    for (const kind of ["ais", "adsb"]) {
        const layer = instance.layers["sdrcc-" + kind + "-icons"];
        assert.equal(layer.type, "symbol", "traffic icons must be MapLibre symbols");
        assert.equal(layer.layout["icon-allow-overlap"], true);
        assert.equal(layer.layout["icon-ignore-placement"], true);
        assert.equal(layer.layout["icon-rotation-alignment"], "map");
        assert.equal(layer.layout["icon-pitch-alignment"], "viewport");
        assert.deepEqual(JSON.parse(JSON.stringify(layer.layout["icon-rotate"])),
            kind === "ais"
                ? ["case", ["get", "is_offshore_structure"], 0,
                    ["get", "is_moving"], ["coalesce", ["get", "course"], 0], 0]
                : ["coalesce", ["get", "course"], 0]);
        assert(instance.callbacks["click:sdrcc-" + kind + "-icons"]);
    }
    const boats = instance.sources["sdrcc-ais"].data.features;
    const planes = instance.sources["sdrcc-adsb"].data.features;
    assert.equal(boats.length, 14);
    for (const target of boats.slice(12,14)) {
        assert.equal(target.properties.render_profile,"pleasure");
        assert.equal(target.properties.icon_name,"sdrcc-ship-3-still",
            "Class B keeps existing AIS icon at low zoom");
        assert.equal(target.properties.hull_available,true);
    }
    assert.equal(boats[12].properties.hull_geometry_source,
        "Illustrative Class B pleasure hull; antenna offsets unavailable");
    assert.equal(boats[13].properties.hull_geometry_source,"AIS dimensions");
    assert.equal(boats[10].properties.icon_name,"sdrcc-offshore-platform");
    assert.equal(boats[10].properties.hull_available,false);
    assert.equal(boats[11].properties.render_profile,"port_authority");
    assert.equal(boats[11].properties.icon_name,"sdrcc-ship-5-moving");
    assert.equal(boats[11].properties.hull_available,true);
    assert.equal(boats[11].properties.hull_geometry_source,
                 "Published dimensions; approximate AIS position offset");
    assert.equal(boats[11].properties.hull_bearing_approximate,true);
    assert.equal(boats[9].properties.render_profile,"krve");
    assert.equal(boats[9].properties.icon_name,"sdrcc-ship-7-moving",
        "KRVE must retain the normal HSC symbol while zoomed out");
    assert.equal(boats[9].properties.hull_available,true);
    assert.equal(boats[9].properties.length_m,10);
    assert.equal(boats[9].properties.icon_scale,.75);
    assert.equal(boats[8].properties.render_profile,"watertaxi");
    assert.equal(boats[8].properties.icon_name,"sdrcc-ship-7-moving",
        "MSTX must use normal AIS high-speed icon at low zoom");
    assert.equal(boats[8].properties.hull_available,true);
    assert.equal(boats[8].properties.length_m,11);
    assert.equal(boats[8].properties.icon_scale,0.75);
    assert.equal(boats[7].properties.icon_name,"sdrcc-ship-5-still",
        "police must use its original AIS class icon when zoomed out");
    assert.equal(boats[7].properties.render_profile,"police");
    assert.equal(boats[7].properties.hull_available,true);
    assert.equal(boats[6].properties.icon_name,"sdrcc-ship-5-still");
    assert.equal(boats[6].properties.hull_available,true);
    assert.equal(boats[3].properties.icon_name,"sdrcc-offshore-wtg");
    assert.equal(boats[3].properties.icon_scale,0.78,
        "WTG should be reduced to a similar size as offshore platform icons");
    assert.equal(boats[4].properties.icon_scale,0.9,
        "offshore platforms should have 20% larger icons");
    assert.equal(boats[4].properties.icon_name,"sdrcc-offshore-platform");
    assert.equal(boats[3].properties.hull_available,false);
    assert.equal(boats[4].properties.hull_available,false);
    assert.equal(boats[5].properties.render_profile,"cargo");
    assert.equal(planes.length, 1);
    assert.equal(boats[0].properties.course, 132);
    assert.equal(boats[0].properties.course_known, true);
    assert.equal(boats[0].properties.icon_name, "sdrcc-ship-6-moving");
    assert.equal(boats[0].properties.is_moving, true);
    assert.equal(boats[1].properties.validation_state, "unverified");
    assert.equal(boats[1].properties.icon_name, "sdrcc-ship-2-moving-unverified");
    assert.equal(boats[2].properties.course, null);
    assert.equal(boats[2].properties.course_known, false);
    assert.equal(boats[2].properties.icon_name, "sdrcc-ship-1-still");
    assert.equal(boats[2].properties.is_moving, false);
    assert.equal(planes[0].properties.course, 212);

    const polygons = instance.sources["sdrcc-ais-hulls"].data.features;
    assert.equal(polygons.length, 9,
        "existing seven 3D models plus two new Class B hulls only");
    const decks=instance.sources["sdrcc-ais-decks"].data.features;
    assert.equal(decks.length,46,
        "existing 38 deck parts plus four for each Class B vessel");
    for(const part of ["bridge","cargo-hatch","tanker-pipe","tanker-cap","tug-wheelhouse","tug-winch",
                       "police-cabin","police-stripe","police-lightbar",
                       "watertaxi-cabin","watertaxi-roof","watertaxi-stripe","watertaxi-window",
                       "krve-workdeck","krve-cabin","krve-roof","krve-fender",
                       "krve-windows","krve-mooring-gear","rpa-cabin","rpa-roof",
                       "rpa-yellow-stripe","rpa-windows","rpa-fire-monitor",
                       "pleasure-deck","pleasure-cabin","pleasure-windshield","pleasure-cockpit"])
        assert(decks.some(f=>f.properties.part===part), "missing deck part "+part);
    assert(decks.every(f=>["123456789","244123999","244555000",
        "244600015","244020742","244456065","244050469",
        "244901101","244901102"].includes(f.properties.id)));
    assert.equal(decks.filter(f=>f.properties.id==="244901101").length,4);
    assert.equal(decks.filter(f=>f.properties.id==="244901102").length,4);
    assert(instance.layers["sdrcc-ais-hull-3d"].paint["fill-extrusion-color"]
        .includes("#29475b"),"Class B boat hull is dark blue");
    assert(instance.layers["sdrcc-ais-hull-decks"].paint["fill-extrusion-color"]
        .includes("#f7f8f3"),"Class B boat cabin is white");
    const rpaDetails=decks.filter(f=>f.properties.id==="244050469");
    assert.equal(rpaDetails.length,7);
    assert(instance.layers["sdrcc-ais-hull-3d"].paint["fill-extrusion-color"]
        .includes("#1d4c79"),"RPA hull must be navy blue");
    assert(instance.layers["sdrcc-ais-hull-decks"].paint["fill-extrusion-color"]
        .includes("#f7d438"),"RPA needs bright yellow flank stripes");
    const krveParts=decks.filter(f=>f.properties.id==="244456065");
    assert.equal(krveParts.length,8,"KRVE has a cabin, roof, yellow fenders, windows and working deck");
    const krveRoof=krveParts.find(f=>f.properties.part==="krve-roof");
    assert(krveRoof.properties.base_height_m>2.5);
    assert(instance.layers["sdrcc-ais-hull-3d"].paint["fill-extrusion-color"]
        .includes("#20272e"),"KRVE hull is dark");
    assert(instance.layers["sdrcc-ais-hull-decks"].paint["fill-extrusion-color"]
        .includes("#f8bf1e"),"KRVE fenders are yellow");
    const taxideck=decks.filter(f=>f.properties.id==="244020742");
    assert.equal(taxideck.length,6);
    assert(Math.abs(taxideck.find(f=>f.properties.part==="watertaxi-roof")
        .properties.base_height_m - 2.9)<0.001);
    assert(instance.layers["sdrcc-ais-hull-3d"].paint["fill-extrusion-color"]
        .includes("#11161c"),"water taxi hull must be black");
    assert(instance.layers["sdrcc-ais-hull-decks"].paint["fill-extrusion-color"]
        .includes("#ffd31a"),"water taxi roof must be yellow");
    assert(decks.every(f=>f.geometry.coordinates[0].every(p=>p.every(Number.isFinite))));
    assert.equal(instance.layers["sdrcc-ais-hull-decks"].minzoom,15);
    assert.equal(instance.layers["sdrcc-ais-hull-decks"].type,"fill-extrusion");
    assert(instance.layers["sdrcc-ais-hull-3d"].paint["fill-extrusion-color"]
        .includes !== undefined, "police hull paint layer must remain distinct");
    assert(JSON.stringify(instance.layers["sdrcc-ais-hull-3d"].paint["fill-extrusion-color"])
        .includes("police"), "police hull must receive a distinctive navy colour");
    assert(instance.callbacks["click:sdrcc-ais-hull-decks"]);
    assert.equal(instance.layers["sdrcc-ais-hull-fill"].type, "fill");
    assert.equal(instance.layers["sdrcc-ais-hull-border"].type, "line");
    const extrusion = instance.layers["sdrcc-ais-hull-3d"];
    assert.equal(extrusion.type, "fill-extrusion");
    assert.equal(extrusion.layout.visibility, "none");
    assert.deepEqual(JSON.parse(JSON.stringify(extrusion.paint["fill-extrusion-height"])),
        ["get", "display_height_m"]);
    assert(instance.callbacks["click:sdrcc-ais-hull-3d"]);
    assert.equal(polygons[0].properties.display_height_m, 7.22);
    assert.equal(instance.layers["sdrcc-ais-hull-fill"].minzoom, 14);
    const ring = polygons[0].geometry.coordinates[0];
    assert.equal(ring.length, 8, "stern, shoulders, bow and closed polygon");
    assert.deepEqual(ring[0], ring[ring.length - 1], "hull polygon must close");
    assert(ring.every(pair => pair.every(Number.isFinite)), "hull geometry must be finite");
    // Antenna offset is real-world metres: a 140 m ship must not remain a fixed-sized icon.
    const x = (point) => (point[0] - 4.3) * 111320 * Math.cos(51.9 * Math.PI / 180);
    const y = (point) => (point[1] - 51.9) * 111320;
    const forward = p => x(p) * Math.sin(134*Math.PI/180) + y(p)*Math.cos(134*Math.PI/180);
    const projected = ring.map(forward);
    const length = Math.max(...projected) - Math.min(...projected);
    assert(length > 138 && length < 142, "hull should span the actual 140 metres");
    assert.equal(boats[0].properties.hull_available, true);
    assert.equal(boats[1].properties.hull_available, false);
    assert.equal(boats[0].properties.length_m, 140);
    // Exact, non-overlapping zoom ranges: no cartoon icon drawn on top of a hull.
    assert.equal(instance.layers["sdrcc-ais-icons"].maxzoom, 14);
    assert.equal(instance.layers["sdrcc-ais-fallback-icons"].minzoom, 14);
    assert.deepEqual(JSON.parse(JSON.stringify(instance.layers["sdrcc-ais-fallback-icons"].filter)),
        ["!=", ["get", "hull_available"], true]);
    assert.equal(instance.layers["sdrcc-ais-labels"].minzoom, 12.5);
    const labels = instance.layers["sdrcc-ais-labels"];
    assert.equal(labels.layout["icon-text-fit"], "both");
    assert.deepEqual(JSON.parse(JSON.stringify(labels.layout["icon-text-fit-padding"])), [2,4,2,4]);
    assert.deepEqual(JSON.parse(JSON.stringify(labels.layout["text-variable-anchor"])),
        ["top","bottom","right","left"], "AIS names must move away from ship markers");
    const sizes = JSON.parse(JSON.stringify(labels.layout["text-size"]));
    assert.equal(sizes[0], "interpolate");
    assert.equal(sizes[sizes.length-1], 9.5, "labels must stay compact even at maximum zoom");
    assert.equal(labels.layout["text-radial-offset"][0], "interpolate",
        "AIS text must be offset away from vessel icons and hulls");
    assert.equal(labels.layout["text-radial-offset"].at(-1), 5);
    assert.deepEqual(JSON.parse(JSON.stringify(labels.layout["text-field"])),
        ["get", "label_name"]);
    assert.equal(labels.paint["text-color"][0], "match");
    assert(instance.callbacks["click:sdrcc-ais-labels"]);
    assert(instance.callbacks["click:sdrcc-adsb-labels"]);
    const colors = JSON.parse(JSON.stringify(instance.layers["sdrcc-ais-labels"].paint["text-color"]));
    assert.equal(colors[0], "match");
    assert(colors.includes("#17232b"), "light nameplates use dark text for contrast");
    assert.equal(boats[0].properties.label_name, "Known ship");
    assert(instance.callbacks["click:sdrcc-ais-hull-fill"], "hull must be selectable");

    assert.equal(node("count-ais").textContent, 14);
    assert.equal(node("count-adsb").textContent, 1);
    assert.equal(node("legend-mini-status").textContent, "AIS 14 · ADS-B 1",
        "compact legend must still show live receiver target counts");
    assert.equal(instance.sources["sdrcc-home"].data.features.length, 1);
    const home = instance.sources["sdrcc-home"].data.features[0];
    assert.deepEqual(JSON.parse(JSON.stringify(home.geometry.coordinates)), [4.28,51.93]);
    assert.equal(home.properties.name, "EyeVisions Home");
    assert.equal(node("station-status").textContent, "Home Position");
    assert.equal(node("vts-status").textContent, "1 RWS sectors");
    // Live Emergency Monitor and ATIS rings overlay the original vessel.
    // The Map Lab polls its observer endpoint after traffic refresh.
    for (let i = 0; i < 8; i++) await Promise.resolve();
    assert(instance.layers["sdrcc-emergency-ring"]);
    assert(instance.layers["sdrcc-atis-ring"]);
    assert.deepEqual(JSON.parse(JSON.stringify(
        instance.layers["sdrcc-emergency-ring"].paint["circle-stroke-color"])),
        ["match",["get","category"],"knrm","#ffffff","waterpolitie","#2499ff","#ffffff"]);
    assert.equal(instance.sources["sdrcc-emergency"].data.features.length, 2);
    assert.equal(instance.sources["sdrcc-atis"].data.features.length, 1);
    assert.equal(node("emergency-status").textContent, "2 highlighted");
    assert.equal(node("atis-status").textContent, "ATIS matched");
    assert.deepEqual(JSON.parse(JSON.stringify(
        instance.sources["sdrcc-atis"].data.features[0].geometry.coordinates)),
        [4.3,51.9]);
    assert(instance.paintChanges.some(p =>
        p.id === "sdrcc-atis-ring" && p.key === "circle-radius"),
        "rings should pulse without modifying camera");

    assert.equal(instance.sources["sdrcc-vts"].data.features.length, 1);
    assert.equal(instance.sources["sdrcc-vts"].data.features[0].properties.color, "#e5007e");
    assert.equal(instance.layers["sdrcc-vts-fill"].type, "fill");
    assert.equal(instance.layers["sdrcc-vts-line"].type, "line");
    assert(!instance.layers["sdrcc-vts-labels"],
        "sector labels must never cover vessels in the shipping lanes");
    assert(instance.layers["sdrcc-home-name"]);
    assert(instance.callbacks["click:sdrcc-home-dot"]);
    assert(!instance.callbacks["click:sdrcc-vts-fill"],
        "clicking water must not pop up VTS info or steal ship clicks");

    assert.equal(instance.layers["sdrcc-ais-track"].type,"line");
    assert.equal(instance.layers["sdrcc-ais-track"].layout.visibility,"none");
    node("layer-tracks").checked = true;
    node("layer-tracks").listeners.change();
    assert(instance.layoutChanges.some(x=>x.id==="sdrcc-ais-track"&&x.value==="visible"));
    for(let i=0;i<8;i++) await Promise.resolve();
    assert.equal(instance.sources["sdrcc-ais-track"].data.features.length,2);
    assert(node("track-status").textContent.includes("2 vessel tracks"));
    assert.equal(lastTrackUrl, "/api/map-lab/ais-tracks?minutes=7");
    assert.equal(instance.layers["sdrcc-ais-track"].paint["line-color"][0],"match");
    node("track-duration").value = "1";
    node("track-duration").listeners.input();
    assert.equal(node("track-duration-value").textContent, "1 min");
    node("track-duration").listeners.change();
    for (let i=0;i<8;i++) await Promise.resolve();
    assert.equal(stored.get("sdrcc.mapLab.trackMinutes"), "1");
    assert.equal(lastTrackUrl, "/api/map-lab/ais-tracks?minutes=1");
    node("track-duration").value = "60";
    node("track-duration").listeners.change();
    for (let i=0;i<8;i++) await Promise.resolve();
    assert.equal(lastTrackUrl, "/api/map-lab/ais-tracks?minutes=60");
    node("show-names").checked = false;
    node("show-names").listeners.change();
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-labels" && change.value === "none"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-icons" && change.value === "visible"),
        "hiding labels must not hide distant ship arrows");
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-fallback-icons" && change.value === "visible"),
        "hiding labels must not hide fallback ship arrows");

    // Clicking a plane requests the optional photo only at selection time.
    instance.callbacks["click:sdrcc-adsb-icons"]({features:[planes[0]]});
    assert(lastPopup && lastPopup.element, "aircraft popup must open");
    // Flush the small async chain: fetch -> JSON -> render image / attribution.
    for (let i = 0; i < 8; i++) await Promise.resolve();
    const card = lastPopup.element;
    const detailLines = card.children.map(item => item.children?.map(child => child.textContent).join("") || "");
    assert(detailLines.some(x => x.includes("Registration: PH-BGX")));
    assert(detailLines.some(x => x.includes("Type: B738")));
    const photo = card.children.find(child => child.className === "popup-photo");
    assert(photo && photo.children.some(child =>
        child.tag === "img" && child.src.startsWith("https://cdn.planespotters.net/")),
        "credited aircraft image must be rendered on click");
    assert(photo.children.some(child => child.textContent.includes("Example Photographer")));
    instance.callbacks["click:sdrcc-ais-hull-3d"]({features:[polygons[0]]});
    assert(lastPopup.element.children.some(child =>
        child.children?.some(value => value.textContent.includes("Length"))));
    assert(lastPopup.element.children.some(child =>
        child.children?.some(value => value.textContent.includes("Emergency vessel"))));
    assert(lastPopup.element.children.some(child =>
        child.children?.some(value => value.textContent.includes("Matched Marine ATIS"))));

    node("mode-3d").listeners.click();
    assert.equal(instance.camera.pitch, 62);
    assert(instance.layers["sdrcc-buildings"], "existing 3D buildings preserved");
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-buildings" && change.value === "visible"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-3d" && change.value === "visible"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-decks" && change.value === "visible"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-fill" && change.value === "none"));

    node("layer-emergency").checked = false;
    node("layer-emergency").listeners.change();
    assert(instance.layoutChanges.some(c=>c.id==="sdrcc-emergency-ring"&&c.value==="none"));
    node("layer-atis").checked = false;
    node("layer-atis").listeners.change();
    assert(instance.layoutChanges.some(c=>c.id==="sdrcc-atis-ring"&&c.value==="none"));
    node("layer-vts").checked = false;
    node("layer-vts").listeners.change();
    assert(instance.layoutChanges.some(c => c.id==="sdrcc-vts-fill" && c.value==="none"));
    assert(instance.layoutChanges.some(c => c.id==="sdrcc-vts-line" && c.value==="none"));
    node("layer-station").checked = false;
    node("layer-station").listeners.change();
    assert(instance.layoutChanges.some(c => c.id==="sdrcc-home-name" && c.value==="none"));
    assert(instance.layoutChanges.some(c => c.id==="sdrcc-home-ring" && c.value==="none"));

    // Clicking another vessel must not replace the all-vessel trail set.
    instance.callbacks["click:sdrcc-ais-icons"]({features:[boats[6]]});
    for (let i=0;i<8;i++) await Promise.resolve();
    assert.equal(instance.sources["sdrcc-ais-track"].data.features.length,2);
    node("layer-tracks").checked=false;
    node("layer-tracks").listeners.change();
    assert.equal(instance.sources["sdrcc-ais-track"].data.features.length,0);
    assert(instance.layoutChanges.some(x=>x.id==="sdrcc-ais-track"&&x.value==="none"));
    node("layer-ais").checked = false;
    node("layer-ais").listeners.change();
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-icons" && change.value === "none"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-fill" && change.value === "none"),
        "hiding AIS must hide actual hull polygons too");
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-decks" && change.value === "none"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-3d" && change.value === "none"),
        "hiding AIS must hide 3D hulls too");
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-fallback-icons" && change.value === "none"),
        "hiding AIS must hide zoomed-in fallback vessels too");

    console.log("PASS: 76 AIS/aircraft sprites, original distant tug icons, all-vessel tracks and 3D hull, "
        + "emergency/ATIS matched rings, visibility, nameplates and 3D");
})().catch(error => {console.error(error); process.exitCode = 1;});
