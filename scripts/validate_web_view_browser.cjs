const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
(async () => {
    for (const viewer of ['ais','adsb']) {
        const calls = [], events = [];
        const metas = {'sdrcc-view-prefix':`/web/${viewer}/`, 'sdrcc-view-upstream-path':viewer==='ais'?'/':'/tar1090/', 'csrf-token':'test-token'};
        class XHR {open(...args){this.args=args;} send(){} setRequestHeader(k,v){this.header=[k,v];}}
        const location = {href:`https://8.8.8.8/web/${viewer}/?mmsi=123456789`,origin:'https://8.8.8.8'};
        const context={URL,Request,Headers,XMLHttpRequest:XHR,location,
            document:{querySelector(selector){return {content:metas[selector.match(/name="([^"]+)/)[1]]};}},
            window:{fetch:async(input, options)=>{calls.push([input,options]);return {status:200};},
                EventSource:class {constructor(url){events.push(url);} static OPEN=1;}}};
        vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dashboard/static/js/web_view_bridge.js'),'utf8'),context);
        await context.window.fetch('/api/ships.json');
        assert.equal(calls.at(-1)[0],`https://8.8.8.8/web/${viewer}/api/ships.json`);
        await context.window.fetch('api/decode',{method:'POST',body:'message'});
        assert.equal(calls.at(-1)[1].headers.get('X-CSRF-Token'),'test-token');
        await context.window.fetch('https://tiles.example/1/2/3.png');
        assert.equal(calls.at(-1)[0],'https://tiles.example/1/2/3.png');
        assert.equal(calls.at(-1)[1].headers,undefined);
        await context.window.fetch(new Request('https://8.8.8.8/api/decode',{method:'POST',body:'message'}));
        assert.equal(calls.at(-1)[0].url,`https://8.8.8.8/web/${viewer}/api/decode`);
        const xhr=new XHR();xhr.open('GET','/ships.json');
        assert.equal(xhr.args[1],`https://8.8.8.8/web/${viewer}/ships.json`);
        new context.window.EventSource('/api/sse');
        assert.equal(events[0],`https://8.8.8.8/web/${viewer}/api/sse`);
        assert.equal(context.window.EventSource.OPEN,1);
    }
    console.log('PASS: viewer fetch, Request, XHR, EventSource and external tile URLs');
})().catch(error=>{console.error(error);process.exitCode=1;});
