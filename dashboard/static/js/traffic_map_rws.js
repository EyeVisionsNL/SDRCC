/* SDRCC Map Lab — read-only Hoek van Holland tide and wind.
 * Uses the SAME localhost Rijkswaterstaat relay and AQO requests as the
 * AIS-Catcher Rijnmond VTS block layer. Never controls AIS/SDR receivers.
 */
(() => {
    "use strict";
    const el = id => document.getElementById(id);
    const outer = el("map-lab-legend");
    const refreshButton = el("rws-refresh");
    const chart = el("rws-tide-chart");
    if (!outer || !refreshButton || !chart) return;
    const status = el("rws-source");
    const tideLabel = el("rws-tide-summary");
    const highLabel = el("rws-next-high");
    const windLabel = el("rws-wind-value");
    const windMeta = el("rws-wind-meta");
    const windArrow = el("rws-wind-arrow");
    const relay = window.location.protocol + "//" + window.location.hostname + ":8120/";
    const intervalMs = 10 * 60 * 1000;
    let interval = null;
    let busy = false;
    let lastRequest = 0;

    const pad = n => String(n).padStart(2, "0");
    function rwsDate(date) {
        const offset = -date.getTimezoneOffset();
        const abs = Math.abs(offset);
        return date.getFullYear() + "-" + pad(date.getMonth()+1) + "-"
            + pad(date.getDate()) + "T" + pad(date.getHours()) + ":"
            + pad(date.getMinutes()) + ":" + pad(date.getSeconds())
            + (offset >= 0 ? "+" : "-") + pad(Math.floor(abs/60)) + ":" + pad(abs%60);
    }
    function tideRequest(processType, begin, end) {
        return {
            Locatie: {Code:"hoekvanholland"},
            AquoPlusWaarnemingMetadata: {AquoMetadata: {
                Compartiment:{Code:"OW"}, Grootheid:{Code:"WATHTE"},
                Hoedanigheid:{Code:"NAP"}, Eenheid:{Code:"cm"},
                ProcesType:processType,
            }},
            Periode:{Begindatumtijd:rwsDate(begin),Einddatumtijd:rwsDate(end)},
        };
    }
    function windRequest(code) {
        return {
            LocatieLijst:[{Code:"hoekvanholland"}],
            AquoPlusWaarnemingMetadataLijst:[{
                AquoMetadata:{Compartiment:{Code:"LT"},Grootheid:{Code:code}},
                WaarnemingMetadata:{OpdrachtgevendeInstantieLijst:["RIKZ_METEO"]},
            }],
        };
    }
    async function post(endpoint, body) {
        const response = await fetch(relay + "ONLINEWAARNEMINGENSERVICES/" + endpoint, {
            method:"POST", mode:"cors", cache:"no-store",
            headers:{"Content-Type":"application/json"}, body:JSON.stringify(body),
        });
        if (response.status === 204) return null;
        if (!response.ok) throw new Error("RWS HTTP " + response.status);
        return response.json();
    }
    function samples(payload) {
        const result = [];
        const visited = new Set();
        function scan(node, unit) {
            if (!node || typeof node !== "object" || result.length >= 5000 || visited.has(node)) return;
            visited.add(node);
            if (Array.isArray(node)) {
                for (const child of node) scan(child,unit);
                return;
            }
            const meta = node.AquoMetadata || node.AquoPlusWaarnemingMetadata?.AquoMetadata
                || node.AquoMetadataLocatie?.AquoMetadata || {};
            const u = (meta.Eenheid || node.Eenheid || node.eenheid)?.Code
                || (typeof meta.Eenheid === "string" ? meta.Eenheid : unit);
            const timestamp = node.Tijdstip || node.TijdstipMeting || node.DatumTijd
                || node.Datumtijd || node.time || node.timestamp;
            const measurement = node.Meetwaarde || node.meetwaarde || node;
            const fields = ["Waarde_Numeriek","WaardeNumeriek","Waarde_Alfanumeriek",
                "WaardeAlfanumeriek","Waarde","waarde"];
            let value = null;
            for (const key of fields) {
                const raw=measurement[key];
                if (raw === "" || raw === null || raw === undefined) continue;
                const parsed = Number(String(raw).replace(",","."));
                if (Number.isFinite(parsed)) {value=parsed;break;}
            }
            if (timestamp && value !== null) {
                const time=Date.parse(timestamp);
                if (Number.isFinite(time)) result.push({time,value,unit:String(u||"")});
            }
            for (const [key,child] of Object.entries(node)) {
                if (key !== "Meetwaarde" && key !== "meetwaarde" && child && typeof child === "object")
                    scan(child,u);
            }
        }
        scan(payload,"");
        const unique=new Map();
        for(const item of result)unique.set(item.time+"|"+item.value+"|"+item.unit,item);
        return [...unique.values()].sort((a,b)=>a.time-b.time);
    }
    const toMetres = item => {
        const unit=item.unit.toLowerCase();
        return unit.includes("mm")?item.value/1000:unit.includes("cm")||!unit?item.value/100:item.value;
    };
    const speedMps = item => {
        const u=item.unit.toLowerCase().replace(/\s/g,"");
        return u.includes("km/h")||u.includes("km/u")||u==="kmh"
            ?item.value/3.6:u.includes("kn")?item.value*.514444:item.value;
    };
    const clock = t => new Date(t).toLocaleTimeString("nl-NL",{hour:"2-digit",minute:"2-digit"});
    const level = n => n.toFixed(2).replace(".",",") + " m NAP";
    const beaufort = n => [0.3,1.6,3.4,5.5,8,10.8,13.9,17.2,20.8,24.5,28.5,32.7]
        .findIndex(x=>n<x);
    const windPoint = d => ["N","NNO","NO","ONO","O","OZO","ZO","ZZO",
        "Z","ZZW","ZW","WZW","W","WNW","NW","NNW"][Math.round(((d%360+360)%360)/22.5)%16];
    const NS="http://www.w3.org/2000/svg";
    function svg(tag, attrs, label) {
        const n=document.createElementNS(NS,tag);
        for (const [key,val] of Object.entries(attrs))n.setAttribute(key,String(val));
        if(label!==undefined)n.textContent=label;
        return n;
    }
    function renderChart(measured,predicted) {
        chart.replaceChildren();
        const series=measured.concat(predicted);
        if (!series.length) {
            chart.appendChild(svg("text",{x:150,y:59,"text-anchor":"middle"},"Getijgegevens niet beschikbaar"));
            return;
        }
        const minTime=Math.min(...series.map(p=>p.time));
        const maxTime=Math.max(...series.map(p=>p.time),minTime+1);
        let low=Math.min(...series.map(p=>p.value)),high=Math.max(...series.map(p=>p.value));
        if(high===low){low-=.1;high+=.1;}
        const margin=(high-low)*.12;low-=margin;high+=margin;
        const x=t=>34+(t-minTime)/(maxTime-minTime)*255;
        const y=v=>80-(v-low)/(high-low)*66;
        for(const frac of [0,.5,1]){
            const yy=14+66*frac;
            chart.appendChild(svg("line",{x1:34,y1:yy,x2:289,y2:yy,stroke:"#34566e","stroke-width":1}));
        }
        chart.appendChild(svg("text",{x:30,y:16,"text-anchor":"end"},high.toFixed(1)));
        chart.appendChild(svg("text",{x:30,y:81,"text-anchor":"end"},low.toFixed(1)));
        for(const [points,color,dash] of [[predicted,"#fbb76a","5 3"],[measured,"#65c5ef",""]]){
            if(!points.length)continue;
            chart.appendChild(svg("path",{
                d:points.map((p,i)=>(i?"L":"M")+x(p.time).toFixed(1)+" "+y(p.value).toFixed(1)).join(" "),
                fill:"none",stroke:color,"stroke-width":2,
                "stroke-linecap":"round","stroke-dasharray":dash,
            }));
        }
        if(measured.length) {
            const last=measured[measured.length-1];
            chart.appendChild(svg("circle",{cx:x(last.time),cy:y(last.value),r:3,fill:"#65c5ef"}));
        }
        chart.appendChild(svg("text",{x:34,y:102},clock(minTime)));
        chart.appendChild(svg("text",{x:288,y:102,"text-anchor":"end"},clock(maxTime)));
    }
    function renderWind(speedItem, directionItem) {
        const speed=speedItem?speedMps(speedItem):null;
        const direction=directionItem?directionItem.value:null;
        const validDirection=direction!==null&&Number.isFinite(direction);
        if(validDirection) {
            windArrow.setAttribute("transform","rotate("+(((direction%360+360)%360+180)%360)+" 18 18)");
        }
        windArrow.setAttribute("visibility",validDirection&&(speed===null||speed>=.3)?"visible":"hidden");
        if(speed!==null&&Number.isFinite(speed)) {
            const force=beaufort(speed);
            const label=speed<.3?"Windstil":validDirection?"Wind uit "+windPoint(direction):"Wind";
            windLabel.textContent=label+(validDirection?" · "+Math.round(direction)+"°":"")
                +" · "+speed.toFixed(1).replace(".",",")+" m/s · "+(force<0?12:force)+" Bft";
        }else{
            windLabel.textContent=validDirection?"Wind uit "+windPoint(direction)
                +" · "+Math.round(direction)+"°":"Windgegevens niet beschikbaar";
        }
        const ts=speedItem?.time||directionItem?.time;
        const older=ts&&Date.now()-ts>30*60*1000;
        windMeta.textContent="RWS Hoek van Holland · "+(ts?clock(ts):"geen meettijd")
            +(older?" · ouder dan 30 min":"");
    }
    async function refresh() {
        if(busy)return;
        busy=true;refreshButton.disabled=true;
        status.textContent="Rijkswaterstaat-data ophalen…";
        const now=new Date(),start=new Date(now.getTime()-6*3600000);
        const end=new Date(now.getTime()+7*3600000);
        const requests=[
            ["OphalenWaarnemingen",tideRequest("meting",start,now)],
            ["OphalenWaarnemingen",tideRequest("astronomisch",start,end)],
            ["OphalenLaatsteWaarnemingen",windRequest("WINDSHD")],
            ["OphalenLaatsteWaarnemingen",windRequest("WINDRTG")],
        ];
        try{
            const settled=await Promise.allSettled(requests.map(([endpoint,body])=>post(endpoint,body)));
            const parsed=settled.map((result)=>result.status==="fulfilled"?samples(result.value):[]);
            const measured=parsed[0].map(p=>({...p,value:toMetres(p)}));
            const predicted=parsed[1].map(p=>({...p,value:toMetres(p)}));
            renderChart(measured,predicted);
            const latest=measured[measured.length-1];
            const forecast=predicted.reduce((best,p)=>!best||Math.abs(p.time-now.getTime())<Math.abs(best.time-now.getTime())?p:best,null);
            tideLabel.textContent=latest?"Gemeten "+level(latest.value)+" · "+clock(latest.time)
                :forecast?"Astronomisch "+level(forecast.value)+" (geen actuele meting)"
                :"Getijgegevens niet beschikbaar";
            let peak=null;
            for(let i=1;i<predicted.length-1;i++) {
                const a=predicted[i-1],b=predicted[i],c=predicted[i+1];
                if(b.time>=now.getTime()&&b.value>=a.value&&b.value>=c.value
                    &&(b.value>a.value||b.value>c.value)){peak=b;break;}
            }
            highLabel.textContent=peak?"Volgend hoogwater rond "+clock(peak.time)
                :"Tijd volgend hoogwater niet beschikbaar";
            renderWind(parsed[2].at(-1)||null,parsed[3].at(-1)||null);
            const failures=settled.filter(x=>x.status==="rejected").length;
            const hasData=parsed.some(list=>list.length>0);
            status.textContent=hasData?"Bron: Rijkswaterstaat · "+clock(Date.now())
                +(failures?" · "+failures+" gegevensbron(nen) tijdelijk niet bereikbaar":"")
                : "RWS-relay (:8120) of meetgegevens niet beschikbaar";
            lastRequest=Date.now();
        }catch(_){
            tideLabel.textContent="Getijgegevens niet beschikbaar";
            highLabel.textContent="Tijd volgend hoogwater niet beschikbaar";
            renderChart([],[]);
            renderWind(null,null);
            status.textContent="RWS-relay (:8120) niet bereikbaar; kaart blijft werken";
        }finally{busy=false;refreshButton.disabled=false;}
    }
    function sync() {
        // Mirror the original block layer: refresh only while legend is open.
        if(outer.open && !document.hidden) {
            if(!lastRequest || Date.now()-lastRequest>=intervalMs)void refresh();
            if(interval===null)interval=window.setInterval(()=>void refresh(),intervalMs);
        }else if(interval!==null){
            window.clearInterval(interval);interval=null;
        }
    }
    refreshButton.addEventListener("click",()=>void refresh());
    outer.addEventListener("toggle",sync);
    document.addEventListener("visibilitychange",sync);
    window.setTimeout(sync,0);
})();
