(() => {
    const state = {busy: false, timer: null};
    const byId = (id) => document.getElementById(id);
    const escapeHtml = (value) => String(value ?? "-")
        .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

    function setMessage(message, isError = false) {
        const node = byId("mission-planner-message");
        if (!node) return;
        node.textContent = message;
        node.classList.toggle("error-text", isError);
    }

    function formatDateTime(value) {
        if (!value) return "-";
        const [date = "", time = ""] = String(value).split(" ");
        return `${date} ${time.slice(0, 5)}`.trim();
    }

    const qualityLabels = {
        'KORT': 'SHORT', 'MATIG': 'FAIR', 'REDELIJK': 'FAIR', 'GOED': 'GOOD',
        'ZEER GOED': 'VERY GOOD', 'UITSTEKEND': 'EXCELLENT'
    };

    function normalizeReceiverLabel(value) {
        const raw = String(value ?? "-").trim();
        const normalized = raw.toLowerCase();
        if (normalized === "sdr1") return "SDR1";
        if (normalized === "sdr2") return "SDR2";
        if (normalized === "auto") return "AUTO";
        return raw || "-";
    }

    function eligibility(item) {
        if (item.skipped) return {label: "SKIPPED", reason: "Manually skipped by the operator.", cls: "skipped"};
        if ((item.conflict_with || []).length) return {label: "CONFLICT", reason: `Receiver conflict with ${(item.conflict_with || []).join(", ")}.`, cls: "conflict"};
        if (item.mission_type === "VOICE" && item.automation_enabled === false) {
            return {label: "SELECTABLE", reason: "Eligible for an operator-planned Voice recording.", cls: "planned"};
        }
        const status = String(item.status || "QUEUED").toUpperCase();
        if (["TARGET", "NEXT"].includes(status)) return {label: "TARGET", reason: "Selected as the next automated mission.", cls: "target"};
        if (["ACTIVE", "IN PROGRESS", "RECORDING"].includes(status)) return {label: "ACTIVE", reason: "Mission is currently active.", cls: "active"};
        return {label: "ELIGIBLE", reason: "Pass meets the current planning rules.", cls: "eligible"};
    }

    function render(payload) {
        const queue = Array.isArray(payload.queue) ? payload.queue : [];
        const minimumElevation = Number(payload.minimum_elevation ?? 40);
        byId("mission-planner-minimum-elevation").value = String(minimumElevation);
        const weatherCount = queue.filter((item) => String(item.mission_type || "WEATHER").toUpperCase() !== "VOICE").length;
        const voiceCount = queue.filter((item) => String(item.mission_type || "").toUpperCase() === "VOICE").length;
        byId("mission-planner-weather-count").textContent = String(weatherCount);
        byId("mission-planner-voice-count").textContent = String(voiceCount);
        byId("mission-planner-pass-count").textContent = String(queue.length);
        byId("mission-planner-window").textContent = `${payload.hours_ahead || 48} hours`;

        const body = byId("mission-planner-table-body");
        if (!body) return;
        if (!queue.length) {
            body.innerHTML = '<tr><td colspan="9" class="mission-planner-empty">No eligible missions found in the planning window.</td></tr>';
            return;
        }
        body.innerHTML = queue.map((item) => {
            const result = eligibility(item);
            const missionType = String(item.mission_type || "WEATHER").toUpperCase();
            const rawReceiver = item.active_receiver || item.reserved_receiver || item.configured_receiver || item.receiver || "-";
            const receiver = missionType === "VOICE" && ["-", "NOT ASSIGNED", "AUTO"].includes(String(rawReceiver).toUpperCase())
                ? "AUTO" : normalizeReceiverLabel(rawReceiver);
            const elevation = Number(item.max_elevation);
            const frequency = Number(item.frequency_mhz);
            const rawQuality = String(item.quality?.label || "-").toUpperCase();
            const quality = qualityLabels[rawQuality] || rawQuality;
            return `<tr class="mission-planner-row is-${escapeHtml(result.cls)}">
                <td><span class="mission-type-badge is-${escapeHtml(missionType.toLowerCase())}">${escapeHtml(missionType)}</span></td>
                <td><strong>${escapeHtml(item.name || "Unknown satellite")}</strong><span>${escapeHtml(item.mode || item.pipeline || "-")}</span></td>
                <td>${escapeHtml(formatDateTime(item.start))}</td>
                <td>${Number.isFinite(elevation) ? `${elevation.toFixed(1)}°` : "-"}</td>
                <td>${Number.isFinite(frequency) ? `${frequency.toFixed(3)} MHz` : "-"}</td>
                <td>${escapeHtml(receiver)}</td><td>${escapeHtml(quality)}</td>
                <td><span class="mission-planner-state is-${escapeHtml(result.cls)}">${escapeHtml(result.label)}</span></td>
                <td>${escapeHtml(result.reason)}</td></tr>`;
        }).join("");
    }

    async function loadPlanner() {
        try {
            const response = await fetch("/api/mission-queue?limit=50&hours=48", {cache: "no-store"});
            const payload = await response.json();
            if (!response.ok || payload.ok === false) throw new Error(payload.error || "Mission Planner is unavailable.");
            render(payload);
            setMessage(`Updated ${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"})}.`);
        } catch (error) { setMessage(`Refresh failed: ${error.message}`, true); }
    }

    async function saveMinimumElevation(event) {
        event.preventDefault();
        if (state.busy) return;
        const input = byId("mission-planner-minimum-elevation");
        const button = event.currentTarget.querySelector('button[type="submit"]');
        state.busy = true; if (button) button.disabled = true;
        setMessage("Saving minimum elevation...");
        try {
            const response = await fetch("/api/weather-planning", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({minimum_elevation: Number(input.value)})});
            const payload = await response.json();
            if (!response.ok || payload.ok === false) throw new Error(payload.message || "Save failed.");
            setMessage(payload.message || "Minimum elevation saved.");
            window.dispatchEvent(new CustomEvent("sdrcc:weather-planning-changed", {detail: payload.settings}));
            await Promise.all([loadPlanner(), loadVoiceSchedule()]);
        } catch (error) { setMessage(`Save failed: ${error.message}`, true); }
        finally { state.busy = false; if (button) button.disabled = false; }
    }

    function localInput(value) {
        return String(value || "").replace(" ", "T").slice(0, 16);
    }

    function renderVoiceSchedule(payload) {
        const list = byId("voice-recording-list");
        const message = byId("voice-recording-message");
        if (!list) return;
        const passes = Array.isArray(payload.passes) ? payload.passes : [];
        const schedules = payload.schedules || {};
        if (message) message.textContent = payload.message || "Voice planning loaded.";
        if (!passes.length) {
            list.innerHTML = '<div class="mission-planner-empty">No ISS passes meet the current minimum elevation.</div>';
            return;
        }
        list.innerHTML = passes.map((item) => {
            const key = String(item.queue_key || "");
            const scheduled = schedules[key] || null;
            const receiver = scheduled?.receiver || payload.default_receiver || "auto";
            const start = scheduled?.start || item.start;
            const stop = scheduled?.stop || item.end;
            const custom = Boolean(scheduled?.use_custom_window);
            return `<article class="voice-recording-item ${scheduled ? "is-scheduled" : ""}" data-key="${escapeHtml(key)}">
                <div class="voice-recording-pass">
                    <div><span>${escapeHtml(formatDateTime(item.start))}</span><strong>${escapeHtml(item.name || "ISS")}</strong></div>
                    <div><span>Max elevation</span><strong>${Number(item.max_elevation || 0).toFixed(1)}°</strong></div>
                    <div><span>Pass window</span><strong>${escapeHtml(String(item.start || "").slice(11,16))}–${escapeHtml(String(item.end || "").slice(11,16))}</strong></div>
                    <span class="mission-planner-state ${scheduled ? "is-eligible" : "is-planned"}">${scheduled ? "SCHEDULED" : "AVAILABLE"}</span>
                </div>
                <form class="voice-recording-form" data-key="${escapeHtml(key)}">
                    <label class="voice-recording-check"><input type="checkbox" name="use_custom_window" ${custom ? "checked" : ""}> Custom recording window</label>
                    <label>Start<input type="datetime-local" name="start" value="${escapeHtml(localInput(start))}" ${custom ? "" : "disabled"}></label>
                    <label>Stop<input type="datetime-local" name="stop" value="${escapeHtml(localInput(stop))}" ${custom ? "" : "disabled"}></label>
                    <label>Receiver<select name="receiver"><option value="auto" ${receiver === "auto" ? "selected" : ""}>Auto (recommended)</option><option value="sdr1" ${receiver === "sdr1" ? "selected" : ""}>SDR1</option><option value="sdr2" ${receiver === "sdr2" ? "selected" : ""}>SDR2</option></select></label>
                    <div class="voice-recording-fixed-status" title="Audio recording is always enabled"><strong>✓</strong><span>Audio recording</span></div>
                    <label class="voice-recording-check"><input type="checkbox" name="live_monitor" ${scheduled?.live_monitor ? "checked" : ""}> Live monitor</label>
                    <div class="voice-recording-actions"><button type="submit" class="control-button">${scheduled ? "Update recording" : "Schedule recording"}</button>${scheduled ? '<button type="button" class="control-button danger" data-remove>Remove</button>' : ""}</div>
                </form>
            </article>`;
        }).join("");
    }

    async function loadVoiceSchedule() {
        try {
            const response = await fetch("/api/voice-schedule?hours=48", {cache: "no-store"});
            const payload = await response.json();
            if (!response.ok || payload.ok === false) throw new Error(payload.error || "Voice planning unavailable.");
            renderVoiceSchedule(payload);
        } catch (error) {
            const message = byId("voice-recording-message"); if (message) { message.textContent = error.message; message.classList.add("error-text"); }
        }
    }

    byId("voice-recording-list")?.addEventListener("change", (event) => {
        if (event.target.name !== "use_custom_window") return;
        const form = event.target.closest("form");
        form?.querySelectorAll('input[type="datetime-local"]').forEach((input) => { input.disabled = !event.target.checked; });
    });

    byId("voice-recording-list")?.addEventListener("submit", async (event) => {
        const form = event.target.closest(".voice-recording-form"); if (!form) return;
        event.preventDefault();
        const data = new FormData(form); const custom = data.get("use_custom_window") === "on";
        const payload = {queue_key: form.dataset.key, use_custom_window: custom, receiver: data.get("receiver"), live_monitor: data.get("live_monitor") === "on"};
        if (custom) { payload.start = data.get("start"); payload.stop = data.get("stop"); }
        const response = await fetch("/api/voice-schedule?hours=48", {method: "PUT", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)});
        const result = await response.json();
        if (!response.ok || result.ok === false) { alert(result.error || "Planning failed"); return; }
        renderVoiceSchedule(result);
    });

    byId("voice-recording-list")?.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-remove]"); if (!button) return;
        const form = button.closest(".voice-recording-form");
        const response = await fetch("/api/voice-schedule?hours=48", {method: "DELETE", headers: {"Content-Type":"application/json"}, body: JSON.stringify({queue_key: form.dataset.key})});
        const result = await response.json();
        if (!response.ok || result.ok === false) { alert(result.error || "Remove failed"); return; }
        renderVoiceSchedule(result);
    });

    byId("mission-planner-settings-form")?.addEventListener("submit", saveMinimumElevation);
    byId("mission-planner-refresh")?.addEventListener("click", () => Promise.all([loadPlanner(), loadVoiceSchedule()]));
    window.addEventListener("sdrcc:weather-planning-changed", () => Promise.all([loadPlanner(), loadVoiceSchedule()]));
    Promise.all([loadPlanner(), loadVoiceSchedule()]);
    state.timer = window.setInterval(() => Promise.all([loadPlanner(), loadVoiceSchedule()]), 15000);
})();
