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
  const radius = by("local-ai-radius");
  const tabs = Array.from(page.querySelectorAll("[data-ai-view]"));
  let view = "ask", inspecting = false;
  const display = value => value == null ? "Unavailable" : String(value);
  const numberUnit = (value, unit) => value == null ? "Unavailable" : value + " " + unit;
  function metric(label, value, state = "unknown") {
    const tile = document.createElement("div");
    tile.className = "ai-metric"; tile.dataset.state = state;
    const name = document.createElement("span"), val = document.createElement("strong");
    name.textContent = label; val.textContent = display(value);
    tile.append(name, val); inspectMetrics.append(tile);
  }
  function renderObservation(data) {
    inspectMetrics.replaceChildren(); inspectData.textContent = "";
    if (!data) return;
    const lines = [];
    inspectStatus.textContent = "Observed " + data.observed_utc + " · " + (data.status || "Read-only snapshot");
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
    const body = {kind, radius_km: Number(radius.value)};
    if (analyze) body.question = inspectQuestion.value.trim() || (kind === "station_health" ? "Assess station health, explain any findings and recommend safe checks." : "Summarize the observed maritime traffic and ATIS activity. Explain limitations.");
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
    by("local-ai-radius-field").hidden = next !== "maritime";
    by("local-ai-inspect-title").textContent = next === "maritime" ? "Maritime Intelligence" : "Station Health";
    tabs.forEach(t => t.setAttribute("aria-pressed", String(t.dataset.aiView === next)));
    inspectQuestion.value = ""; inspectAnswer.textContent = ""; renderObservation(null);
    inspectStatus.textContent = "Read-only observations.";
    if (next !== "ask") inspect();
  }
  tabs.forEach(t => t.addEventListener("click", () => switchView(t.dataset.aiView)));
  inspectRefresh.addEventListener("click", () => inspect());
  inspectAnalyze.addEventListener("click", () => inspect(true));
  radius.addEventListener("change", () => inspect());
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
    inspectRefresh.disabled = inspectAnalyze.disabled = inspectQuestion.disabled = radius.disabled = busy || !s?.enabled || !s?.installed;
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
