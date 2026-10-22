#!/usr/bin/env node
"use strict";
// Read-only UI regression: a failed same-version develop -> main update must
// display its underlying error instead of a misleading channel reminder.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../dashboard/static/js/update_manager.js"), "utf8");

async function scenario(worker, sameVersion) {
    const nodes = {};
    const node = id => nodes[id] ||= {
        classList: {toggle(){}, add(){}, remove(){}, contains(){return false;}},
        toggleAttribute(){}, setAttribute(){}, addEventListener(){}, disabled:false
    };
    const data = {
        installed_version: "0.68.2", latest_version: sameVersion ? "0.68.2" : "0.68.3",
        beta_program: false, installed_channel:"develop", source_channel:"main",
        channel_change_pending: true, update_available: true,
        same_version: sameVersion, can_complete_audio_setup:false, worker
    };
    vm.runInNewContext(source,{
        document: {getElementById:node},
        fetch: async()=>({ok:true,json:async()=>data}),
        setTimeout(){},setInterval(){},clearInterval(){},
        window:{location:{reload(){}}},confirm(){return true},
    });
    await new Promise(resolve=>setImmediate(resolve));
    return nodes;
}
(async()=>{
    for(const sameVersion of [true,false]){
        const nodes = await scenario({
            state:"failed", message:"Update source missing: docs/example.md"
        },sameVersion);
        assert.equal(nodes["sdrcc-update-badge"].textContent, "UPDATE FAILED");
        assert.match(nodes["sdrcc-update-result"].textContent,/Update source missing/);
        assert.equal(nodes["sdrcc-update-install"].disabled,false);
    }
    const nodes=await scenario({state:"idle"},true);
    assert.equal(nodes["sdrcc-update-install"].textContent,"Switch to stable");
    assert.match(nodes["sdrcc-update-result"].textContent,/develop.*main/);
    console.log("PASS: same-version channel failure is visible and retry remains possible");
})().catch(e=>{console.error(e);process.exitCode=1;});
