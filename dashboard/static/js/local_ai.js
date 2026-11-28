(() => {
  "use strict";
  const by = id => document.getElementById(id);
  const panel = by("local-ai-panel");
  if (!panel) return;
  const status = by("local-ai-status"), badge = by("local-ai-badge");
  const install = by("local-ai-install"), toggle = by("local-ai-toggle");
  const remove = by("local-ai-remove"), send = by("local-ai-send");
  const question = by("local-ai-question"), answer = by("local-ai-answer");
  const page = by("tab-intelligence");
  const period = by("local-ai-period"), evidence = by("local-ai-evidence");
  const evidenceText = by("local-ai-evidence-text");
  function showEvidence(data) {
    evidence.hidden = !data;
    evidence.open = false;
    evidenceText.textContent = "";
    if (!data) return;
    if (data.kind === "application_knowledge") {
      evidence.querySelector("summary").textContent = "Application Knowledge · verified help";
      evidenceText.textContent = (data.entries || []).join("\n\n");
      return;
    }
    evidence.querySelector("summary").textContent = "Reception Analytics · verified source data";
    const display = v => v == null ? "Unavailable" : String(v);
    const lines = [
      data.source + " · " + data.period,
      data.window_start_utc + " → " + data.window_end_utc,
      "Station-wide; sampled simultaneous targets, not unique totals."
    ];
    if (data.samples != null) {
      lines.push("Samples: " + data.samples + " / " + data.expected_samples + " nominal · " + data.coverage_pct + "% coverage",
        "First: " + display(data.first_sample_utc) + " · Last: " + display(data.last_sample_utc));
    }
    if (data.latest_sample_stale) lines.push("Latest sample is older than 3 minutes; no live status inferred.");
    if (data.status !== "ok") lines.push(data.reason || data.status);
    else for (const [key, label] of [["ais", "AIS"], ["adsb", "ADS-B"]]) {
      const row = data[key];
      lines.push("", label + " · Active samples: " + display(row.active_samples) + " · Inactive: " + display(row.inactive_samples) + " · Unknown: " + display(row.unknown_activity_samples));
      for (const [field, name] of [["targets", "Targets"], ["rate", "Messages/sec"], ["range_nm", "Range (NM)"]]) {
        const metric = row[field];
        lines.push(name + ": mean " + display(metric.mean) + " · peak " + display(metric.peak) + " · valid samples " + metric.valid_samples);
      }
    }
    evidenceText.textContent = lines.join("\n");
  }
  const transfer = by("local-ai-transfer"), progress = by("local-ai-progress");
  const transferText = by("local-ai-transfer-text"), cancel = by("local-ai-cancel");
  const installError = by("local-ai-install-error");
  const mib = bytes => (bytes / 1048576).toFixed(1) + " MiB";
  const threads = by("local-ai-threads"), tokens = by("local-ai-tokens"), memory = by("local-ai-memory");
  const chatProgress = by("local-ai-chat-progress");
  const save = by("local-ai-save"), settingsResult = by("local-ai-settings-result");
  let snapshot = null, pending = false, timer = null, dirty = false, actionError = "", chatting = false, refreshing = false, epoch = 0;
  const visible = () => page.classList.contains("active");
  const inspectView = by("local-ai-inspect-view"), inspectStatus = by("local-ai-inspect-status");
  const inspectRefresh = by("local-ai-inspect-refresh"), inspectAnalyze = by("local-ai-inspect-analyze");
  const inspectQuestion = by("local-ai-inspect-question"), inspectAnswer = by("local-ai-inspect-answer");
  const inspectMetrics = by("local-ai-inspect-metrics"), inspectData = by("local-ai-inspect-data");
  const radius = by("local-ai-radius"), missionPeriod = by("local-ai-mission-period"), briefingDate = by("local-ai-briefing-date"), advisorHours = by("local-ai-advisor-hours");
  const viewNames = {station_health:"Station Health",maritime:"Maritime Intelligence",reception_performance:"Reception Performance",mission_analyst:"Mission Analyst",aviation:"Aviation Intelligence",station_memory:"Station Memory",anomaly_detection:"Anomaly Detection",daily_briefing:"Daily Briefing",mission_advisor:"Mission Advisor",rf_optimization:"RF Optimization"};
  const defaultQuestions = {
    station_health:"Assess station health, explain any findings and recommend safe checks.",
    maritime:"Summarize the observed maritime traffic and ATIS activity. Explain limitations.",
    reception_performance:"Compare AIS and ADS-B reception with the preceding seven days. Explain changes, coverage and safe checks without claiming a cause.",
    mission_analyst:"Summarize mission results, compare satellites and receivers cautiously, and suggest improvements based on the available measurements.",
    aviation:"Summarize current aggregate aviation observations, altitude distribution and reception limits.",
    station_memory:"Summarize the selected technical notes and log classifications. Identify reported successful recoveries and unresolved issues without inventing causes.",
    anomaly_detection:"Explain current anomaly alerts, recent transitions, and safe diagnostic checks. Distinguish suspected problems from proven faults.",
    daily_briefing:"Write a concise station briefing from these observations: AIS, ADS-B, ATIS, mission outcomes and retained technical alerts. Explain missing data and recommend any necessary checks.",
    mission_advisor:"Explain which upcoming passages have promising geometry, historical evidence and any conflicts or receiver concerns. Do not guarantee reception or recommend changing scheduler settings.",
    rf_optimization:"Evaluate the selected RF experiment, its sample coverage and before/after observations. Distinguish measured changes from causal proof. Suggest safe follow-up measurements."
  };
  const tabs = Array.from(page.querySelectorAll("[data-ai-view]"));
  let view = "ask", inspecting = false;
  const memoryTools = by("local-ai-memory-tools"), memoryQuery = by("local-ai-memory-query");
  const memorySearch = by("local-ai-memory-search"), memoryImport = by("local-ai-memory-import");
  const memoryAdd = by("local-ai-memory-add"), memoryPrev = by("local-ai-memory-prev"), memoryNext = by("local-ai-memory-next");
  const memoryKind = by("local-ai-memory-kind"), memoryTitle = by("local-ai-memory-title"), memoryDetails = by("local-ai-memory-details"), memoryOutcome = by("local-ai-memory-outcome");
  const memoryResult = by("local-ai-memory-result");
  let memoryPage = 1, memoryFilter = "", memoryMatched = 0;
  function renderMemoryControls(busy) {
    for (const el of [memoryQuery,memorySearch,memoryImport,memoryAdd,memoryKind,memoryTitle,memoryDetails,memoryOutcome]) el.disabled = busy;
    memoryPrev.disabled = busy || memoryPage <= 1;
    memoryNext.disabled = busy || memoryPage*10 >= memoryMatched;
    for (const el of inspectData.querySelectorAll("[data-memory-delete]")) el.disabled = busy;
    by("local-ai-memory-page").textContent = "Page " + memoryPage + " / " + Math.max(1,Math.ceil(memoryMatched/10));
  }
  const rfTools=by("local-ai-rf-tools"), rfSelect=by("local-ai-rf-select"), rfFinalize=by("local-ai-rf-finalize"), rfDelete=by("local-ai-rf-delete"), rfRecord=by("local-ai-rf-record"), rfResult=by("local-ai-rf-result");
  const rfService=by("local-ai-rf-service"), rfCategory=by("local-ai-rf-category"), rfPeriod=by("local-ai-rf-period"), rfTitle=by("local-ai-rf-title"), rfDetails=by("local-ai-rf-details");
  let rfId=0, rfCurrent=null;
  function renderRFControls(busy){
    for(const el of [rfSelect,rfRecord,rfService,rfCategory,rfPeriod,rfTitle,rfDetails]) el.disabled=busy;
    rfFinalize.disabled=busy||!rfCurrent||rfCurrent.saved||rfCurrent.status==="measuring";
    rfDelete.disabled=busy||!rfCurrent;
  }
  const display = value => value == null ? "Unavailable" : String(value);
  const numberUnit = (value, unit) => value == null ? "Unavailable" : value + " " + unit;
  function metric(label, value, state = "unknown") {
    const tile = document.createElement("div");
    tile.className = "ai-metric"; tile.dataset.state = state;
    const name = document.createElement("span"), val = document.createElement("strong");
    name.textContent = label; val.textContent = display(value);
    tile.append(name, val); inspectMetrics.append(tile);
  }
  const signedPct = value => value == null ? "Unavailable" : (value > 0 ? "+" : "") + value + "%";
  function detailTable(title, headers, rows) {
    const section = document.createElement("section");
    section.className = "ai-detail-table";
    const heading = document.createElement("h4"); heading.textContent = title;
    const scroll = document.createElement("div"); scroll.className = "ai-table-scroll";
    const table = document.createElement("table"), head = table.createTHead(), tr = head.insertRow();
    for (const label of headers) {
      const th = document.createElement("th"); th.scope = "col"; th.textContent = label; tr.append(th);
    }
    const body = table.createTBody();
    for (const row of rows) {
      const line = body.insertRow();
      for (const value of row) { const cell = line.insertCell(); cell.textContent = display(value); }
    }
    scroll.append(table); section.append(heading,scroll); inspectData.append(section);
  }
  function comparisonBars(label, metric, unit, currentLabel="Last 24h", baselineLabel="Prior 7d") {
    const group = document.createElement("div"); group.className = "ai-compare-group";
    const title = document.createElement("strong"); title.textContent = label + " · " + signedPct(metric.change_pct);
    group.append(title);
    const max = Math.max(metric.current_mean ?? 0, metric.baseline_mean ?? 0, 0.000001);
    for (const [name,value,style] of [[currentLabel,metric.current_mean,"current"],[baselineLabel,metric.baseline_mean,"baseline"]]) {
      const row = document.createElement("div"); row.className = "ai-compare-row";
      const text = document.createElement("span"); text.textContent = name;
      const track = document.createElement("div"); track.className = "ai-compare-track";
      const bar = document.createElement("div"); bar.className = "ai-compare-bar " + style;
      bar.style.width = (value == null ? 0 : Math.max(0,Math.min(100,100*value/max))) + "%";
      const number = document.createElement("span"); number.textContent = numberUnit(value,unit);
      track.append(bar); row.append(text,track,number); group.append(row);
    }
    inspectData.append(group);
  }
  function note(text) {
    const p = document.createElement("p"); p.className = "ai-detail-note"; p.textContent = text; inspectData.append(p);
  }
  function renderPerformance(data) {
    const labels = {targets:"Targets",rate:"Messages/sec",range_nm:"Range (NM)"};
    for (const [key,name] of [["ais","AIS"],["adsb","ADS-B"]]) {
      for (const [metricKey, label] of Object.entries(labels)) {
        const m = data.services[key].metrics[metricKey];
        metric(name + " · " + label, signedPct(m.change_pct),m.status === "above" ? "ok" : m.status === "below" ? "attention" : "unknown");
      }
      comparisonBars(name + " message rate",data.services[key].metrics.rate,"msg/s");
      const service = data.services[key];
      detailTable(name + " reception",["Metric","24h mean","7d mean","24h peak","7d peak","Change"],Object.entries(labels).map(([k,label])=>{
        const m=service.metrics[k];
        return [label,m.current_mean,m.baseline_mean,m.current_peak,m.baseline_peak,m.change_pct == null ? m.status.replaceAll("_"," ") : signedPct(m.change_pct)];
      }));
      note("Active samples: " + display(service.current_active_samples) + " / " + display(service.baseline_active_samples) + " · Inactive: " + display(service.current_inactive_samples) + " / " + display(service.baseline_inactive_samples));
      note("Valid samples (24h / prior 7d): " + Object.entries(labels).map(([k,l])=>l+" "+service.metrics[k].current_valid_samples+"/"+service.metrics[k].baseline_valid_samples).join(" · "));
    }
    note("Coverage: 24h " + numberUnit(data.current.coverage_pct,"%") + " · prior 7d " + numberUnit(data.baseline.coverage_pct,"%"));
    note("Current: " + data.current.window_start_utc + " → " + data.current.window_end_utc + " · Baseline: " + data.baseline.window_start_utc + " → " + data.baseline.window_end_utc);
    note(data.scope);
  }
  function renderMissions(data) {
    if (!data.summary) { note(data.reason || "Mission history unavailable."); return; }
    const m = data.summary;
    metric("Stored missions",m.missions);
    metric("Success",numberUnit(m.success_pct,"%"),m.success_pct === 100 ? "ok" : "unknown");
    metric("Images",m.images);
    metric("Best peak SNR",numberUnit(m.peak_snr_best_db,"dB"));
    metric("Total frames",m.frames);
    metric("Mean quality",numberUnit(m.quality_mean_pct,"%"));
    const rows = group=>group.groups.map(g=>[g.name,g.missions,numberUnit(g.success_pct,"%"),numberUnit(g.peak_snr_mean_db,"dB"),numberUnit(g.peak_snr_best_db,"dB"),g.snr_samples,g.images]);
    for (const [label,group] of [["By satellite",data.satellites],["By receiver",data.receivers]]) {
      detailTable(label,["Name","Missions","Success","Mean peak SNR","Best peak SNR","SNR samples","Images"],rows(group));
      if (group.omitted_groups) note(group.omitted_groups + " additional groups not displayed.");
    }
    detailTable("By maximum elevation",["Elevation","Missions","Success","Mean peak SNR","SNR samples"],data.elevation.map(g=>[g.name,g.missions,numberUnit(g.success_pct,"%"),numberUnit(g.peak_snr_mean_db,"dB"),g.snr_samples]));
    note("Results: " + Object.entries(m.results).map(([k,v])=>k+": "+v).join(" · ") + " · Unknown: " + m.unknown_result);
    note("Success: "+m.success+" / "+m.completed+" known completed · Cancelled: "+m.cancelled+" · Simulations excluded: "+data.excluded_simulations+" · Retained records: "+data.retained_records+" · Undated records: "+data.undated_records);
    note("Measurements available: SNR "+m.snr_samples+" · images "+m.image_samples+" · frames "+m.frame_samples+" · quality "+m.quality_samples+" · Mean duration "+numberUnit(m.duration_mean_s,"s"));
    note(data.scope);
  }
  function distribution(title, counts) {
    const block = document.createElement("section"); block.className = "ai-compare-group";
    const heading = document.createElement("strong"); heading.textContent = title; block.append(heading);
    const max = Math.max(1,...Object.values(counts));
    for (const [label,count] of Object.entries(counts)) {
      const row = document.createElement("div"); row.className = "ai-distribution-row";
      const name = document.createElement("span"); name.textContent = label;
      const track = document.createElement("div"); track.className = "ai-compare-track";
      const bar = document.createElement("div"); bar.className = "ai-compare-bar"; bar.style.width = (100*count/max)+"%";
      const n = document.createElement("span"); n.textContent = count;
      track.append(bar); row.append(name,track,n); block.append(row);
    }
    inspectData.append(block);
  }
  function renderAviation(data) {
    metric("Radius",numberUnit(data.radius_km,"km"));
    metric("Positioned aircraft",data.aircraft,data.status==="ok"?"ok":"unknown");
    metric("Rotorcraft",data.helicopters);
    metric("Ground aircraft",data.ground_aircraft);
    metric("Mean altitude",numberUnit(data.altitude_mean_ft,"ft"));
    metric("Max range",numberUnit(data.max_range_nm,"NM"));
    if (data.status!=="ok") { note(data.reason || "Aviation data unavailable."); return; }
    distribution("Altitude distribution · excluding reported ground",data.altitude_bands);
    distribution("Reported / inferred aircraft category",data.categories);
    note("Mean speed: "+numberUnit(data.speed_mean_knots,"kn")+" · altitude samples: "+data.altitude_samples+" · speed samples: "+data.speed_samples);
    note("Station message rate: "+numberUnit(data.message_rate_station,"msg/s")+" · excluded surface targets: "+data.surface_targets_excluded);
    note(data.scope);
  }
  function renderMemory(data) {
    memoryMatched=data.matched ?? 0;
    metric("Stored entries",data.total);
    metric("Incidents / log entries",data.total == null ? null : (data.counts.incident ?? 0));
    metric("Hardware changes",data.total == null ? null : (data.counts.hardware ?? 0));
    metric("Configuration",data.total == null ? null : (data.counts.configuration ?? 0));
    metric("Notes",data.total == null ? null : (data.counts.note ?? 0));
    metric("Search matches",data.matched);
    if (data.reason) note(data.reason);
    else if (!data.entries.length) note("No entries on this page. Add a technical note or import recent logs.");
    for (const entry of data.entries) {
      const card=document.createElement("article"); card.className="ai-memory-entry";
      const head=document.createElement("div"); head.className="ai-memory-entry-head";
      const title=document.createElement("strong"); title.textContent=entry.title;
      const del=document.createElement("button"); del.type="button"; del.className="control-button ai-danger"; del.textContent="Delete"; del.setAttribute("data-local-ai-control",""); del.dataset.memoryDelete=String(entry.id);
      del.addEventListener("click",()=>{if(confirm("Delete this station memory entry? Imported entries may reappear if the original log is imported again.")) memoryAction({action:"delete",id:entry.id});});
      head.append(title,del);
      const meta=document.createElement("div"); meta.className="ai-subtitle"; meta.textContent=entry.kind+" · "+entry.source+" · "+new Date(entry.created_utc).toLocaleString();
      const body=document.createElement("div"); body.textContent=entry.details;
      const outcome=document.createElement("div"); outcome.className="ai-memory-outcome"; outcome.textContent=entry.outcome ? "Outcome: "+entry.outcome : "";
      card.append(head,meta,body,outcome); inspectData.append(card);
    }
    note(data.scope+" AI sees at most the first six entries on this page, with shortened details/outcomes.");
  }
  async function memoryAction(body) {
    if(view!=="station_memory" || pending || !snapshot?.enabled || !snapshot?.installed || snapshot.busy) return;
    epoch++; pending=true; render(); memoryResult.textContent="Working...";
    let changed=false;
    try {
      const data=await api("memory",body);
      changed=true;
      if(body.action==="add"){
        memoryTitle.value=memoryDetails.value=memoryOutcome.value="";
        by("local-ai-memory-form").open=false;
        memoryFilter=memoryQuery.value=""; memoryPage=1;
        memoryResult.textContent="Note saved.";
      } else if(body.action==="import"){
        memoryPage=1; memoryFilter=memoryQuery.value="";
        memoryResult.textContent="Imported "+data.added+" of "+data.matched+" matching log entries. "+Object.entries(data.sources).map(([k,v])=>k+": "+v).join(" · ")+(data.truncated?" · Limited":"");
      } else { memoryPage=1; memoryResult.textContent="Entry deleted."; }
    } catch(err){memoryResult.textContent=err.message;}
    finally{epoch++; pending=false; render(); if(changed) await inspect(); else schedule();}
  }
  const anomalySettings=by("local-ai-anomaly-settings"), anomalyEnabled=by("local-ai-anomaly-enabled"), anomalyMqtt=by("local-ai-anomaly-mqtt"), anomalySave=by("local-ai-anomaly-save"), anomalyCount=by("local-ai-anomaly-count");
  let anomalyDirty=false;
  function renderAnomaly(data) {
    if(!anomalyDirty){anomalyEnabled.checked=data.enabled;anomalyMqtt.checked=data.mqtt;}
    metric("Monitoring",data.status,data.status==="monitoring"?"ok":"unknown");
    metric("Open alerts",data.active.length,data.active.length?"attention":"ok");
    metric("Pending checks",Object.values(data.checks).filter(c=>c.state==="bad"&&c.consecutive<3).length);
    metric("Unknown checks",Object.values(data.checks).filter(c=>c.state==="unknown").length);
    metric("Memory queue",data.memory_pending);
    metric("MQTT",data.mqtt?"Enabled":"Off");
    if(data.reason||data.error) note(data.reason||data.error);
    if(data.memory_error||data.memory_overflow) note("Memory: "+(data.memory_error||"Queue capacity exceeded; some transitions were not stored."));
    if(data.mqtt) note(data.mqtt_result||"No MQTT event sent.");
    if(data.status!=="monitoring") note("Monitoring paused or not yet sampled. Open alerts are retained; no recovery inferred.");
    const active=new Set(data.active.map(a=>a.rule));
    detailTable("Current observations",["Check","Status","Streak","Observation"],Object.entries(data.checks).map(([key,c])=>[c.title,active.has(key)?"OPEN · "+c.state:c.state,c.consecutive,c.detail]));
    detailTable("Recent transitions",["Time","Event","Check","Observation"],data.history.map(e=>[new Date(e.timestamp).toLocaleString(),e.transition,e.title,e.detail]));
    note(data.scope||"");
  }
  async function updateAnomalyBadge(){
    if(!anomalyCount)return; // Embedded Intelligence has no desktop navigation badge.
    try{
      const data=await api("anomaly-status");
      anomalyCount.hidden=!data.enabled||!data.active_count;
      anomalyCount.textContent=String(data.active_count||"");
      anomalyCount.title=data.active_count+" open technical alerts";
    }catch(_){anomalyCount.hidden=true;}
  }
  anomalyEnabled.addEventListener("change",()=>{anomalyDirty=true;});
  anomalyMqtt.addEventListener("change",()=>{anomalyDirty=true;});
  anomalySave.addEventListener("click",async()=>{
    if(pending||view!=="anomaly_detection"||!snapshot?.enabled||!snapshot?.installed)return;
    epoch++;pending=true;render();
    try{
      const data=await api("anomaly-settings",{enabled:anomalyEnabled.checked,mqtt:anomalyMqtt.checked});
      anomalyDirty=false;inspectAnswer.textContent="";renderObservation(data.evidence);
      await updateAnomalyBadge();
    }catch(err){inspectStatus.textContent=err.message;}
    finally{epoch++;pending=false;render();schedule();}
  });
  function renderBriefing(data) {
    const selection=briefingDate.value;
    briefingDate.replaceChildren(new Option("Last 24 hours","rolling"));
    for(const day of data.available_dates||[]) briefingDate.append(new Option(day+" (UTC archive)",day));
    if(selection!=="rolling" && !Array.from(briefingDate.options).some(o=>o.value===selection)) briefingDate.append(new Option(selection+" (unavailable)",selection));
    briefingDate.value=selection;
    if(!data.reception){note(data.reason||"Briefing unavailable.");return;}
    const rx=data.reception, m=data.missions.summary, a=data.atis, alerts=data.alerts;
    metric("AIS peak targets",rx.ais?.targets?.peak);
    metric("ADS-B peak targets",rx.adsb?.targets?.peak);
    metric("ATIS decoded",a.decoded);
    metric("Stored missions",m?.missions);
    metric("Images",m?.images);
    metric("Visible alert openings",alerts.opened,alerts.opened>0?"attention":"unknown");
    note((data.mode==="archive"?"Archived UTC day "+data.date:"Rolling 24 hours")+" · "+data.window_start_utc+" → "+data.window_end_utc);
    detailTable("Reception overview",["Metric","AIS","ADS-B"],[
      ["Mean targets",rx.ais?.targets?.mean,rx.adsb?.targets?.mean],
      ["Peak targets",rx.ais?.targets?.peak,rx.adsb?.targets?.peak],
      ["Mean msg/s",rx.ais?.rate?.mean,rx.adsb?.rate?.mean],
      ["Peak msg/s",rx.ais?.rate?.peak,rx.adsb?.rate?.peak],
      ["Max range (NM)",rx.ais?.range_nm?.peak,rx.adsb?.range_nm?.peak],
      ["Active samples",rx.ais?.active_samples,rx.adsb?.active_samples],
      ["Valid rate samples",rx.ais?.rate?.valid_samples,rx.adsb?.rate?.valid_samples]
    ]);
    note("Reception: "+rx.status+" · "+display(rx.samples)+"/"+display(rx.expected_samples)+" samples · coverage "+numberUnit(rx.coverage_pct,"%"));
    detailTable("Missions and ATIS",["Metric","Value"],[
      ["Mission history",data.missions.status],["Successful",m?.success],["Known completed",m?.completed],
      ["Success rate",numberUnit(m?.success_pct,"%")],["Cancelled",m?.cancelled],["Unknown outcome",m?.unknown_result],
      ["Best peak SNR",numberUnit(m?.peak_snr_best_db,"dB")],["Images / measured missions",m?display(m.images)+" / "+m.image_samples:null],
      ["ATIS source",a.status],["Candidates",a.candidates],["Decoded",a.decoded],["AIS matched",a.ais_matched],["Photos",a.photo_found]
    ]);
    detailTable("Retained technical alert transitions",["Rule","Opened","Cleared"],Object.entries(alerts.rules||{}).map(([k,v])=>[k.replaceAll("_"," "),v.opened,v.cleared]));
    note("Visible openings: "+display(alerts.opened)+" · clears: "+display(alerts.cleared)+" · "+alerts.scope);
    note(data.scope);
  }
  function renderAdvisor(data) {
    metric("Planning horizon",numberUnit(data.hours,"h"));
    metric("Candidates",data.candidate_count);
    metric("High elevation",data.high_elevation_count);
    metric("Needs review",data.review_count,data.review_count>0?"attention":"unknown");
    metric("Best geometry",numberUnit(data.best_geometry?.elevation,"°"));
    metric("Scheduler",data.scheduler_mode);
    if(!data.passes){note(data.reason||"Mission advice unavailable.");return;}
    if(data.best_geometry){
      const p=data.best_geometry;
      note("Highest unflagged elevation: "+p.name+" · "+new Date(p.start_utc).toLocaleString()+" · "+p.elevation+"° · "+display(p.receiver)+" (geometry only)");
    }
    if(data.scheduler_mode!=="AUTO") note("Scheduler is not in AUTO; no automatic execution implied.");
    detailTable("Upcoming predicted passes · local time",["Satellite / type","Start","Peak","Duration","Receiver","Assessment"],data.passes.map(p=>[
      p.name+" / "+p.mission_type,new Date(p.start_utc).toLocaleString(),numberUnit(p.elevation,"°"),numberUnit(Math.round(p.duration_seconds/60),"min"),p.receiver,p.flags.length?p.flags.join("; "):p.assessment
    ]));
    detailTable("Matched historical observations · last 90 days",["Pass","Completed","Success","Mean peak SNR","SNR samples","Shared roles"],data.passes.map(p=>[
      p.name+" · "+p.elevation+"°",p.history.completed,p.history.status==="observed"?numberUnit(p.history.success_pct,"%"):"Insufficient",numberUnit(p.history.mean_peak_snr_db,"dB"),p.history.snr_samples,p.shared_roles.join(", ")||"None observed"
    ]));
    if(data.omitted_passes) note(data.omitted_passes+" additional candidates omitted from the table.");
    note("History: "+data.history_status+" · "+display(data.history_completed)+" retained completed missions before matching.");
    note("TLE: "+Object.entries(data.tle||{}).map(([k,v])=>k+" "+(!v.valid?"invalid":v.stale?"stale":"current")+" ("+numberUnit(v.age_hours,"h")+")").join(" · "));
    note(data.scope);
    note("AI sees the first six displayed passes and best unflagged geometry only. No mission is started or altered.");
  }
  function renderRF(data) {
    rfCurrent=data.experiment;
    rfSelect.replaceChildren(new Option("Latest experiment","0"));
    for(const e of data.experiments||[]) rfSelect.append(new Option(e.service.toUpperCase()+" · "+e.title+" · "+new Date(e.changed_utc).toLocaleDateString()+(e.saved?" (saved)":""),String(e.id)));
    rfId=rfCurrent?.id||0; rfSelect.value=String(rfId);
    if(!rfCurrent){metric("Experiments",data.experiments?.length);note(data.reason||"No RF experiment selected. Record a physical change to begin.");return;}
    const e=rfCurrent;
    metric("Reception",e.service.toUpperCase());
    metric("Window per side",e.period);
    metric("Experiment",e.saved?"Saved":e.status==="measuring"?"Measuring":e.status==="ready"?"Ready":"Insufficient",e.status==="ready"?"ok":"unknown");
    metric("Targets",signedPct(e.metrics.targets?.change_pct));
    metric("Message rate",signedPct(e.metrics.rate?.change_pct));
    metric("Mean sampled range",signedPct(e.metrics.range_nm?.change_pct));
    note(e.title+" · "+e.category+" · recorded "+new Date(e.changed_utc).toLocaleString());
    if(e.details)note(e.details);
    if(e.status==="measuring"){
      note("After window ends "+new Date(e.after_end_utc).toLocaleString()+" · "+Math.ceil(e.remaining_seconds/3600)+" hours remaining (rounded up). No partial comparison.");
      detailTable("Frozen baseline",["Metric","Mean","Peak","Valid samples"],[["Targets","targets"],["Messages/sec","rate"],["Range (NM)","range_nm"]].map(([label,k])=>{const m=e.before[e.service]?.[k];return [label,m?.mean,m?.peak,m?.valid_samples];}));
    }else{
      const metrics=[["Targets","targets",""],["Message rate","rate","msg/s"],["Range","range_nm","NM"]];
      for(const [label,k,unit] of metrics)if(e.metrics[k])comparisonBars(label,e.metrics[k],unit,"After","Before");
      detailTable("Before / after",["Metric","Before mean","After mean","Before peak","After peak","Change","Status"],metrics.map(([label,k])=>{const m=e.metrics[k];return [label,m.baseline_mean,m.current_mean,m.baseline_peak,m.current_peak,signedPct(m.change_pct),m.status.replaceAll("_"," ")];}));
      if(e.intervening_changes)note("Comparison suppressed: "+e.intervening_changes+" other recorded change(s) for this service in the measurement interval.");
    }
    detailTable("Measurement coverage",["Window","Samples","Active","Coverage"],[["Before",e.before],["After",e.after]].map(([label,w])=>[label,w?display(w.samples)+"/"+display(w.expected_samples):null,w?.[e.service]?.active_samples,numberUnit(w?.coverage_pct,"%")]));
    note("Before: "+e.before.window_start_utc+" → "+e.before.window_end_utc+" · After: "+e.after_start_utc+" → "+e.after_end_utc+" (UTC)");
    note(e.saved?"Result frozen "+new Date(e.saved_utc).toLocaleString():"Save result after the measurement window to preserve it and update the linked Station Memory note.");
    note(data.scope);
  }
  async function rfAction(body){
    if(view!=="rf_optimization"||pending||!snapshot?.enabled||!snapshot?.installed||snapshot.busy)return;
    epoch++;pending=true;render();rfResult.textContent="Working...";
    let changed=false;
    try{
      const data=await api("rf-experiment",body);changed=true;
      if(body.action==="record"){rfId=data.id;rfTitle.value=rfDetails.value="";by("local-ai-rf-form").open=false;rfResult.textContent="Change recorded in Station Memory. Measurement scheduled by time window.";}
      else if(body.action==="finalize"){rfResult.textContent="Result saved.";}
      else{rfId=0;rfResult.textContent="Experiment deleted. Station Memory note retained.";}
    }catch(err){rfResult.textContent=err.message;}
    finally{epoch++;pending=false;render();if(changed)await inspect();else schedule();}
  }
  function renderObservation(data) {
    inspectMetrics.replaceChildren(); inspectData.textContent = "";
    rfCurrent=null;
    if (!data) return;
    const lines = [];
    inspectStatus.textContent = "Observed " + data.observed_utc + " · " + (data.status || "Read-only snapshot");
    if (data.kind === "rf_optimization") { renderRF(data); return; }
    if (data.kind === "mission_advisor") { renderAdvisor(data); return; }
    if (data.kind === "daily_briefing") { renderBriefing(data); return; }
    if (data.kind === "anomaly_detection") { renderAnomaly(data); return; }
    if (data.kind === "aviation") { renderAviation(data); return; }
    if (data.kind === "station_memory") { renderMemory(data); return; }
    if (data.kind === "reception_performance") { renderPerformance(data); return; }
    if (data.kind === "mission_analyst") { renderMissions(data); return; }
    if (data.kind === "station_health") {
      for (const [name, service] of Object.entries(data.services)) {
        metric(name, service.state, service.status);
        lines.push(name + ": " + service.state + " · restart count " + display(service.restart_count),
          "Decoder: " + service.reception.status + " · " + (service.reception.scope || "No active decoder observation"));
      }
      const recovery = data.recovery_history;
      if (recovery) {
        const day = recovery.windows?.["24h"];
        metric("Recovery history", recovery.status, recovery.status === "observed" ? "ok" : "unknown");
        if (day) {
          metric("Auto recoveries · 24h", day.automatic, day.automatic ? "attention" : "ok");
          metric("Runtime verified · 24h", day.verified + "/" + day.automatic, day.failed || day.unconfirmed ? "attention" : "ok");
        }
        if (recovery.status !== "observed") lines.push("Recovery history is unavailable or stale; do not infer a fault-free station.");
        if (day?.automatic) lines.push("Historical receiver incidents detected, even if services are currently running.");
        if (recovery.memory_pending) lines.push("Station Memory synchronization pending: " + recovery.memory_pending);
      }
      metric("USB identity", data.usb.status, data.usb.status);
      metric("History", data.database.status, data.database.status === "ok" && !data.database.latest_sample_stale ? "ok" : "attention");
      metric("Available RAM", numberUnit(data.resources.available_ram_gib, "GiB"));
      metric("CPU temperature", numberUnit(data.resources.cpu_temperature_c, "°C"));
      lines.push("", "USB devices (kernel identity, not transfer test)");
      for (const row of data.usb.receivers) lines.push(row.receiver + " · " + row.presence + " · " + display(row.port) + " · power " + display(row.power_control) + " · runtime " + display(row.runtime_status));
      lines.push("", "Disk free: " + numberUnit(data.resources.disk_free_gib, "GiB") + " · load/CPU: " + display(data.resources.load_1m_per_cpu),
        "Reception database: " + display(data.database.samples) + " samples · last sample age " + numberUnit(data.database.latest_sample_age_seconds, "s"),
        "", "Recent visible log entries (last hour)");
      for (const [name, events] of Object.entries(data.events_last_hour)) {
        lines.push(name + ": " + events.status + (events.truncated ? " (bounded)" : ""));
        for (const [key, count] of Object.entries(events.counts || {})) if (count) lines.push("  " + key.replaceAll("_", " ") + ": " + count);
      }
      lines.push("", "Findings:", ...(data.findings.length ? data.findings : ["No advisory threshold triggered in available observations."]), "", data.scope);
    } else {
      const ais = data.ais, atis = data.atis;
      metric("Radius", data.radius_km + " km");
      metric("Validated targets", ais.validated_targets, ais.status === "ok" ? "ok" : "unknown");
      metric("Moving", ais.moving);
      metric("Stationary / slow", ais.stationary_or_slow);
      metric("ATIS decoded · 24h", atis.decoded);
      metric("ATIS AIS matched · 24h", atis.ais_matched);
      lines.push("AIS: " + ais.status, ais.reason || data.scope);
      if (ais.status === "ok") {
        lines.push("Freshness: ≤ " + ais.freshness_seconds + " s · speed unknown: " + ais.speed_unknown, "", "By vessel profile:");
        for (const [profile, count] of Object.entries(ais.by_profile)) lines.push(profile.replaceAll("_", " ") + ": " + count);
        lines.push("", "Nearest ordinary vessel examples" + (ais.examples_limited ? " (limited)" : "") + ":");
        for (const row of ais.nearest_examples) lines.push(row.name + " · " + row.profile + " · " + row.distance_km + " km · " + numberUnit(row.speed_knots, "kn"));
      }
      lines.push("", "ATIS history (station-wide): " + atis.status,
        "Candidates: " + display(atis.candidates) + " · decoded: " + display(atis.decoded) + " · photos: " + display(atis.photo_found));
    }
    if (data.kind === "station_health" && data.recovery_history) {
      const recovery = data.recovery_history;
      if (Object.keys(recovery.windows || {}).length) {
        detailTable("Recovery history", ["Period","Automatic","Verified","Failed / attention","Unconfirmed","Manual"], Object.entries(recovery.windows).map(([period,row])=>[period,row.automatic,row.verified,row.failed,row.unconfirmed,row.manual]));
        detailTable("Recent receiver incidents", ["Time (UTC)","Receiver","Service","Outcome","Attempts","Recovery time","Nearby context"], recovery.recent.map(row=>[row.time_utc,row.receiver,row.service || "—",row.outcome.replaceAll("_"," "),row.attempts || "—",row.seconds == null ? "—" : row.seconds + " s",row.context.join(" · ") || "—"]));
      }
      note(recovery.scope);
      note("Last history scan: " + display(recovery.last_scan_utc) + (recovery.bounded ? " · log tail bounded" : ""));
      note("Optional technical MQTT alerts use the existing Anomaly Detection settings.");
      const pre=document.createElement("div");pre.style.whiteSpace="pre-wrap";pre.textContent=lines.join("\n");inspectData.append(pre);
    } else inspectData.textContent = lines.join("\n");
  }
  let lastHealthRead = 0;
  async function inspect(analyze = false) {
    if (view === "ask" || pending || !snapshot?.enabled || !snapshot?.installed || snapshot.busy) return;
    const kind = view;
    if (kind === "station_health") lastHealthRead = Date.now();
    const body = {kind, radius_km: Number(radius.value), mission_period: missionPeriod.value, memory_query:memoryFilter, memory_page:memoryPage, briefing_date:briefingDate.value, advisor_hours:Number(advisorHours.value), rf_id:rfId};
    if (analyze) body.question = inspectQuestion.value.trim() || defaultQuestions[kind];
    epoch++; pending = true; inspecting = true; chatting = analyze; render(); schedule();
    inspectStatus.textContent = analyze ? "Collecting observations and analyzing..." : "Collecting observations...";
    inspectAnswer.textContent = "";
    renderObservation(null);
    try {
      const data = await api("inspect", body);
      renderObservation(data.evidence);
      inspectAnswer.textContent = data.answer || "";
    } catch (err) {
      renderObservation(err.evidence);
      inspectStatus.textContent = err.message;
    } finally {
      epoch++; pending = false; inspecting = false; chatting = false; clearTimeout(timer); render(); await refresh();
    }
  }
  function switchView(next) {
    if (pending || next === view) return;
    view = next;
    by("local-ai-ask-view").hidden = next !== "ask";
    inspectView.hidden = next === "ask";
    by("local-ai-radius-field").hidden = next !== "maritime" && next !== "aviation";
    const radius200=by("local-ai-radius-200"); radius200.hidden=radius200.disabled=next!=="aviation";
    if(next==="maritime" && radius.value==="200") radius.value="100";
    memoryTools.hidden=next!=="station_memory";
    rfTools.hidden=next!=="rf_optimization";
    rfCurrent=null;
    anomalySettings.hidden=next!=="anomaly_detection";
    by("local-ai-briefing-date-field").hidden=next!=="daily_briefing";
    by("local-ai-advisor-hours-field").hidden=next!=="mission_advisor";
    anomalyDirty=false;
    by("local-ai-mission-period-field").hidden = next !== "mission_analyst";
    by("local-ai-inspect-title").textContent = viewNames[next] || "Station Health";
    tabs.forEach(t => t.setAttribute("aria-pressed", String(t.dataset.aiView === next)));
    inspectQuestion.value = ""; inspectAnswer.textContent = ""; renderObservation(null);
    inspectStatus.textContent = "Read-only observations.";
    if (next !== "ask") inspect();
  }
  tabs.forEach(t => t.addEventListener("click", () => switchView(t.dataset.aiView)));
  inspectRefresh.addEventListener("click", () => inspect());
  inspectAnalyze.addEventListener("click", () => inspect(true));
  radius.addEventListener("change", () => inspect());
  missionPeriod.addEventListener("change", () => inspect());
  briefingDate.addEventListener("change", () => inspect());
  advisorHours.addEventListener("change", () => inspect());
  rfSelect.addEventListener("change",()=>{rfId=Number(rfSelect.value);rfCurrent=null;inspect();});
  rfRecord.addEventListener("click",()=>{if(confirm("Record the completed physical RF change now? This does not change receiver settings."))rfAction({action:"record",service:rfService.value,category:rfCategory.value,period:rfPeriod.value,title:rfTitle.value,details:rfDetails.value});});
  rfFinalize.addEventListener("click",()=>{if(rfCurrent&&confirm("Save this result permanently, including any insufficient data?"))rfAction({action:"finalize",id:rfCurrent.id});});
  rfDelete.addEventListener("click",()=>{if(rfCurrent&&confirm("Delete this experiment? The linked Station Memory note is retained."))rfAction({action:"delete",id:rfCurrent.id});});
  memorySearch.addEventListener("click",()=>{memoryFilter=memoryQuery.value.trim();memoryPage=1;inspect();});
  memoryQuery.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();memorySearch.click();}});
  memoryPrev.addEventListener("click",()=>{if(memoryPage>1){memoryPage--;inspect();}});
  memoryNext.addEventListener("click",()=>{if(memoryPage*10<memoryMatched){memoryPage++;inspect();}});
  memoryImport.addEventListener("click",()=>{if(confirm("Import classified receiver errors and recovery messages from the visible recent logs? Raw log content is not saved.")) memoryAction({action:"import"});});
  memoryAdd.addEventListener("click",()=>memoryAction({action:"add",entry_kind:memoryKind.value,title:memoryTitle.value,details:memoryDetails.value,outcome:memoryOutcome.value}));
  async function api(path, body) {
    const res = await fetch("/api/local-ai/" + path, body === undefined
      ? {cache: "no-store"} : {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body)});
    const data = await res.json();
    if (!res.ok) {
      const error = new Error(data.error || "Local AI request failed.");
      error.evidence = data.evidence;
      throw error;
    }
    return data;
  }
  function render() {
    const s = snapshot;
    const busy = pending || !s || s.busy;
    install.hidden = !s || s.installed;
    install.style.display = install.hidden ? "none" : "";
    install.disabled = busy || !!s?.installed;
    toggle.disabled = busy || !s?.installed;
    remove.disabled = busy || !s || (!s.installed && !s.has_assets);
    question.disabled = send.disabled = period.disabled = busy || !s?.enabled || !s?.installed;
    inspectRefresh.disabled = inspectAnalyze.disabled = inspectQuestion.disabled = radius.disabled = missionPeriod.disabled = briefingDate.disabled = advisorHours.disabled = busy || !s?.enabled || !s?.installed;
    renderMemoryControls(busy || !s?.enabled || !s?.installed);
    renderRFControls(busy || !s?.enabled || !s?.installed);
    anomalyEnabled.disabled=anomalyMqtt.disabled=anomalySave.disabled=busy || !s?.enabled || !s?.installed;
    tabs.forEach(t => { t.disabled = pending; });
    if (inspecting && chatting && s?.progress) inspectStatus.textContent = s.progress;
    toggle.textContent = s?.enabled ? "Disable Local AI" : "Enable Local AI";
    threads.disabled = tokens.disabled = memory.disabled = save.disabled = busy || !s?.installed;
    chatProgress.textContent = chatting ? (s?.progress || "Loading model...") : "";
    transfer.hidden = !s?.installing;
    cancel.disabled = pending || !s?.installing || s.cancelling ||
      !["connecting", "downloading"].includes(s.download?.stage);
    if (s?.installing) {
      const d = s.download;
      if (d?.total_bytes) {
        progress.value = Math.min(100, 100 * d.received_bytes / d.total_bytes);
      } else {
        progress.removeAttribute("value");
      }
      const info = d ? [
        d.file,
        mib(d.received_bytes) + (d.total_bytes ? " / " + mib(d.total_bytes) + " (" + Math.floor(Math.min(100, 100*d.received_bytes/d.total_bytes)) + "%)" : ""),
        d.stage === "downloading" ? mib(d.bytes_per_second) + "/s average" : d.stage,
        d.seconds_since_data > 10 ? "No new data for " + Math.floor(d.seconds_since_data) + "s" : ""
      ].filter(Boolean).join(" · ") : s.progress;
      transferText.textContent = s.cancelling ? "Cancelling download..." : info;
    }
    if (!s) return;
    for (const option of threads.options) option.disabled = Number(option.value) > s.max_threads;
    if (!dirty && s.settings) {
      threads.value = String(s.settings.threads);
      tokens.value = String(s.settings.max_tokens);
      memory.value = String(s.settings.address_space_gib ?? 7);
    }
    badge.textContent = s.busy ? "BUSY" : s.installed ? (s.enabled ? "ENABLED" : "DISABLED") : "NOT INSTALLED";
    badge.dataset.state = s.busy ? "busy" : s.installed && s.enabled ? "enabled" : "disabled";
    status.textContent = [s.progress || (s.installed ? "Model and engine installed." : "AI is not installed."),
      s.ram_gib + " GiB RAM · " + s.available_gib + " GiB available · " + s.architecture,
      s.error || ""].filter(Boolean).join(" · ");
    installError.textContent = actionError || s.error || "";
  }
  function schedule() {
    clearTimeout(timer);
    if (visible() && (!pending || chatting)) timer = setTimeout(refresh, chatting ? 800 : snapshot?.busy || !snapshot ? 2000 : 5000);
  }
  async function refresh() {
    if (!visible() || (pending && !chatting) || refreshing) return;
    refreshing = true;
    const requestEpoch = epoch;
    try {
      const next = await api("status");
      if (requestEpoch === epoch) { snapshot = next; render(); }
    } catch (err) {
      if (requestEpoch === epoch) { status.textContent = err.message; }
    } finally { refreshing = false; schedule(); }
    if (visible() && view === "station_health" && !pending && !snapshot?.busy &&
        !inspectAnswer.textContent && Date.now() - lastHealthRead >= 60000) {
      void inspect();
    }
  }
  async function act(action) {
    if (pending) return;
    epoch++; pending = true; render();
    actionError = "";
    try { snapshot = await api("action", {action}); dirty = false; }
    catch (err) { actionError = err.message; }
    finally { pending = false; render(); schedule(); }
  }
  install.addEventListener("click", () => {
    if (confirm("Download and verify Local AI and Qwen3-4B? Approximately 2.5 GB of model data.")) act("install");
  });
  cancel.addEventListener("click", () => act("cancel_install"));
  toggle.addEventListener("click", () => act(snapshot?.enabled ? "disable" : "enable"));
  remove.addEventListener("click", () => {
    if (confirm("Remove the local AI model and engine? Receiver configuration is not affected.")) act("remove");
  });
  send.addEventListener("click", async () => {
    const q = question.value.trim();
    if (!q || pending || send.disabled) return;
    epoch++; pending = true; chatting = true; answer.textContent = ""; showEvidence(null); render(); schedule();
    try {
      const data = await api("chat", {question: q, reception_period: period.value});
      answer.textContent = data.answer;
      answer.scrollTop = 0;
      showEvidence(data.evidence || (data.source ? {kind:"application_knowledge", entries:[data.source + " · direct answer (no model inference)"]} : null));
    }
    catch (err) { answer.textContent = err.message; showEvidence(err.evidence); }
    finally { epoch++; pending = false; chatting = false; clearTimeout(timer); render(); await refresh(); }
  });
  threads.addEventListener("change", () => { dirty = true; });
  tokens.addEventListener("change", () => { dirty = true; });
  memory.addEventListener("change", () => { dirty = true; });
  save.addEventListener("click", async () => {
    if (pending) return;
    epoch++; pending = true; render();
    try {
      const data = await api("settings", {threads: Number(threads.value), max_tokens: Number(tokens.value), address_space_gib: Number(memory.value)});
      snapshot.settings = data.settings;
      dirty = false;
      settingsResult.textContent = "AI settings saved.";
    } catch (err) { settingsResult.textContent = err.message; }
    finally { pending = false; render(); schedule(); }
  });
  window.addEventListener("sdrcc:tab-changed", event => {
    if (event.detail?.tab === "intelligence") refresh();
    else clearTimeout(timer);
  });
  render();
  if (visible()) refresh();
  updateAnomalyBadge();
  setInterval(()=>{if(!document.hidden)updateAnomalyBadge();},30000);
})();
