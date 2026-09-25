// Browser preference and stream URL regression without receiver hardware.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../dashboard/static/js/traffic_voice.js'), 'utf8');
const saved = new Map([['sdrcc.trafficVoice.speechFilter', 'strong']]);
function boot(blocked=false) {
    let initialize, plays=0;
    const element = () => ({value:'', options:[], handlers:{}, addEventListener(e,fn){this.handlers[e]=fn;}});
    const filter = element(), denoise = element();
    denoise.options = ['off','speex','rnnoise'].map(value => ({value}));
    const audio = {src:'', dataset:{}, getAttribute(){return this.src;}, play:async()=>{plays++;}, pause(){}, load(){}, removeAttribute(){this.src='';}};
    const nodes = {'traffic-voice-speech-filter':filter,'traffic-voice-denoise':denoise,'traffic-voice-audio':audio};
    const storage = {getItem:k=>{if(blocked)throw Error(); return saved.get(k)||null;},setItem:(k,v)=>{if(blocked)throw Error();saved.set(k,v);}};
    const ctx = {console, localStorage:storage,document:{hidden:true,readyState:'loading',getElementById:id=>nodes[id]||null,querySelector:()=>null,addEventListener:(e,fn)=>{if(e==='DOMContentLoaded')initialize=fn;}},window:{addEventListener(){},setInterval(){return 1;},localStorage:storage}};
    vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, 'globalThis.test = {renderAudio};})();'), ctx);
    initialize();
    const render = (mode,available=true) => ctx.test.renderAudio({selected_mode:mode,audio:{stream_url:'/api/traffic-voice/audio-stream',denoisers:{speex:{available},rnnoise:{available}}}});
    return {filter,denoise,audio,render,plays:()=>plays};
}
(async()=>{
    let b=boot(); assert.equal(b.filter.value,'strong');
    b.render('marine_ais');b.audio.src='playing';
    b.denoise.value='speex';b.denoise.handlers.change({target:b.denoise});
    assert(b.audio.src.includes('denoise=speex')); assert(b.audio.src.includes('mode=marine_ais'));
    b.render('airband_adsb');assert.equal(b.filter.value,'off');assert.equal(b.denoise.value,'off');
    b.filter.value='light';b.filter.handlers.change({target:b.filter});
    b.denoise.value='rnnoise';b.denoise.handlers.change({target:b.denoise});
    assert(b.audio.src.includes('speech_filter=light'));assert(b.audio.src.includes('denoise=rnnoise'));
    b.render('marine_ais');assert.equal(b.filter.value,'strong');assert.equal(b.denoise.value,'speex');
    b=boot();b.render('airband_adsb');assert.equal(b.filter.value,'light');assert.equal(b.denoise.value,'rnnoise');
    b.render('airband_adsb',false);assert(b.denoise.options[2].disabled);assert(!b.denoise.options[0].disabled);
    assert.equal(b.plays(),0); // Rendering preferences must not start stopped audio.
    b=boot(true);assert.equal(b.filter.value,'normal');b.render('airband_adsb');assert.equal(b.filter.value,'off');
    await Promise.resolve();
    console.log('PASS: mode-specific browser persistence, legacy migration, live URLs, missing engines, storage failure and stopped audio');
})().catch(error=>{console.error(error);process.exit(1);});
