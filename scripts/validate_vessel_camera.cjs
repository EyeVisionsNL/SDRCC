// Simulated DOM: no camera network requests until the user opens a player.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
    constructor() { this.children=[]; this.events={}; this.open=false; }
    addEventListener(name, fn) { this.events[name]=fn; }
    setAttribute(name, value) { this[name]=value; }
    appendChild(child) { this.children.push(child); }
    replaceChildren() { this.children=[]; }
    showModal() { this.open=true; }
    close() { this.open=false; this.events.close?.(); }
    click() { this.events.click?.(); }
}
const ids={};
for(const id of ['traffic-voice-vessel-camera','vessel-camera-dialog','vessel-camera-player','vessel-camera-title','vessel-camera-identity','vessel-camera-source','vessel-camera-close']) ids[id]=new Element();
const document=new Element(); Object.assign(document,{readyState:'complete',hidden:false,getElementById:id=>ids[id],createElement:()=>new Element()});
const window=new Element();
vm.runInNewContext(fs.readFileSync('dashboard/static/js/vessel_camera.js','utf8'),{window,document,URL});
const api=window.sdrccVesselCamera;
const camera={mmsi:'244010927',shipname:'CARISMA',page_url:'https://webcam-binnenvaart.nl/pages/cam-carisma.php'};
const payload={selected_mode:'marine_ais',service:{active:true},ais_match:{matched:true,mmsi:camera.mmsi},vessel_camera:camera};
const button=ids['traffic-voice-vessel-camera'], player=ids['vessel-camera-player'], dialog=ids['vessel-camera-dialog'];
api.render(payload); assert.equal(button.hidden,false); assert.equal(player.children.length,0);
button.click(); assert.equal(dialog.open,true); assert.equal(player.children.length,1);
assert.equal(player.children[0].src,camera.page_url+'#my-video');
api.render({...payload,ais_match:{matched:false}}); assert.equal(button.hidden,true); assert.equal(player.children[0].src,camera.page_url+'#my-video');
ids['vessel-camera-close'].click(); assert.equal(dialog.open,false); assert.equal(player.children.length,0);
for(const url of ['https://evil.test/cam.php','javascript:alert(1)',camera.page_url+'?token=x','https://webcam-binnenvaart.nl.evil.test/pages/cam-x.php']) {
 api.render({...payload,vessel_camera:{...camera,page_url:url}}); assert.equal(button.hidden,true); button.click(); assert.equal(player.children.length,0);
}
api.render({...payload,ais_match:{matched:true,mmsi:'999999999'}}); assert.equal(button.hidden,true);
api.render(payload); button.click(); dialog.events.cancel(); assert.equal(player.children.length,0);
button.click(); document.hidden=true; document.events.visibilitychange(); assert.equal(dialog.open,false); assert.equal(player.children.length,0);
const history=new Element(); api.addHistoryButton(history,camera); assert.equal(player.children.length,0); history.children[0].click(); assert.equal(dialog.open,true);
api.render({...payload,service:{active:false}}); assert.equal(dialog.open,false); assert.equal(button.hidden,true);
api.render(payload); button.click(); api.render(null); assert.equal(player.children.length,0);
console.log('PASS: on-demand camera, identity/URL guards, history, fixed vessel, Escape/close/hidden/stopped cleanup');
