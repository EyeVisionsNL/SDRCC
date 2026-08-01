(() => {
    let rfFormDirty = false;
    let rfFormSaving = false;
    let rfFormFocused = false;
    let assignmentFormDirty = false;
    let assignmentFormSaving = false;
    let assignmentFormFocused = false;
    let lastDevices = [];
    let missionQueueByReceiver = {};
    let lastReceiverContexts = null;

    function rfFormIsBeingEdited() {
        return rfFormDirty || rfFormSaving || rfFormFocused;
    }

    function assignmentFormIsBeingEdited() {
        return assignmentFormDirty || assignmentFormSaving || assignmentFormFocused;
    }

    async function getStatus() {
        const response = await fetch("/api/status", {cache: "no-store"});
        if (!response.ok) throw new Error("status api fout");
        return await response.json();
    }


    async function getReceiverAuthority() {
        const response = await fetch("/api/receiver-assignments", {cache: "no-store"});
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || data.error || "receiver assignments api error");
        return data;
    }

    function roleLabel(value) {
        const role = String(value || "").trim().toLowerCase();
        const labels = {
            ais: "AIS",
            adsb: "ADS-B",
            weather: "Weather / METEOR",
            iss_voice: "ISS Voice",
            meshcore: "MeshCore",
        };
        return labels[role] || (role ? role.replaceAll("_", " ").toUpperCase() : "-");
    }

    function receiverQueueRole(receiver) {
        const item = missionQueueByReceiver[receiver];
        return item ? String(item.mission_type || item.plugin_id || item.receiver_role || "") : "";
    }

    function renderAssignmentRuntimeSummary() {
        const runtime = document.getElementById("assignment-policy-runtime");
        if (!runtime || !lastReceiverContexts) return;

        const roles = lastReceiverContexts.roles || {};
        const order = ["weather", "ais", "adsb", "iss_voice"];
        runtime.innerHTML = order.map(role => {
            const item = roles[role] || {};
            const configured = String(item.configured_receiver || "-").toUpperCase();
            const verified = item.verified_runtime_receiver
                ? String(item.verified_runtime_receiver).toUpperCase()
                : (item.runtime_active ? "UNVERIFIED" : "INACTIVE");
            const state = String(item.verification || "UNKNOWN").replaceAll("_", " ");
            return `<div class="assignment-runtime-role" data-state="${state.toLowerCase()}"><span>${roleLabel(role)}</span><strong>Configured ${configured} · Runtime ${verified}</strong><small>${state}</small></div>`;
        }).join("");
    }

    function populateAssignmentPolicy(data) {
        lastReceiverContexts = data;
        const assignments = data.configured_assignments || data.assignments || {};
        for (const role of ["weather", "ais", "adsb", "iss_voice"]) {
            const suffix = role === "iss_voice" ? "iss-voice" : role;
            const select = document.getElementById(`receiver-assignment-${suffix}`);
            if (select && assignments[role]) select.value = assignments[role];
        }
        const status = document.getElementById("assignment-authority-status");
        if (status) {
            status.textContent = String(data.status || "UNKNOWN").replaceAll("_", " ");
            status.dataset.state = String(data.status || "unknown").toLowerCase();
        }
        const drift = document.getElementById("assignment-authority-drift");
        const driftItems = Array.isArray(data.drift) ? data.drift : [];
        if (drift) {
            drift.hidden = driftItems.length === 0;
            drift.innerHTML = driftItems.map(item =>
                `<div><strong>${roleLabel(item.role)}</strong><span>${String(item.type || "configuration drift").replaceAll("_", " ")} · expected ${item.expected_serial || "-"} · configured ${item.service_config_serial || "-"} · runtime ${item.runtime_serial || "-"}</span></div>`
            ).join("");
        }
        renderAssignmentRuntimeSummary();
    }

    function setText(id, value) {
        const element = document.getElementById(id);
        if (!element) return;
        element.textContent = value;
        if (id === "assignment-policy-result") element.hidden = !value;
    }

    function clearAssignmentPolicyResult() {
        const element = document.getElementById("assignment-policy-result");
        if (!element) return;
        element.textContent = "";
        element.hidden = true;
    }

    function setPill(id, service) {
        const element = document.getElementById(id);
        if (!element) return;
        const running = service && service.active;
        element.textContent = running ? "RUNNING" : (service ? String(service.state || "-").toUpperCase() : "-");
        element.classList.toggle("running", running);
    }



    function populateRf(settings) {
        if (!settings) return;
        const mode = document.getElementById("weather-gain-mode");
        const gain = document.getElementById("weather-gain-db");
        if (mode) mode.value = settings.gain_mode || "auto";
        if (gain) {
            const current = String(settings.gain_db);
            if (!gain.options.length) {
                (settings.valid_gains || []).forEach(value => {
                    const option = document.createElement("option");
                    option.value = String(value);
                    option.textContent = `${Number(value).toFixed(1)} dB`;
                    gain.appendChild(option);
                });
            }
            gain.value = current;
            gain.disabled = (settings.gain_mode || "auto") !== "manual";
        }
        const dc = document.getElementById("weather-dc-block");
        const iq = document.getElementById("weather-iq-swap");
        const lna = document.getElementById("weather-lna-agc");
        const fill = document.getElementById("weather-fill-missing");
        const rs = document.getElementById("weather-rs-usecheck");
        if (dc) dc.checked = Boolean(settings.dc_block);
        if (iq) iq.checked = Boolean(settings.iq_swap);
        if (lna) lna.checked = Boolean(settings.lna_agc);
        if (fill) fill.checked = Boolean(settings.fill_missing);
        if (rs) rs.checked = Boolean(settings.rs_usecheck);
        if (gain) gain.disabled = Boolean(settings.lna_agc) || (settings.gain_mode || "auto") !== "manual";
    }

    function receiverNumber(dev, index) {
        const name = String(dev.name || dev.id || "");
        const match = name.match(/SDR\s*(\d+)/i);
        return match ? `SDR${match[1]}` : `SDR${index + 1}`;
    }

    function assignmentReceiverLabel(dev, index) {
        const number = receiverNumber(dev, index);
        const name = String(dev.name || "").trim();
        const compactName = name.replace(/\s+/g, "").toUpperCase();
        const compactNumber = number.replace(/\s+/g, "").toUpperCase();
        return !name || compactName === compactNumber ? number : `${number} · ${name}`;
    }

    function normalizeReceiver(value) {
        const normalized = String(value || "").trim().toUpperCase().replaceAll("_", "");
        if (normalized.includes("SDR1") || normalized === "1") return "SDR1";
        if (normalized.includes("SDR2") || normalized === "2") return "SDR2";
        return "";
    }

    function updateAssignmentReceiverOptions(devices) {
        const byId = {};
        for (const [index, dev] of (devices || []).entries()) {
            const id = String(dev.id || `sdr${index + 1}`).toLowerCase();
            byId[id] = assignmentReceiverLabel(dev, index);
        }
        for (const selectId of [
            "receiver-assignment-weather",
            "receiver-assignment-ais",
            "receiver-assignment-adsb",
            "receiver-assignment-iss-voice",
        ]) {
            const select = document.getElementById(selectId);
            if (!select) continue;
            const selected = select.value;
            for (const option of select.options) option.textContent = byId[option.value] || option.value.toUpperCase();
            select.value = selected;
        }
    }

    function missionQueueTask(item) {
        if (!item) return "";
        const name = item.name || item.satellite || "Mission";
        const type = String(item.mission_type || item.plugin_id || item.receiver_role || "")
            .replaceAll("_", " ")
            .toUpperCase();
        return type ? `${name} · ${type}` : name;
    }

    function renderDevices(devices) {
        lastDevices = Array.isArray(devices) ? devices : [];
        updateAssignmentReceiverOptions(lastDevices);
        const container = document.getElementById("radio-devices");
        if (!container) return;
        container.innerHTML = "";

        for (const [index, dev] of lastDevices.entries()) {
            const number = receiverNumber(dev, index);
            const queuedTask = missionQueueTask(missionQueueByReceiver[normalizeReceiver(number)]);
            const nextTask = queuedTask || dev.next_task || "-";
            const item = document.createElement("article");
            item.className = "radio-device";
            item.innerHTML = `
                <div class="receiver-card-title">
                    <strong>${number}</strong>
                    <span class="receiver-badge receiver-badge-${String(dev.status_label || "available").toLowerCase().replaceAll(" ", "-")}">${dev.status_label || "AVAILABLE"}</span>
                </div>
                <div class="receiver-detail-grid">
                    <span>Naam<strong>${dev.name || dev.id || "-"}</strong></span>
                    <span>Serienummer<strong>${dev.serial || "-"}</strong></span>
                    <span>Standaardtaak<strong>${dev.default_task || "-"}</strong></span>
                    <span>Huidige taak<strong>${dev.current_task || "-"}</strong></span>
                    <span>Volgende taak<strong>${nextTask}</strong></span>
                    <span>Bron / status<strong>${dev.active_detail || "-"}</strong></span>
                </div>
            `;
            container.appendChild(item);
        }

        if (!devices || devices.length === 0) {
            container.textContent = "Geen SDR-apparaten gevonden.";
        }
    }

    async function getLiveRf() {
        const response = await fetch("/api/live-rf", {cache: "no-store"});
        if (!response.ok) throw new Error("live rf api fout");
        return await response.json();
    }

    function formatSeconds(value, fallback = "--:--") {
        const seconds = Number(value);
        if (!Number.isFinite(seconds) || seconds < 0) return fallback;
        const rounded = Math.max(0, Math.round(seconds));
        const minutes = Math.floor(rounded / 60);
        const remainder = rounded % 60;
        return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
    }

    function formatFrequency(value) {
        const hz = Number(value);
        return Number.isFinite(hz) && hz > 0 ? `${(hz / 1e6).toFixed(3)} MHz` : "-";
    }

    function formatSampleRate(value) {
        const rate = Number(value);
        if (!Number.isFinite(rate) || rate <= 0) return "-";
        return rate >= 1e6 ? `${(rate / 1e6).toFixed(3)} MS/s` : `${Math.round(rate / 1e3)} kS/s`;
    }

    function formatDb(value, fallback = "--.-- dB") {
        const number = Number(value);
        return Number.isFinite(number) ? `${number.toFixed(2)} dB` : fallback;
    }

    function setTelemetryStatus(id, value) {
        const element = document.getElementById(id);
        if (!element) return;
        const status = String(value || "UNKNOWN").toUpperCase();
        element.textContent = status;
        element.classList.remove("telemetry-sync", "telemetry-nosync", "telemetry-unknown");
        if (status === "SYNC") element.classList.add("telemetry-sync");
        else if (status === "NOSYNC") element.classList.add("telemetry-nosync");
        else element.classList.add("telemetry-unknown");
    }

    function renderLiveRf(data) {
        const active = Boolean(data && data.active);
        const state = String((data && data.state) || "IDLE").toUpperCase();
        const stateElement = document.getElementById("live-rf-state");
        if (stateElement) {
            stateElement.textContent = state;
            stateElement.className = `live-rf-state live-rf-state-${state.toLowerCase().replaceAll(" ", "-")}`;
        }

        setText("live-rf-satellite", data.satellite || (active ? "Weather mission" : "No active weather mission"));
        setText("live-rf-detail", data.detail || data.last_line || (active ? "SatDump telemetry active." : "SatDump telemetry appears here during a recording."));
        setText("live-rf-updated", data.updated_at ? `Updated ${data.updated_at}` : "Waiting for telemetry...");
        setText("live-rf-elapsed", formatSeconds(data.elapsed_seconds, "00:00"));
        setText("live-rf-remaining", formatSeconds(data.remaining_seconds));
        setText("live-rf-snr", formatDb(data.snr_db));
        setText("live-rf-peak-snr", formatDb(data.peak_snr_db));
        setText("live-rf-ber", Number.isFinite(Number(data.ber)) ? Number(data.ber).toFixed(6) : "-----");
        setText("live-rf-frames", Number(data.frames || 0).toLocaleString("nl-NL"));
        setTelemetryStatus("live-rf-viterbi", data.viterbi);
        setTelemetryStatus("live-rf-deframer", data.deframer);
        setText("live-rf-receiver", data.receiver || "-");
        setText("live-rf-serial", data.serial || "-");
        setText("live-rf-frequency", formatFrequency(data.frequency_hz));
        setText("live-rf-samplerate", formatSampleRate(data.sample_rate));
        const gainMode = data.gain_mode ? String(data.gain_mode).toUpperCase() : "-";
        const gainValue = Number.isFinite(Number(data.gain_db)) ? ` · ${Number(data.gain_db).toFixed(1)} dB` : "";
        setText("live-rf-gain", `${gainMode}${gainValue}`);
        setText("live-rf-processing", `DC ${data.dc_block ? "AAN" : "UIT"} · IQ ${data.iq_swap ? "SWAP" : "NORMAAL"}`);
        setText("live-rf-cadu", Number(data.cadu_bytes || 0).toLocaleString("nl-NL"));
        setText("live-rf-images", Number(data.image_count || 0).toLocaleString("nl-NL"));

        const timeout = Number(data.timeout_seconds);
        const elapsed = Number(data.elapsed_seconds);
        const progress = Number.isFinite(timeout) && timeout > 0 && Number.isFinite(elapsed)
            ? Math.max(0, Math.min(100, (elapsed / timeout) * 100))
            : 0;
        const progressBar = document.getElementById("live-rf-progress-bar");
        if (progressBar) progressBar.style.width = `${progress}%`;

        const snr = Number(data.snr_db);
        const snrPercent = Number.isFinite(snr) ? Math.max(0, Math.min(100, (snr / 15) * 100)) : 0;
        const snrBar = document.getElementById("live-rf-snr-bar");
        if (snrBar) snrBar.style.width = `${snrPercent}%`;
    }

    async function updateLiveRf() {
        try {
            renderLiveRf(await getLiveRf());
        } catch (error) {
            console.log("Live RF update mislukt:", error.message);
        }
    }

    window.addEventListener("sdrcc:mission-queue-updated", event => {
        const queue = Array.isArray(event.detail?.queue) ? event.detail.queue : [];
        const nextByReceiver = {};
        for (const item of queue) {
            if (!item || item.skipped) continue;
            const receiver = normalizeReceiver(
                item.active_receiver || item.reserved_receiver || item.configured_receiver || item.receiver || item.receiver_id
            );
            if (!receiver || nextByReceiver[receiver]) continue;
            nextByReceiver[receiver] = item;
        }
        missionQueueByReceiver = nextByReceiver;
        if (lastDevices.length) renderDevices(lastDevices);
        renderAssignmentRuntimeSummary();
    });

    async function updateRadioPage() {
        try {
            const data = await getStatus();
            const sdr2 = data.sdr2 || {};
            setText("radio-sdr2-status", sdr2.status || "-");
            setText("radio-sdr2-profile", sdr2.profile || "-");
            setText("radio-sdr2-locked", sdr2.locked ? "YES" : "NO");
            setText("radio-sdr2-process", sdr2.process || "-");
            setText("radio-sdr2-updated", sdr2.updated || "-");
            setPill("radio-ais-pill", data.ais);
            setPill("radio-adsb-pill", data.adsb);
            renderDevices(data.devices || []);
            try {
                if (!assignmentFormIsBeingEdited()) {
                    populateAssignmentPolicy(await getReceiverAuthority());
                }
            } catch (contextError) {
                setText("assignment-policy-result", `Assignment Authority unavailable: ${contextError.message}`);
            }
            if (!rfFormIsBeingEdited()) {
                populateRf(data.weather_rf || {});
            }
            const weatherDevice = (data.devices || []).find(item => item.weather_selected);
        } catch (error) {
            console.log("Radio update mislukt:", error.message);
        }
    }

    const receiverAssignmentsForm = document.getElementById("receiver-assignments-form");
    if (receiverAssignmentsForm) {
        const submitButton = receiverAssignmentsForm.querySelector('button[type="submit"]');
        for (const control of receiverAssignmentsForm.querySelectorAll("select")) {
            control.addEventListener("focus", () => { assignmentFormFocused = true; });
            control.addEventListener("blur", () => { assignmentFormFocused = false; });
            control.addEventListener("change", () => {
                assignmentFormDirty = true;
                clearAssignmentPolicyResult();
            });
        }
        receiverAssignmentsForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const result = document.getElementById("assignment-policy-result");
            const assignments = {
                weather: document.getElementById("receiver-assignment-weather")?.value,
                ais: document.getElementById("receiver-assignment-ais")?.value,
                adsb: document.getElementById("receiver-assignment-adsb")?.value,
                iss_voice: document.getElementById("receiver-assignment-iss-voice")?.value,
            };
            if (assignments.ais === assignments.adsb) {
                setText("assignment-policy-result", "AIS and ADS-B cannot use the same receiver.");
                return;
            }
            assignmentFormSaving = true;
            if (submitButton) submitButton.disabled = true;
            setText("assignment-policy-result", "Applying transaction and verifying runtime...");
            try {
                const response = await fetch("/api/receiver-assignments", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({assignments}),
                });
                const data = await response.json();
                if (!response.ok || !data.ok) {
                    const rollback = data.rollback_performed
                        ? ` Rollback ${data.rollback_ok ? "completed" : "needs attention"}.`
                        : "";
                    throw new Error((data.message || `HTTP ${response.status}`) + rollback);
                }
                assignmentFormDirty = false;
                const verified = data.verification || await getReceiverAuthority();
                populateAssignmentPolicy(verified);
                setText(
                    "assignment-policy-result",
                    data.changed
                        ? "Assignments applied, services synchronized and runtime verified."
                        : "Assignments were already synchronized."
                );
            } catch (error) {
                setText("assignment-policy-result", `Apply failed: ${error.message}`);
            } finally {
                assignmentFormSaving = false;
                if (submitButton) submitButton.disabled = false;
            }
        });
    }


    const gainMode = document.getElementById("weather-gain-mode");
    if (gainMode) gainMode.addEventListener("change", () => {
        rfFormDirty = true;
        const gain = document.getElementById("weather-gain-db");
        if (gain) gain.disabled = document.getElementById("weather-lna-agc")?.checked || gainMode.value !== "manual";
    });

    const lnaAgc = document.getElementById("weather-lna-agc");
    if (lnaAgc) lnaAgc.addEventListener("change", () => {
        rfFormDirty = true;
        const gain = document.getElementById("weather-gain-db");
        if (gain) gain.disabled = lnaAgc.checked || document.getElementById("weather-gain-mode")?.value !== "manual";
    });

    const rfForm = document.getElementById("weather-rf-form");
    if (rfForm) {
        for (const control of rfForm.querySelectorAll("select, input")) {
            control.addEventListener("focus", () => { rfFormFocused = true; });
            control.addEventListener("blur", () => { rfFormFocused = false; });
            control.addEventListener("input", () => { rfFormDirty = true; });
            control.addEventListener("change", () => { rfFormDirty = true; });
        }

        rfForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const result = document.getElementById("weather-rf-result");
            const submitButton = rfForm.querySelector('button[type="submit"]');
            const payload = {
                gain_mode: document.getElementById("weather-gain-mode").value,
                gain_db: Number(document.getElementById("weather-gain-db").value),
                dc_block: document.getElementById("weather-dc-block").checked,
                iq_swap: document.getElementById("weather-iq-swap").checked,
                lna_agc: document.getElementById("weather-lna-agc").checked,
                fill_missing: document.getElementById("weather-fill-missing").checked,
                rs_usecheck: document.getElementById("weather-rs-usecheck").checked,
            };
            rfFormSaving = true;
            if (submitButton) submitButton.disabled = true;
            try {
                const response = await fetch("/api/weather-rf", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (result) result.textContent = data.message || "-";
                if (response.ok) {
                    populateRf(data.settings);
                    rfFormDirty = false;
                }
            } catch (error) {
                if (result) result.textContent = `Opslaan mislukt: ${error.message}`;
            } finally {
                rfFormSaving = false;
                if (submitButton) submitButton.disabled = false;
            }
        });
    }




    function formatMonitorFrequency(value) {
        const hz = Number(value);
        return Number.isFinite(hz) && hz > 0 ? `${(hz / 1e6).toFixed(hz >= 1e9 ? 0 : 3)} MHz` : "-";
    }

    function monitorMetric(label, value) {
        const display = value === null || value === undefined || value === "" ? "-" : value;
        return `<span>${label}<strong>${display}</strong></span>`;
    }

    function formatReceiverMetric(metric) {
        const value = metric ? metric.value : null;
        if (value === null || value === undefined || value === "") return "-";

        switch (String(metric.format || "text")) {
            case "frequency_hz":
                return formatMonitorFrequency(value);
            case "integer": {
                const number = Number(value);
                return Number.isFinite(number) ? Math.round(number).toLocaleString("nl-NL") : "-";
            }
            case "decimal_1": {
                const number = Number(value);
                return Number.isFinite(number) ? number.toFixed(1) : "-";
            }
            case "distance_nm": {
                const number = Number(value);
                return Number.isFinite(number) ? `${number.toFixed(1)} NM` : "-";
            }
            case "db_2": {
                const number = Number(value);
                return Number.isFinite(number) ? `${number.toFixed(2)} dB` : "-";
            }
            default:
                return String(value);
        }
    }

    function legacyReceiverMetrics(receiver) {
        const metrics = receiver.metrics || {};
        const items = [];
        if (receiver.frequency_hz) {
            items.push({label: "Frequentie", value: receiver.frequency_hz, format: "frequency_hz"});
        }
        for (const [key, value] of Object.entries(metrics)) {
            if (["available", "service_active", "source", "detail", "message_rate_source"].includes(key)) continue;
            items.push({label: key.replaceAll("_", " "), value, format: "text"});
        }
        return items;
    }

    function renderReceiverMetrics(receiver) {
        const metrics = Array.isArray(receiver.display_metrics)
            ? receiver.display_metrics
            : legacyReceiverMetrics(receiver);

        return metrics.map(metric => monitorMetric(metric.label || metric.key || "Metric", formatReceiverMetric(metric))).join("");
    }

    function renderReceiverMonitor(data) {
        const grid = document.getElementById("receiver-monitor-grid");
        if (!grid) return;
        const receivers = (data && data.receivers) || [];
        grid.innerHTML = "";
        for (const receiver of receivers) {
            const card = document.createElement("article");
            const roleClass = String(receiver.role || "idle").toLowerCase().replaceAll("-", "");
            const configured = (receiver.configured_roles || []).map(roleLabel).join(", ") || "None";
            const verified = (receiver.verified_runtime_roles || []).map(roleLabel).join(", ") || "None";
            const authorityState = receiver.authority_status || "UNKNOWN";
            card.className = `receiver-monitor-item role-${roleClass}${receiver.configuration_drift ? " has-drift" : ""}`;
            card.innerHTML = `
                <div class="receiver-monitor-heading">
                    <div><strong>${receiver.number || receiver.id || "SDR"}</strong><small>${receiver.serial || "-"}</small></div>
                    <div class="receiver-monitor-badges"><span>${receiver.role || "IDLE"}</span><span>${receiver.status || "-"}</span></div>
                </div>
                <div class="receiver-monitor-authority">
                    <span>Configured<strong>${configured}</strong></span>
                    <span>Verified runtime<strong>${verified}</strong></span>
                    <span>Drift<strong data-state="${String(authorityState).toLowerCase()}">${authorityState}</strong></span>
                </div>
                <div class="receiver-monitor-metrics">${renderReceiverMetrics(receiver)}</div>
                <p>${receiver.detail || "-"}</p>
            `;
            grid.appendChild(card);
        }
        if (!receivers.length) grid.textContent = "Geen receiverstatus beschikbaar.";
        setText(
            "receiver-monitor-updated",
            data && data.generated_at
                ? `${data.authority_status || "UNKNOWN"} · Updated ${data.generated_at}`
                : "Unavailable"
        );
    }

    async function updateReceiverMonitor() {
        try {
            const response = await fetch("/api/receiver-monitor", {cache: "no-store"});
            const data = await response.json();
            if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
            renderReceiverMonitor(data);
        } catch (error) {
            const grid = document.getElementById("receiver-monitor-grid");
            if (grid) grid.textContent = `Receiver Monitor niet beschikbaar: ${error.message}`;
        }
    }
    updateRadioPage();
    updateLiveRf();
    updateReceiverMonitor();
    setInterval(updateRadioPage, 3000);
    setInterval(updateLiveRf, 1000);
    setInterval(updateReceiverMonitor, 2000);
})();
