const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const source=fs.readFileSync('dashboard/static/js/traffic_map_lab.js','utf8');
const start=source.indexOf('    function deckCollection('), end=source.indexOf('    function hasHull(',start);
const ctx={hullMinLength:()=>5}; vm.createContext(ctx);
vm.runInContext(source.slice(start,end)+'; this.deckCollection=deckCollection;',ctx);
for(const heading of [0,90,177.1,270]) {
 const ship={id:'244700532',render_profile:'water_supply',to_bow:12.5,to_stern:12.5,to_port:3,to_starboard:3,lon:4.4,lat:51.9,hull_heading:heading};
 const result=ctx.deckCollection([ship],{features:[{properties:{id:ship.id,display_height_m:1.8}}]});
 assert.equal(result.features.length,11);
 const parts=result.features.map(f=>f.properties.part);
 for(const part of ['water-house','water-windows','water-roof','water-pipe','water-hatch','water-pump','water-hose']) assert(parts.includes(part));
 for(const f of result.features){
  assert(f.properties.top_height_m>f.properties.base_height_m);
  for(const [lon,lat] of f.geometry.coordinates[0]) {
   const x=(lon-ship.lon)*111320*Math.cos(ship.lat*Math.PI/180), y=(lat-ship.lat)*111320;
   const a=heading*Math.PI/180, forward=x*Math.sin(a)+y*Math.cos(a),right=x*Math.cos(a)-y*Math.sin(a);
   assert(Math.abs(forward)<=12.5+1e-6); assert(Math.abs(right)<=3+1e-6);
  }
 }
}
console.log('PASS: water supply model equipment, heights, AIS bounds and four headings');
