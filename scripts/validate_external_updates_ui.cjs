#!/usr/bin/env node
"use strict";
// Offline UI regression: unchanged status polls must never recreate buttons.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const root = path.join(__dirname, "..");
const src = fs.readFileSync(path.join(root, "dashboard/static/js/external_updates.js"), "utf8");
const markup = fs.readFileSync(path.join(root, "dashboard/templates/index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "dashboard/static/css/system.css"), "utf8");
assert(markup.includes('id="external-update-summary-detail"'),
    "collapsed summary must expose a live version-check summary");
assert(markup.includes('id="external-update-badge"'));
assert(markup.indexOf('id="ais-autostart-title"') < markup.indexOf('id="external-updates"'),
    "external update list should follow paired SDRCC/AIS maintenance controls");
assert(css.includes("#tab-system #external-updates > .system-maintenance-body-v0540f"),
    "nested external update body must override its parent's two-column layout");
assert(css.includes("grid-column: 1 / -1"),
    "external update section must span full maintenance grid");
assert(!src.includes("setInterval(() => { if (!pending) load(false); }, 5000)"),
    "old 5s repaint loop must be removed");
assert(src.includes("if (signature === lastSignature) return;"),
    "unchanged status results must not rebuild the DOM");

class Element {
    constructor(tag = "div") {
        this.tagName = tag;
        this.children = [];
        this.textContent = "";
        this.className = "";
        this.dataset = {};
        this.disabled = false;
        this.listeners = {};
        this.href = "";
    }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = [...children]; }
    addEventListener(event, callback) { this.listeners[event] = callback; }
    queryAll(predicate) {
        return [...(predicate(this) ? [this] : []),
            ...this.children.flatMap(c => c.queryAll(predicate))];
    }
}
let created = 0;
const ids = [
    "external-updates", "external-update-list", "external-update-check",
    "external-update-result", "external-update-badge",
    "external-update-summary-detail",
];
const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
const makeRow = (id, name, installed, latest, reason, available = false, can_install = false) => ({
    id, name, installed, latest, reason, available, can_install,
    url: "https://github.com/example/release",
});
let data = {ok: true, software: [
    makeRow("ais-catcher", "AIS-catcher", "0.70", "0.70", "Up to date"),
    makeRow("satdump", "SatDump", "Non-APT installation", null,
        "Managed outside APT; update requires manual review"),
    makeRow("readsb", "readsb", "3.16.15", null, "Pinned by SDRCC; compatibility review required"),
    makeRow("rtl-airband", "RTLSDR-Airband", "SDRCC patched v5.2.0", null,
        "Custom gain and scan patches; automatic upgrade disabled"),
], worker: {}, release_check_error: null};
const intervals = [];
let installCalls = 0;
const sandbox = {
    document: {
        getElementById(id) { return elements[id]; },
        createElement(tag) { created++; return new Element(tag); },
    },
    fetch: async url => {
        if (url.includes("/install")) {
            installCalls++;
            return {ok: true, json: async () => ({ok: true})};
        }
        return {ok: true, json: async () => data};
    },
    window: {confirm: () => false},
    setInterval: callback => intervals.push(callback),
    console,
};
const flush = () => new Promise(resolve => setImmediate(resolve));

(async () => {
    vm.runInNewContext(src, sandbox, {filename: "external_updates.js"});
    await flush();
    const list = elements["external-update-list"];
    assert.equal(list.children.length, 4);
    assert.equal(elements["external-update-badge"].textContent, "CHECK LIMITED");
    assert(elements["external-update-summary-detail"].textContent.includes("3 need verification"));
    assert.equal(list.queryAll(item => item.tagName === "button").length, 0,
        "up-to-date or manual tools must not show misleading blue update buttons");
    assert.equal(list.queryAll(item => item.tagName === "a").length, 4,
        "release notes must remain lightweight text links");
    const previousCards = list.children;
    const previousCreated = created;
    assert.equal(intervals.length, 1);
    intervals[0]();
    await flush();
    assert.equal(created, previousCreated, "stable status polling must create zero elements");
    assert.deepEqual(list.children, previousCards,
        "stable status polling must preserve existing card and button references");

    data = {...data, software: [
        {...data.software[0], status: "current"},
        {...data.software[1], installed: "1.2.2", latest: "1.2.2", status: "current",
            reason: "Current stable release (nightly builds excluded)"},
        {...data.software[2], installed: "3.16.15", latest: "3.16.20",
            available: true, can_install: false, status: "review",
            reason: "Newer development build; SDRCC receiver integration must be tested"},
        {...data.software[3], installed: "5.2.0 (SDRCC patched)", latest: "6.2.0",
            available: true, can_install: false, status: "review",
            reason: "New stable version; SDRCC patches need porting"},
    ]};
    intervals[0]();
    await flush();
    assert.equal(elements["external-update-badge"].textContent, "REVIEW REQUIRED");
    assert.equal(list.queryAll(item => item.tagName === "button").length, 0,
        "readsb and Airband need review, not automatic install controls");
    const body = list.queryAll(item => item.tagName === "p").map(item => item.textContent);
    assert(body.some(text => text.includes("Latest dev: 3.16.20")));
    assert(body.some(text => text.includes("Latest stable: 6.2.0")));

    data = {...data, software: [
        data.software[0],
        makeRow("satdump", "SatDump", "1.2.2", "1.2.3", "APT update available", true, true),
        data.software[2], data.software[3],
    ]};
    intervals[0]();
    await flush();
    assert.equal(elements["external-update-badge"].textContent, "1 UPDATE AVAILABLE");
    const buttons = list.queryAll(item => item.tagName === "button");
    assert.equal(buttons.length, 1);
    assert.equal(buttons[0].textContent, "⬆ Install 1.2.3");
    buttons[0].listeners.click();
    await flush();
    assert.equal(installCalls, 0, "cancelled confirmation must not install anything");

    data = {...data, worker: {state: "installing", software: "satdump",
        message: "Applying update."}};
    intervals[0]();
    await flush();
    assert.equal(elements["external-update-badge"].textContent, "UPDATING");
    assert.equal(list.queryAll(item => item.tagName === "button")[0].disabled, true);

    console.log("PASS: collapsed status, neutral cards, real update-only buttons and flicker-free polling");
})().catch(error => {console.error(error); process.exitCode = 1;});
