/* Historical Marine audio replay: only existing archive and photo APIs. */
(() => {
"use strict";
const id=n=>document.getElementById(n),list=id("marine-replay-list");if(!list)return;
let offset=0,busy=false;
const el=(tag,cls,value)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n;};
function details(row,card){
 const wrap=el("div","replay-details"),audio=el("audio","replay-audio");
 audio.controls=true;audio.preload="none";audio.src=row.audio_url;wrap.append(audio);
 if(row.mmsi){
  const line=el("div","replay-photo-row"),photo=el("img","replay-photo"),credit=el("span","history-note","Finding credited vessel photo…");
  photo.hidden=true;photo.alt="Vessel photo";photo.loading="lazy";line.append(photo,credit);wrap.append(line);
  fetch("/api/traffic-voice/vessel-photo?mmsi="+encodeURIComponent(row.mmsi)+"&shipname="+encodeURIComponent(row.shipname||""),{cache:"no-store"})
    .then(r=>r.json()).then(v=>{
      if(!wrap.isConnected)return;
      if(v.ok&&v.image_url){photo.src=v.image_url;photo.hidden=false;credit.textContent=v.artist||v.source_name||"Photo source";}
      else credit.textContent="Photo not available.";
    }).catch(()=>credit.textContent="Photo not available.");
 }
 const lat=Number(row.lat),lon=Number(row.lon);
 if(row.lat!=null&&row.lon!=null&&Number.isFinite(lat)&&Number.isFinite(lon)&&Math.abs(lat)<=90&&Math.abs(lon)<=180){
  wrap.append(el("p","history-note","AIS position at reception: "+lat.toFixed(5)+"°, "+lon.toFixed(5)+"°"));
  const button=el("button","control-button","Show historical location"),frame=el("iframe","replay-map");
  frame.hidden=true;frame.loading="lazy";frame.title="Historical AIS position at reception";
  button.addEventListener("click",()=>{
    frame.hidden=!frame.hidden;button.textContent=frame.hidden?"Show historical location":"Hide location";
    if(!frame.hidden&&!frame.getAttribute("src")){
      const bbox=[lon-.012,lat-.007,lon+.012,lat+.007].join(",");
      frame.src="https://www.openstreetmap.org/export/embed.html?bbox="+encodeURIComponent(bbox)+"&layer=mapnik&marker="+encodeURIComponent(lat+","+lon);
    }
  });wrap.append(button,frame);
 }else wrap.append(el("p","history-note","Historical AIS position unavailable."));
 card.append(wrap);
}
function render(data){
 list.replaceChildren();
 id("marine-replay-count").textContent=data.total+" archived recordings · "+data.retention_days+" days / "+data.storage_limit_mb+" MB maximum";
 if(!data.rows.length)list.append(el("p","history-note","No recordings yet. New Marine transmissions will be saved automatically."));
 data.rows.forEach(row=>{
  const box=el("article","card replay-entry"),head=el("div","replay-entry-head"),left=el("div","replay-entry-info");
  left.append(el("strong","",row.shipname||row.channel||"Marine transmission"));
  left.append(el("p","",new Date(row.received_at).toLocaleString()+" · "+Number(row.duration).toFixed(1)+" s · "+(row.channel||"Channel unknown")));
  left.append(el("span","replay-match"+(row.mmsi?" matched":""),row.mmsi?"POSSIBLE SPEAKER":"NO VERIFIED AIS MATCH"));
  const button=el("button","control-button","Replay / details");head.append(left,button);box.append(head);
  if(row.code)box.append(el("p","replay-identity","ATIS "+row.code+(row.mmsi?" · MMSI "+row.mmsi:" · "+row.status)));
  button.addEventListener("click",()=>{
    const open=box.querySelector(".replay-details");
    if(open){open.remove();button.textContent="Replay / details";}else{details(row,box);button.textContent="Close details";}
  });
  list.append(box);
 });
 id("marine-replay-newer").disabled=offset===0;
 id("marine-replay-older").disabled=offset+data.rows.length>=data.total;
}
async function refresh(){
 if(busy)return;busy=true;id("marine-replay-message").textContent="Loading archive…";
 try{
  const r=await fetch("/api/marine-replay?limit=50&offset="+offset,{cache:"no-store"});
  if(!r.ok)throw Error("API "+r.status);
  render(await r.json());
  id("marine-replay-message").textContent="Local archive · only validated ATIS/AIS matches are identified as possible speakers.";
 }catch(e){id("marine-replay-message").textContent="Replay unavailable: "+e.message;}
 finally{busy=false;}
}
id("marine-replay-refresh").addEventListener("click",()=>void refresh());
id("marine-replay-newer").addEventListener("click",()=>{offset=Math.max(0,offset-50);void refresh();});
id("marine-replay-older").addEventListener("click",()=>{offset+=50;void refresh();});
window.addEventListener("sdrcc:tab-changed",e=>{if(e.detail?.tab==="marine-replay")void refresh();});
})();
