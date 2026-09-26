const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
(async () => {
    const calls = [], redirects = [];
    const location = {href:'https://8.8.8.8/', origin:'https://8.8.8.8', assign:p=>redirects.push(p)};
    const context = {URL, Request, Headers, location, document:{querySelector:()=>({content:'test-token'})},
        window:{fetch:async(input, options)=>{calls.push({input,options});return {status:input==='/expired'?401:200};}}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dashboard/static/js/security.js'),'utf8'),context);
    await context.window.fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    assert.equal(calls.at(-1).options.headers.get('X-CSRF-Token'),'test-token');
    assert.equal(calls.at(-1).options.headers.get('Content-Type'),'application/json');
    const body = new FormData(); body.append('file','channels');
    await context.window.fetch('/api/import',{method:'POST',body});
    assert.equal(calls.at(-1).options.body,body);
    assert.equal(calls.at(-1).options.headers.get('Content-Type'),null);
    await context.window.fetch(new Request('https://8.8.8.8/api/action',{method:'PUT',body:'{}'}));
    assert.equal(calls.at(-1).options.headers.get('X-CSRF-Token'),'test-token');
    await context.window.fetch('https://other.example/upload',{method:'POST'});
    assert.equal(calls.at(-1).options.headers,undefined);
    await context.window.fetch('/api/status');
    assert.equal(calls.at(-1).options.headers,undefined);
    await context.window.fetch('/expired');
    assert.deepEqual(redirects,['/login']);
    console.log('PASS: CSRF for JSON, multipart and Request; external URLs untouched; expired session redirects');
})().catch(error=>{console.error(error);process.exitCode=1;});
