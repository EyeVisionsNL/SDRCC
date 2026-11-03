#!/usr/bin/env node
"use strict";
// Slow-browser regression for Marine/Airband Voice start/stop and status polling.
// No SDR, live server, network, permissions or system services required.
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "dashboard/static/js/traffic_voice.js"), "utf8");
const html = fs.readFileSync(path.join(root, "dashboard/templates/index.html"), "utf8");
assert.match(html, /\/static\/js\/traffic_voice\.js\?v=\{\{ asset_version \}\}/,
    "Voice script must use the installed SDRCC version so clients load bug fixes");
const exportSource = source.replace(/\}\)\(\);\s*$/, `globalThis.test = {
    refresh, runAction,
    setRender(fn) { render = fn; },
    setRenderError(fn) { renderError = fn; },
    isBusy() { return actionBusy; }
};})();`);
assert.notEqual(exportSource, source, "Expected test injection at IIFE end");

function deferred() {
    let resolve, reject;
    const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
    return {promise, resolve, reject};
}
const response = (payload, ok = true) => ({
    ok, status: ok ? 200 : 500, json: async () => payload,
});
function node() {
    return {
        disabled: false, textContent: "", dataset: {}, src: "",
        classList: {contains: () => true, add() {}, remove() {}, toggle() {}},
        getAttribute(name) { return name === "src" ? this.src : ""; },
        removeAttribute(name) { if (name === "src") this.src = ""; },
        setAttribute(name) { if (name === "disabled") this.disabled = true; },
        pause() {}, load() {},
    };
}
function boot() {
    const requests = [];
    const renders = [], errors = [];
    const controls = [node(), node()];
    const nodes = {
        "tab-traffic-voice": node(),
        "traffic-voice-action-message": node(),
        "traffic-voice-audio": node(),
        "traffic-voice-audio-toggle": node(),
        "traffic-voice-audio-detail": node(),
    };
    const ctx = {
        console, AbortController,
        fetch(url, options) {
            const task = deferred();
            requests.push({url, options, ...task});
            return task.promise;
        },
        document: {
            hidden: false, readyState: "loading",
            getElementById: id => nodes[id] || null,
            querySelectorAll: () => controls,
            addEventListener() {},
            querySelector() { return null; },
        },
        window: {setTimeout: () => 1, clearTimeout() {}, addEventListener() {}},
    };
    vm.runInNewContext(exportSource, ctx, {filename: "traffic_voice.js"});
    ctx.test.setRender(payload => { renders.push(payload); });
    ctx.test.setRenderError(error => errors.push(error.message));
    return {test: ctx.test, requests, renders, errors, nodes, controls};
}
async function tick() { await Promise.resolve(); await Promise.resolve(); }
async function main() {
    // Old GET finishes while the STOP POST is in progress: never render it.
    const a = boot();
    const oldGet = a.test.refresh(true);
    assert.equal(a.requests.length, 1);
    const stopping = a.test.runAction("stop");
    assert.equal(a.requests.length, 2);
    assert.equal(a.requests[0].options.signal.aborted, true);
    a.requests[0].resolve(response({service: {active: true}, modes: []}));
    await oldGet;
    assert.equal(a.renders.length, 0, "stale GET cannot resurrect the Voice state");
    a.requests[1].resolve(response({
        ok: true, message: "Voice stopped",
        snapshot: {ok: true, service: {active: false}, modes: []},
    }));
    await stopping;
    assert.equal(a.renders.at(-1).service.active, false);
    assert(!a.controls.some(button => button.disabled), "buttons recover after success");
    assert.equal(a.test.isBusy(), false);

    // Slow previous polling response must never replace a newer one.
    const b = boot();
    const older = b.test.refresh(true);
    const newer = b.test.refresh(true);
    assert.equal(b.requests[0].options.signal.aborted, true);
    b.requests[1].resolve(response({service: {active: true}, modes: []}));
    await newer;
    b.requests[0].resolve(response({service: {active: false}, modes: []}));
    await older;
    assert.equal(b.renders.length, 1);
    assert.equal(b.renders[0].service.active, true);

    // Polling every three seconds must not spawn simultaneous requests.
    const c = boot();
    const first = c.test.refresh(true);
    await c.test.refresh(false);
    assert.equal(c.requests.length, 1, "overlapping interval poll suppressed");
    c.requests[0].resolve(response({service: {active: true}, modes: []}));
    await first;
    const second = c.test.refresh(false);
    assert.equal(c.requests.length, 2, "poll resumes once previous finishes");
    c.requests[1].resolve(response({service: {active: true}, modes: []}));
    await second;

    // POST or following status failure must not require a page reload to unlock controls.
    const d = boot();
    const fail = d.test.runAction("start_marine");
    d.requests[0].resolve(response({ok: false, message: "Receiver temporarily busy"}, false));
    await tick();
    assert.equal(d.requests.length, 2, "fallback GET after POST failure");
    assert(!d.controls.some(button => button.disabled),
        "action buttons are restored before slower fallback GET completes");
    d.requests[1].reject(new Error("Status temporarily unavailable"));
    await fail;
    assert.equal(d.test.isBusy(), false);
    assert.equal(d.errors.length, 1);
    const retry = d.test.runAction("start_marine");
    assert.equal(d.requests.length, 3, "another start can be attempted without reload");
    d.requests[2].resolve(response({ok: true, message: "Started",
        snapshot: {ok: true, modes: [], service: {active: true}}}));
    await retry;
    assert.equal(d.renders.at(-1).service.active, true);

    console.log("PASS: Voice stop/start survives slow polls, stale replies, failed GET/POST and recovers controls without browser reload");
}
main().catch(e => { console.error(e); process.exitCode = 1; });
