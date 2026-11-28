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
  const radius = by("local-ai-radius"), missionPeriod = by("local-ai-mission-period");
  const viewNames = {station_health:"Station Health",maritime:"Maritime Intelligence",reception_performance:"Reception Performance",mission_analyst:"Mission Analyst",aviation:"Aviation Intelligence",station_memory:"Station Memory"};
  const defaultQuestions = {
    station_health:"Assess station health, explain any findings and recommend safe checks.",
    maritime:"Summarize the observed maritime traffic and ATIS activity. Explain limitations.",
    reception_performance:"Compare AIS and ADS-B reception with the preceding seven days. Explain changes, coverage and safe checks without claiming a cause.",
    mission_analyst:"Summarize mission results, compare satellites and receivers cautiously, and suggest improvements based on the available measurements.",
    aviation:"Summarize current aggregate aviation observations, altitude distribution and reception limits.",
    station_memory:"Summarize the selected technical notes and log classifications. Identify reported successful recoveries and unresolved issues without inventing causes."
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
  function comparisonBars(label, metric, unit) {
    const group = document.createElement("div"); group.className = "ai-compare-group";
    const title = document.createElement("strong"); title.textContent = label + " · " + signedPct(metric.change_pct);
    group.append(title);
    const max = Math.max(metric.current_mean ?? 0, metric.baseline_mean ?? 0, 0.000001);
    for (const [name,value,style] of [["Last 24h",metric.current_mean,"current"],["Prior 7d",metric.baseline_mean,"baseline"]]) {
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
    metric("Incidents / log entries",data.counts.incident ?? 0);
    metric("Hardware changes",data.counts.hardware ?? 0);
    metric("Configuration",data.counts.configuration ?? 0);
    metric("Notes",data.counts.note ?? 0);
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
  function renderObservation(data) {
    inspectMetrics.replaceChildren(); inspectData.textContent = "";
    if (!data) return;
    const lines = [];
    inspectStatus.textContent = "Observed " + data.observed_utc + " · " + (data.status || "Read-only snapshot");
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
    inspectData.textContent = lines.join("\n");
  }
  async function inspect(analyze = false) {
    if (view === "ask" || pending || !snapshot?.enabled || !snapshot?.installed || snapshot.busy) return;
    const kind = view;
    const body = {kind, radius_km: Number(radius.value), mission_period: missionPeriod.value, memory_query:memoryFilter, memory_page:memoryPage};
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
    inspectRefresh.disabled = inspectAnalyze.disabled = inspectQuestion.disabled = radius.disabled = missionPeriod.disabled = busy || !s?.enabled || !s?.installed;
    renderMemoryControls(busy || !s?.enabled || !s?.installed);
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
      showEvidence(data.evidence);
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
})();
