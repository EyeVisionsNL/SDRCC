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
const esm = 'await import("https://unpkg.com/maplibre-gl@6.14.0/dist/maplibre-gl.mjs")';
assert(source.includes(esm), "MapLibre 6 import unexpectedly changed");

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
            assert(Object.keys(this.images).length === 72,
                "14 nameplates, 56 class symbols and 2 aircraft sprites must be registered");
        }
        this.layers[layer.id] = layer;
    }
    getLayer(id) {return this.layers[id];}
    setLayoutProperty(id, key, value) {
        this.layoutChanges.push({id, key, value});
    }
    easeTo(camera) {this.camera = camera;}
    jumpTo(camera) {this.camera = camera;}
    getCanvas() {return {style: {}};}
}

(async () => {
    const data = {
        ok: true, center: [4.28, 51.93],
        station: {name:"EyeVisions Home", lon:4.28, lat:51.93, altitude_m:12},
        ais: {available: true, source_count: 3, count: 3, unverified_count: 1,
            targets: [
                {type:"ais", id:"123456789", name:"Known ship",
                    lon:4.3, lat:51.9, course:132, hull_heading:134, speed_knots:6,
                    length_m:140, to_bow:110, to_stern:30,
                    to_port:9, to_starboard:10, hull_available:true, shipclass:6,
                    validation_state:"verified"},
                {type:"ais", id:"987654321", name:"Unverified ship",
                    lon:4.4, lat:51.91, course:90, speed_knots:7, shipclass:2,
                    validation_state:"unverified"},
                {type:"ais", id:"111222333", name:"No heading",
                    lon:4.31, lat:51.9, course:null, validation_state:"unknown"},
            ]},
        adsb: {available: true, source_count: 1, count: 1, targets:[
            {type:"adsb", id:"4ca123", name:"TEST123",
                registration:"PH-BGX", aircraft_type:"B738", operator:"KLM",
                squawk:"4720", lon:4.5, lat:51.92, course:212, altitude_ft:24000},
        ]},
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
    const fakeWindow = {
        __maplibreMock: {Map: FakeMap, Popup: FakePopup, NavigationControl: class {}, ScaleControl: class {}},
        setInterval() {},
    };
    const patched = source.replace(esm, "await Promise.resolve(window.__maplibreMock)");
    vm.runInNewContext(patched, {
        document, window: fakeWindow, setInterval() {},
        fetch: async url => url === "/api/map-lab/vts-sectors"
            ? {ok:true, json:async () => vts}
            : url.startsWith("/api/map-lab/aircraft-photo/")
            ? {ok:true, json:async () => ({
                ok:true, image_url:"https://cdn.planespotters.net/mock.jpg",
                source_url:"https://www.planespotters.net/photo/123",
                photographer:"Example Photographer", source:"Planespotters.net",
            })}
            : {ok:true, json:async () => data},
    });
    await new Promise(resolve => setImmediate(resolve));
    assert(instance, "map must be constructed");
    instance.callbacks.load();
    await new Promise(resolve => setImmediate(resolve));

    assert.equal(Object.keys(instance.images).length, 72); // 56 AIS symbols + 14 coloured nameplates + 2 aircraft
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
                ? ["case", ["get", "is_moving"], ["coalesce", ["get", "course"], 0], 0]
                : ["coalesce", ["get", "course"], 0]);
        assert(instance.callbacks["click:sdrcc-" + kind + "-icons"]);
    }
    const boats = instance.sources["sdrcc-ais"].data.features;
    const planes = instance.sources["sdrcc-adsb"].data.features;
    assert.equal(boats.length, 3);
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
    assert.equal(polygons.length, 1, "only ships with real dimensions get hull outlines");
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

    assert.equal(node("count-ais").textContent, 3);
    assert.equal(node("count-adsb").textContent, 1);
    assert.equal(instance.sources["sdrcc-home"].data.features.length, 1);
    const home = instance.sources["sdrcc-home"].data.features[0];
    assert.deepEqual(JSON.parse(JSON.stringify(home.geometry.coordinates)), [4.28,51.93]);
    assert.equal(home.properties.name, "EyeVisions Home");
    assert.equal(node("station-status").textContent, "Home Position");
    assert.equal(node("vts-status").textContent, "1 RWS sectors");
    assert.equal(instance.sources["sdrcc-vts"].data.features.length, 1);
    assert.equal(instance.sources["sdrcc-vts"].data.features[0].properties.color, "#e5007e");
    assert.equal(instance.layers["sdrcc-vts-fill"].type, "fill");
    assert.equal(instance.layers["sdrcc-vts-line"].type, "line");
    assert(instance.layers["sdrcc-vts-labels"]);
    assert(instance.layers["sdrcc-home-name"]);
    assert(instance.callbacks["click:sdrcc-home-dot"]);
    assert(instance.callbacks["click:sdrcc-vts-fill"]);

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

    node("mode-3d").listeners.click();
    assert.equal(instance.camera.pitch, 62);
    assert(instance.layers["sdrcc-buildings"], "existing 3D buildings preserved");
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-buildings" && change.value === "visible"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-3d" && change.value === "visible"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-fill" && change.value === "none"));

    node("layer-vts").checked = false;
    node("layer-vts").listeners.change();
    assert(instance.layoutChanges.some(c => c.id==="sdrcc-vts-fill" && c.value==="none"));
    assert(instance.layoutChanges.some(c => c.id==="sdrcc-vts-line" && c.value==="none"));
    node("layer-station").checked = false;
    node("layer-station").listeners.change();
    assert(instance.layoutChanges.some(c => c.id==="sdrcc-home-name" && c.value==="none"));
    assert(instance.layoutChanges.some(c => c.id==="sdrcc-home-ring" && c.value==="none"));

    node("layer-ais").checked = false;
    node("layer-ais").listeners.change();
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-icons" && change.value === "none"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-fill" && change.value === "none"),
        "hiding AIS must hide actual hull polygons too");
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-3d" && change.value === "none"),
        "hiding AIS must hide 3D hulls too");
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-fallback-icons" && change.value === "none"),
        "hiding AIS must hide zoomed-in fallback vessels too");

    console.log("PASS: 72 AIS/aircraft sprites including 14 nameplates, 140m 3D hull, "
        + "borderless labels, Home Position, VTS sectors, toggles and 3D visibility");
})().catch(error => {console.error(error); process.exitCode = 1;});
