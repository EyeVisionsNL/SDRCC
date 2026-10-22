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
const canvas = () => ({
    width: 0, height: 0,
    getContext: () => ({
        scale() {}, beginPath() {}, moveTo() {}, bezierCurveTo() {},
        lineTo() {}, quadraticCurveTo() {}, closePath() {},
        fill() {}, stroke() {}, fillRect() {}, arc() {}, fillText() {},
        getImageData(x, y, width, height) {
            return {width, height, data: new Uint8ClampedArray(width * height * 4)};
        },
    }),
});
const document = {
    hidden: false, getElementById: node,
    createElement(tag) {
        assert.equal(tag, "canvas");
        return canvas();
    },
};
let instance;
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
        assert.equal(image.height, 96);
        this.images[id] = image;
    }
    getStyle() {return {layers: []};}
    addLayer(layer) {
        if (layer.id.endsWith("-icons")) {
            assert(Object.keys(this.images).length === 58,
                "all 14 class colours and 2 aircraft sprites must be registered");
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
                lon:4.5, lat:51.92, course:212, altitude_ft:24000},
        ]},
    };
    const fakeWindow = {
        __maplibreMock: {Map: FakeMap, NavigationControl: class {}, ScaleControl: class {}},
        setInterval() {},
    };
    const patched = source.replace(esm, "await Promise.resolve(window.__maplibreMock)");
    vm.runInNewContext(patched, {
        document, window: fakeWindow, setInterval() {},
        fetch: async () => ({ok:true, json:async () => data}),
    });
    await new Promise(resolve => setImmediate(resolve));
    assert(instance, "map must be constructed");
    instance.callbacks.load();
    await new Promise(resolve => setImmediate(resolve));

    assert.equal(Object.keys(instance.images).length, 58); // 14 AIS classes × moving/still × verified/unverified + 2 aircraft
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
    const colors = JSON.parse(JSON.stringify(instance.layers["sdrcc-ais-labels"].paint["text-color"]));
    assert.equal(colors[0], "match");
    assert(colors.includes("#1fbf5c"), "cargo green");
    assert(colors.includes("#d93a2b"), "tanker red");
    assert(colors.includes("#2c4fd0"), "passenger blue");
    assert(colors.includes("#c04ef0"), "Class B purple");
    assert(instance.callbacks["click:sdrcc-ais-hull-fill"], "hull must be selectable");

    assert.equal(node("count-ais").textContent, 3);
    assert.equal(node("count-adsb").textContent, 1);

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

    node("mode-3d").listeners.click();
    assert.equal(instance.camera.pitch, 62);
    assert(instance.layers["sdrcc-buildings"], "existing 3D buildings preserved");
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-buildings" && change.value === "visible"));

    node("layer-ais").checked = false;
    node("layer-ais").listeners.change();
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-icons" && change.value === "none"));
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-hull-fill" && change.value === "none"),
        "hiding AIS must hide actual hull polygons too");
    assert(instance.layoutChanges.some(change =>
        change.id === "sdrcc-ais-fallback-icons" && change.value === "none"),
        "hiding AIS must hide zoomed-in fallback vessels too");

    console.log("PASS: AIS-catcher colours, 58 map sprites, class-specific arrows and dots, "
        + "nonoverlapping zoom layers, 140m hull, labels, toggles and 3D");
})().catch(error => {console.error(error); process.exitCode = 1;});
