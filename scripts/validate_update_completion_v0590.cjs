const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../dashboard/static/js/update_manager.js'), 'utf8');
async function scenario(overrides, expected) {
    const nodes = {};
    const intervals = [];
    let posts = 0, reloads = 0;
    const worker = {state:'success', current_version:'0.57.0', target_version:'0.59.0', updated_at:new Date().toISOString(), ...overrides};
    const data = {installed_version:'0.59.0', latest_version:'0.59.0', same_version:true, can_complete_audio_setup:true, worker};
    vm.runInNewContext(source, {
        document:{getElementById(id) {return nodes[id] ||= {addEventListener(){}};}},
        fetch:async(url, options) => {
            if (options.method === 'POST') { posts++; return {ok:true, json:async()=>({ok:true})}; }
            return {ok:true, json:async()=>data};
        },
        setTimeout(){}, setInterval(fn, ms){intervals.push({fn, ms});return intervals.length;}, clearInterval(){},
        window:{location:{reload(){reloads++;}}}, confirm:()=>true,
    });
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(posts, expected);
    assert.equal(nodes['sdrcc-update-install'].textContent, 'Complete audio setup');
    assert.equal(nodes['sdrcc-update-install'].disabled, false);
    for (const timer of intervals) await timer.fn();
    assert.equal(posts, expected, 'no repeated automatic completion');
    assert.equal(reloads, 0, 'stale success must not trigger reload');
    if (expected) {
        data.can_complete_audio_setup = false;
        data.worker = {...worker, current_version:'0.59.0', audio_setup_attempted:true};
        await intervals.find(timer=>timer.ms===2000).fn();
        assert.equal(reloads, 1, 'completed repair reloads dashboard');
    }
}
(async()=>{
    await scenario({}, 1);
    await scenario({audio_setup_attempted:true}, 0);
    await scenario({current_version:'0.59.0'}, 0);
    await scenario({updated_at:new Date(Date.now()-16*60*1000).toISOString()}, 0);
    await scenario({state:'failed'}, 0);
    console.log('PASS: old-worker continuation, manual retry, stale-status protection and no automatic retry loop');
})().catch(error=>{console.error(error);process.exitCode=1;});
