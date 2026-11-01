/* Native Reception Analytics: ADS-B left, AIS right, shared activity context. */
(() => {
"use strict";
const el=n=>document.getElementById(n),NS="http://www.w3.org/2000/svg";
let period="24h",busy=false;
const fmt=(v,d=0)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString("en-GB",{maximumFractionDigits:d});
function node(parent,tag,attrs,content){
 const n=document.createElementNS(NS,tag);
 Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));
 if(content!==undefined)n.textContent=content;
 parent.append(n);return n;
}
function plot(id,rows,key,color,label,windowStart,windowEnd,bucket){
 return plotSeries(id,rows,[{key,color}],label,windowStart,windowEnd,bucket);
}
function plotSeries(id,rows,lines,label,windowStart,windowEnd,bucket){
 const svg=el(id);svg.replaceChildren();svg.setAttribute("viewBox","0 0 640 174");
 svg.setAttribute("role","img");svg.setAttribute("aria-label",label);
 const left=47,right=631,top=18,bottom=136;
 for(let i=0;i<5;i++){let y=top+i*(bottom-top)/4;node(svg,"line",{x1:left,x2:right,y1:y,y2:y,stroke:"#40506a","stroke-opacity":".6"});}
 const values=lines.flatMap(line=>rows.map(r=>r[line.key]).filter(v=>v!=null&&Number.isFinite(Number(v))).map(Number));
 if(!values.length){node(svg,"text",{x:320,y:84,fill:"#94a3b8","text-anchor":"middle","font-size":15},"No samples for this period");return;}
 const max=Math.max(1,...values);
 node(svg,"text",{x:left,y:12,fill:"#cbd5e1","font-size":12},fmt(max,1));
 // Use the selected 24h/7d/30d time interval, not the earliest available sample.
 // This keeps AIS and ADS-B on the same horizontal scale after upgrades.
 const first=windowStart,last=windowEnd,span=Math.max(1,last-first);
 const largestGap=Math.max(2*bucket, 2);
 for(const line of lines){
  let points=[], previousTs=null;
  const flush=()=>{
   if(points.length>1)node(svg,"polyline",{points:points.join(" "),fill:"none",stroke:line.color,"stroke-width":2.8,"stroke-linecap":"round","stroke-linejoin":"round"});
   else if(points.length===1){const [x,y]=points[0].split(",");node(svg,"circle",{cx:x,cy:y,r:3,fill:line.color});}
   points=[];
  };
  for(const row of rows){
   const val=row[line.key];
   if(val==null||!Number.isFinite(Number(val))){flush();previousTs=null;continue;}
   if(previousTs!==null && row.ts-previousTs>largestGap)flush();
   previousTs=row.ts;
   // Never draw a point outside the requested time window.
   if(row.ts<first||row.ts>last)continue;
   points.push((left+(right-left)*(row.ts-first)/span).toFixed(2)+","+(bottom-Number(val)/max*(bottom-top)).toFixed(2));
  }
  flush();
 }
 const date=ts=>new Date(ts*1000).toLocaleString(undefined,{day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"});
 node(svg,"text",{x:left,y:168,fill:"#94a3b8","font-size":11},date(first));
 node(svg,"text",{x:right,y:168,fill:"#94a3b8","font-size":11,"text-anchor":"end"},date(last));
}
function activity(data){
 const svg=el("rx-activity-chart");svg.replaceChildren();svg.setAttribute("viewBox","0 0 1000 242");
 svg.setAttribute("role","img");svg.setAttribute("aria-label","Satellite missions, Marine Traffic, Airband Voice, ADS-B decoder and AIS receiver activity by time");
 const first=Math.floor((Date.now()/1000-data.period_seconds)/data.bucket_seconds)*data.bucket_seconds;
 const count=Math.ceil(data.period_seconds/data.bucket_seconds)+1,width=813/count,left=170;
 const byTime=new Map((data.series||[]).map(r=>[r.ts,r]));
 for(const [index,[key,label,color]] of [["mission_on","Satellite mission","#a78bfa"],["marine_on","Marine Traffic","#2dd4bf"],["airband_on","Airband Voice","#fb7185"],["adsb_on","ADS-B decoder","#fbbf24"],["ais_on","AIS receiver","#38bdf8"]].entries()){
   const y=15+index*38;node(svg,"text",{x:12,y:y+18,fill:"#cbd5e1","font-size":14},label);
   for(let i=0;i<count;i++){
     const ts=first+i*data.bucket_seconds,state=byTime.get(ts)?.[key];
     const rect=node(svg,"rect",{x:left+i*width,y,width:Math.max(.45,width-.45),height:28,rx:width>10?2:0,
       fill:state===1?color:state===0?"#303f55":"#162235",opacity:state===1?".92":"1"});
     node(rect,"title",{},new Date(ts*1000).toLocaleString()+" · "+label+": "+(state===1?"active":state===0?"inactive":"not sampled"));
   }
 }
 const tick=ts=>new Date(ts*1000).toLocaleString(undefined,{day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"});
 for(let i=0;i<=4;i++)node(svg,"text",{x:left+i*813/4,y:230,fill:"#94a3b8","font-size":12,"text-anchor":i===0?"start":i===4?"end":"middle"},tick(first+i*data.period_seconds/4));
}
async function refresh(){
 if(busy||!el("rx-activity-chart"))return;busy=true;el("analytics-updated").textContent="Loading measurements…";
 try{
  const response=await fetch("/api/reception-analytics?period="+period,{cache:"no-store"});
  if(!response.ok)throw Error("HTTP "+response.status);
  const d=await response.json(),s=d.summary||{},rows=d.series||[];
  const fields={"rx-adsb-peak":fmt(s.adsb_peak),
   "rx-ais-total-now":fmt(s.current_catcher_total),
   "rx-ais-fresh-now":fmt(s.current_ais_fresh),
   "rx-adsb-range":s.adsb_range==null?"—":fmt(s.adsb_range,1)+" NM",
   "rx-ais-range":s.ais_range==null?"—":fmt(s.ais_range,1)+" NM",
   "rx-adsb-rate":s.adsb_avg==null?"—":fmt(s.adsb_avg,2)+" msg/s",
   "rx-ais-rate":s.ais_avg==null?"—":fmt(s.ais_avg,2)+" msg/s",
   "rx-mission-minutes":fmt(s.mission_minutes),"rx-marine-minutes":fmt(s.marine_minutes),
   "rx-airband-minutes":fmt(s.airband_minutes)};
  Object.entries(fields).forEach(([k,v])=>el(k).textContent=v);
  const start=d.window_start,end=d.window_end,bucket=d.bucket_seconds;
  for(const [id,key,color] of [["rx-adsb-count","adsb_targets","#a78bfa"],["rx-adsb-messages","adsb_rate","#fbbf24"],["rx-ais-messages","ais_rate","#2dd4bf"]])plot(id,rows,key,color,key,start,end,bucket);
  plotSeries("rx-ais-count",rows,[
    {key:"ais_total",color:"#38bdf8"},
    {key:"ais_targets",color:"#2dd4bf"}
  ],"AIS-Catcher total targets compared with recent verified vessel positions",start,end,bucket);
  const stamp=t=>t?new Date(t*1000).toLocaleString():"not available";
  const gapStart=s.last_legacy_total?stamp(s.last_legacy_total):null;
  const gapEnd=s.first_new_total?stamp(s.first_new_total):null;
  const gap=gapStart&&gapEnd
    ? " · Total-target data not recorded between "+gapStart+" and "+gapEnd
    : gapStart&&!gapEnd?" · Total-target sampling has not resumed yet":"";
  el("rx-ais-coverage").textContent="Total-target history starts "+stamp(s.first_total_ais)+
    " · verified history starts "+stamp(s.first_fresh_ais)+gap+
    " · historical peak verified: "+fmt(s.ais_peak);
  const atis=d.atis||{};
  const atisFields={
    "rx-atis-received":fmt(atis.candidates),
    "rx-atis-decoded":fmt(atis.decoded),
    "rx-atis-photos":fmt(atis.photos),
    "rx-atis-decode-rate":atis.decode_percent==null?"—":fmt(atis.decode_percent,1)+"%",
    "rx-atis-photo-rate":atis.photo_percent==null?"—":fmt(atis.photo_percent,1)+"%"
  };
  Object.entries(atisFields).forEach(([id,value])=>el(id).textContent=value);
  if (atis.error||atis.last_error||atis.dropped_queue_events)
    el("rx-atis-note").textContent="ATIS statistics notice: "+
      (atis.error||atis.last_error||"event queue overflow")+
      " · dropped events: "+fmt(atis.dropped_queue_events);
  activity(d);
  el("rx-ais-status").textContent=s.fresh_ais_samples?"Verified · ≤5 minutes":"Awaiting fresh AIS";
  const age=s.last_sample_ts==null?null:Math.round(d.window_end-s.last_sample_ts);
  const lastStatus=age==null?"no samples recorded":age>180?"last sample "+Math.ceil(age/60)+" min ago":"latest sample "+Math.max(0,age)+" sec ago";
  const error=d.sampling_error?" · collector error: "+d.sampling_error:"";
  el("analytics-updated").textContent="Updated "+new Date(d.updated_at).toLocaleTimeString()+" · "+fmt(s.samples)+" samples · "+lastStatus+error;
 }catch(e){el("analytics-updated").textContent="Reception history unavailable: "+e.message;}
 finally{busy=false;}
}
el("analytics-period")?.addEventListener("change",e=>{period=e.target.value;void refresh();});
el("analytics-refresh")?.addEventListener("click",()=>void refresh());
window.addEventListener("sdrcc:tab-changed",e=>{if(e.detail?.tab==="reception-analytics")void refresh();});
})();
