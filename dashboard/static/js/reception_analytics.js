/* Read-only RF graphs for SDRCC, drawn with native SVG. */
(() => {
"use strict";
const byId=n=>document.getElementById(n);
let period="24h",busy=false;
const format=(v,d=0)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString("en-GB",{maximumFractionDigits:d});
function draw(svg,points,key,color,title){
 svg.replaceChildren();svg.setAttribute("viewBox","0 0 600 160");svg.setAttribute("role","img");svg.setAttribute("aria-label",title);
 const ns="http://www.w3.org/2000/svg";
 const add=(tag,attrs,txt)=>{const e=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));if(txt!==undefined)e.textContent=txt;svg.append(e);};
 for(const y of [20,55,90,125])add("line",{x1:40,x2:585,y1:y,y2:y,stroke:"#34546c"});
 const valid=points.map(p=>p[key]).filter(v=>v!=null&&Number.isFinite(Number(v))).map(Number);
 if(!valid.length){add("text",{x:300,y:84,fill:"#a5c5d7","text-anchor":"middle","font-size":14},"No samples yet");return;}
 const max=Math.max(1,...valid);let segment=[];
 const flush=()=>{if(segment.length)add("polyline",{points:segment.join(" "),fill:"none",stroke:color,"stroke-width":3,"stroke-linecap":"round"});segment=[];};
 points.forEach((p,i)=>{
  const v=p[key];if(v==null||!Number.isFinite(Number(v))){flush();return;}
  const x=40+(points.length===1?0:i/(points.length-1))*540;
  segment.push(x.toFixed(1)+","+(125-Number(v)/max*103).toFixed(1));
 });flush();
 add("text",{x:40,y:15,fill:"#c7e6f4","font-size":12},format(max,2));
 add("text",{x:40,y:148,fill:"#8aaabd","font-size":11},"0");
 add("text",{x:585,y:154,fill:"#8aaabd","font-size":11,"text-anchor":"end"},new Date(points[points.length-1].ts*1000).toLocaleString());
}
async function refresh(){
 if(busy||!byId("analytics-samples"))return;
 busy=true;byId("analytics-updated").textContent="Loading history…";
 try{
  const response=await fetch("/api/reception-analytics?period="+period,{cache:"no-store"});
  if(!response.ok)throw Error("API "+response.status);
  const data=await response.json(),s=data.summary,m=data.marine;
  const values={"analytics-samples":format(s.samples),"analytics-ais-peak":format(s.ais_peak),
    "analytics-adsb-peak":format(s.adsb_peak),
    "analytics-ais-range":s.ais_range==null?"—":format(s.ais_range,1)+" NM",
    "analytics-adsb-range":s.adsb_range==null?"—":format(s.adsb_range,1)+" NM",
    "analytics-marine-clips":format(m.clips),"analytics-atis-count":format(m.validated),
    "analytics-matched-count":format(m.matched),
    "analytics-ais-average":s.ais_avg==null?"— msg/s":format(s.ais_avg,2)+" msg/s",
    "analytics-adsb-average":s.adsb_avg==null?"— msg/s":format(s.adsb_avg,2)+" msg/s"};
  Object.entries(values).forEach(([k,v])=>byId(k).textContent=v);
  for(const [id,key,color] of [["analytics-ais-targets","ais_targets","#38bdf8"],
   ["analytics-adsb-targets","adsb_targets","#a78bfa"],
   ["analytics-ais-rate","ais_rate","#31d5aa"],
   ["analytics-adsb-rate","adsb_rate","#fbbf24"]])draw(byId(id),data.series,key,color,key);
  byId("analytics-updated").textContent="Updated "+new Date(data.updated_at).toLocaleTimeString()+" · samples every 60 seconds";
 }catch(e){byId("analytics-updated").textContent="History unavailable: "+e.message;}
 finally{busy=false;}
}
byId("analytics-period")?.addEventListener("change",e=>{period=e.target.value;void refresh();});
byId("analytics-refresh")?.addEventListener("click",()=>void refresh());
window.addEventListener("sdrcc:tab-changed",e=>{if(e.detail?.tab==="reception-analytics")void refresh();});
})();
