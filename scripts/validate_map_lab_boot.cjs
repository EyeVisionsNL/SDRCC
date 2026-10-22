#!/usr/bin/env node
"use strict";
/*
 * Regression for MapLibre GL JS 6: the ESM namespace provides Map but no
 * supported() function. Test startup with an offline module substitute.
 * No receiver services or external network are touched.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
    path.join(__dirname, "../dashboard/static/js/traffic_map_lab.js"), "utf8");
const importStatement =
    'await import("https://unpkg.com/maplibre-gl@6.14.0/dist/maplibre-gl.mjs")';

assert(source.includes(importStatement), "expected pinned MapLibre ESM import");
assert(!source.includes("maplibregl.supported()"),
    "MapLibre v6 has no supported() API");
const stubbed = source.replace(importStatement, "await Promise.resolve(window.__maplibreMock)");
assert(stubbed.startsWith("/* SDRCC Map Lab:"));
const runner = new Function(
    "document", "window", "fetch",
    stubbed.replace("(async () => {", "return (async () => {"));

const fixture = mock => {
    const nodes = {};
    const element = id => nodes[id] ||= {
        textContent: "", checked: true, setAttribute() {}, addEventListener() {},
        classList: {add() {}, remove() {}},
    };
    return {
        nodes,
        run: () => runner(
            {getElementById: element, hidden: false},
            {__maplibreMock: mock, setInterval() {}},
            async () => ({ok: true, json: async () => ({})}),
        ),
    };
};

(async () => {
    let constructed = 0;
    const v6 = {
        Map: class {
            constructor(options) {
                assert.equal(options.container, "map");
                constructed++;
            }
            addControl() {}
            on() {}
        },
        NavigationControl: class {},
        ScaleControl: class {},
    };
    const normal = fixture(v6);
    await normal.run();
    assert.equal(constructed, 1, "MapLibre 6 Map constructor must run");

    const noGpu = fixture({
        Map: class {constructor() {throw new Error("WebGL unavailable");}},
    });
    await noGpu.run();
    assert.match(noGpu.nodes["map-error"].textContent,
        /Map initialization failed: WebGL unavailable/);

    const badCdn = fixture({});
    await badCdn.run();
    assert.match(badCdn.nodes["map-error"].textContent,
        /MapLibre library could not load.*Map export is missing/);

    console.log("PASS: MapLibre v6 boots without supported(), CDN/GPU errors separated");
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
