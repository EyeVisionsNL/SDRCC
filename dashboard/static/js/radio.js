(() => {
    "use strict";

    const editing = {
        assignment: {dirty: false, saving: false, focused: false},
        weather: {dirty: false, saving: false, focused: false},
        iss: {dirty: false, saving: false, focused: false},
    };

    let lastReceiverContexts = null;

    function isEditing(name) {
        const state = editing[name];
        return state.dirty || state.saving || state.focused;
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function setText(id, value) {
        const element = document.getElementById(id);
        if (!element) return;
        element.textContent = value;
        if (id === "assignment-policy-result") element.hidden = !value;
    }

    async function getStatus() {
        const response = await fetch("/api/status", {cache: "no-store"});
        if (!response.ok) throw new Error("Status API unavailable");
        return await response.json();
    }

    async function getReceiverAuthority() {
        const response = await fetch("/api/receiver-assignments", {cache: "no-store"});
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || data.error || "Assignment API unavailable");
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

    function renderAssignmentRuntimeSummary() {
        const runtime = document.getElementById("assignment-policy-runtime");
        if (!runtime || !lastReceiverContexts) return;
        const roles = lastReceiverContexts.roles || {};
        runtime.innerHTML = ["weather", "ais", "adsb", "iss_voice"].map(role => {
            const item = roles[role] || {};
            const configured = String(item.configured_receiver || "-").toUpperCase();
            const verified = item.verified_runtime_receiver
                ? String(item.verified_runtime_receiver).toUpperCase()
                : (item.runtime_active ? "UNVERIFIED" : "INACTIVE");
            const state = String(item.verification || "UNKNOWN").replaceAll("_", " ");
            return `<div class="assignment-runtime-role" data-state="${escapeHtml(state.toLowerCase())}">
                <span>${escapeHtml(roleLabel(role))}</span>
                <strong>Configured ${escapeHtml(configured)} · Runtime ${escapeHtml(verified)}</strong>
                <small>${escapeHtml(state)}</small>
            </div>`;
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
                `<div><strong>${escapeHtml(roleLabel(item.role))}</strong><span>${escapeHtml(
                    String(item.type || "configuration drift").replaceAll("_", " ")
                )} · expected ${escapeHtml(item.expected_serial || "-")} · configured ${escapeHtml(
                    item.service_config_serial || "-"
                )} · runtime ${escapeHtml(item.runtime_serial || "-")}</span></div>`
            ).join("");
        }
        renderAssignmentRuntimeSummary();
    }

    function receiverNumber(device, index) {
        const name = String(device.name || device.id || "");
        const match = name.match(/SDR\s*(\d+)/i);
        return match ? `SDR${match[1]}` : `SDR${index + 1}`;
    }

    function assignmentReceiverLabel(device, index) {
        const number = receiverNumber(device, index);
        const name = String(device.name || "").trim();
        return !name || name.replace(/\s+/g, "").toUpperCase() === number.toUpperCase()
            ? number
            : `${number} · ${name}`;
    }

    function updateAssignmentReceiverOptions(devices) {
        const byId = {};
        for (const [index, device] of (devices || []).entries()) {
            byId[String(device.id || `sdr${index + 1}`).toLowerCase()] = assignmentReceiverLabel(device, index);
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
            for (const option of select.options) {
                option.textContent = byId[option.value] || option.value.toUpperCase();
            }
            select.value = selected;
        }
    }

    function populateGainOptions(select, settings) {
        if (!select) return;
        if (!select.options.length) {
            for (const value of settings.valid_gains || []) {
                const option = document.createElement("option");
                option.value = String(value);
                option.textContent = `${Number(value).toFixed(1)} dB`;
                select.appendChild(option);
            }
        }
        select.value = String(settings.gain_db);
    }

    function updateWeatherControls() {
        const mode = document.getElementById("weather-gain-mode");
        const gain = document.getElementById("weather-gain-db");
        const lna = document.getElementById("weather-lna-agc");
        if (gain) gain.disabled = Boolean(lna?.checked) || mode?.value !== "manual";
    }

    function populateWeather(settings) {
        if (!settings) return;
        const mode = document.getElementById("weather-gain-mode");
        const gain = document.getElementById("weather-gain-db");
        if (mode) mode.value = settings.gain_mode || "auto";
        populateGainOptions(gain, settings);
        const mapping = {
            "weather-dc-block": settings.dc_block,
            "weather-iq-swap": settings.iq_swap,
            "weather-lna-agc": settings.lna_agc,
            "weather-fill-missing": settings.fill_missing,
            "weather-rs-usecheck": settings.rs_usecheck,
        };
        for (const [id, checked] of Object.entries(mapping)) {
            const control = document.getElementById(id);
            if (control) control.checked = Boolean(checked);
        }
        updateWeatherControls();
    }

    function updateIssControls() {
        const mode = document.getElementById("iss-voice-gain-mode");
        const gain = document.getElementById("iss-voice-gain-db");
        const enabled = document.getElementById("iss-voice-squelch-enabled");
        const threshold = document.getElementById("iss-voice-squelch-threshold");
        if (gain) gain.disabled = mode?.value !== "manual";
        if (threshold) threshold.disabled = !enabled?.checked;
        setText("iss-voice-squelch-value", `${Number(threshold?.value || -42).toFixed(0)} dBFS`);
    }

    function populateIss(settings) {
        if (!settings) return;
        const mode = document.getElementById("iss-voice-gain-mode");
        const gain = document.getElementById("iss-voice-gain-db");
        const enabled = document.getElementById("iss-voice-squelch-enabled");
        const threshold = document.getElementById("iss-voice-squelch-threshold");
        if (mode) mode.value = settings.gain_mode || "auto";
        populateGainOptions(gain, settings);
        if (enabled) enabled.checked = Boolean(settings.squelch_enabled);
        if (threshold) threshold.value = String(settings.squelch_threshold_dbfs ?? -42);
        updateIssControls();
    }

    async function updateRadioPage() {
        try {
            const data = await getStatus();
            updateAssignmentReceiverOptions(data.devices || []);
            if (!isEditing("assignment")) {
                try {
                    populateAssignmentPolicy(await getReceiverAuthority());
                } catch (error) {
                    setText("assignment-policy-result", `Assignment Authority unavailable: ${error.message}`);
                }
            }
            if (!isEditing("weather")) populateWeather(data.weather_rf || {});
            if (!isEditing("iss")) populateIss(data.iss_voice_settings || {});
        } catch (error) {
            console.error("Radio Control:", error);
        }
    }

    function bindEditing(form, name) {
        if (!form) return;
        for (const control of form.querySelectorAll("select, input")) {
            control.addEventListener("focus", () => { editing[name].focused = true; });
            control.addEventListener("blur", () => { editing[name].focused = false; });
            control.addEventListener("input", () => { editing[name].dirty = true; });
            control.addEventListener("change", () => { editing[name].dirty = true; });
        }
    }

    const assignmentForm = document.getElementById("receiver-assignments-form");
    bindEditing(assignmentForm, "assignment");
    assignmentForm?.addEventListener("submit", async event => {
        event.preventDefault();
        const submit = assignmentForm.querySelector('button[type="submit"]');
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
        editing.assignment.saving = true;
        if (submit) submit.disabled = true;
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
            editing.assignment.dirty = false;
            populateAssignmentPolicy(data.verification || await getReceiverAuthority());
            setText("assignment-policy-result", data.changed
                ? "Assignments applied, services synchronized and runtime verified."
                : "Assignments were already synchronized.");
        } catch (error) {
            setText("assignment-policy-result", `Apply failed: ${error.message}`);
        } finally {
            editing.assignment.saving = false;
            if (submit) submit.disabled = false;
        }
    });

    const weatherForm = document.getElementById("weather-rf-form");
    bindEditing(weatherForm, "weather");
    document.getElementById("weather-gain-mode")?.addEventListener("change", updateWeatherControls);
    document.getElementById("weather-lna-agc")?.addEventListener("change", updateWeatherControls);
    weatherForm?.addEventListener("submit", async event => {
        event.preventDefault();
        const submit = weatherForm.querySelector('button[type="submit"]');
        editing.weather.saving = true;
        if (submit) submit.disabled = true;
        try {
            const response = await fetch("/api/weather-rf", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    gain_mode: document.getElementById("weather-gain-mode").value,
                    gain_db: Number(document.getElementById("weather-gain-db").value),
                    dc_block: document.getElementById("weather-dc-block").checked,
                    iq_swap: document.getElementById("weather-iq-swap").checked,
                    lna_agc: document.getElementById("weather-lna-agc").checked,
                    fill_missing: document.getElementById("weather-fill-missing").checked,
                    rs_usecheck: document.getElementById("weather-rs-usecheck").checked,
                }),
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.message || `HTTP ${response.status}`);
            populateWeather(data.settings);
            editing.weather.dirty = false;
            setText("weather-rf-result", data.message || "Weather / METEOR settings saved.");
        } catch (error) {
            setText("weather-rf-result", `Save failed: ${error.message}`);
        } finally {
            editing.weather.saving = false;
            if (submit) submit.disabled = false;
        }
    });

    const issForm = document.getElementById("iss-voice-settings-form");
    bindEditing(issForm, "iss");
    document.getElementById("iss-voice-gain-mode")?.addEventListener("change", updateIssControls);
    document.getElementById("iss-voice-squelch-enabled")?.addEventListener("change", updateIssControls);
    document.getElementById("iss-voice-squelch-threshold")?.addEventListener("input", updateIssControls);
    issForm?.addEventListener("submit", async event => {
        event.preventDefault();
        const submit = issForm.querySelector('button[type="submit"]');
        editing.iss.saving = true;
        if (submit) submit.disabled = true;
        try {
            const response = await fetch("/api/iss-voice/settings", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    gain_mode: document.getElementById("iss-voice-gain-mode").value,
                    gain_db: Number(document.getElementById("iss-voice-gain-db").value),
                    squelch_enabled: document.getElementById("iss-voice-squelch-enabled").checked,
                    squelch_threshold_dbfs: Number(document.getElementById("iss-voice-squelch-threshold").value),
                }),
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.message || `HTTP ${response.status}`);
            populateIss(data.settings);
            editing.iss.dirty = false;
            setText("iss-voice-settings-result", data.message || "ISS Voice settings saved.");
        } catch (error) {
            setText("iss-voice-settings-result", `Save failed: ${error.message}`);
        } finally {
            editing.iss.saving = false;
            if (submit) submit.disabled = false;
        }
    });

    function formatMonitorFrequency(value) {
        const hz = Number(value);
        return Number.isFinite(hz) && hz > 0
            ? `${(hz / 1e6).toFixed(hz >= 1e9 ? 0 : 3)} MHz`
            : "-";
    }

    function monitorMetric(label, value) {
        const display = value === null || value === undefined || value === "" ? "-" : value;
        return `<span>${escapeHtml(label)}<strong>${escapeHtml(display)}</strong></span>`;
    }

    function formatReceiverMetric(metric) {
        const value = metric ? metric.value : null;
        if (value === null || value === undefined || value === "") return "-";
        const number = Number(value);
        switch (String(metric.format || "text")) {
            case "frequency_hz": return formatMonitorFrequency(value);
            case "integer": return Number.isFinite(number) ? Math.round(number).toLocaleString("en-US") : "-";
            case "decimal_1": return Number.isFinite(number) ? number.toFixed(1) : "-";
            case "distance_nm": return Number.isFinite(number) ? `${number.toFixed(1)} NM` : "-";
            case "db_2": return Number.isFinite(number) ? `${number.toFixed(2)} dB` : "-";
            default: return String(value);
        }
    }

    function legacyReceiverMetrics(receiver) {
        const items = [];
        if (receiver.frequency_hz) {
            items.push({label: "Frequency", value: receiver.frequency_hz, format: "frequency_hz"});
        }
        for (const [key, value] of Object.entries(receiver.metrics || {})) {
            if (["available", "service_active", "source", "detail", "message_rate_source"].includes(key)) continue;
            items.push({label: key.replaceAll("_", " "), value, format: "text"});
        }
        return items;
    }

    function renderReceiverMonitor(data) {
        const grid = document.getElementById("receiver-monitor-grid");
        if (!grid) return;
        const receivers = data?.receivers || [];
        grid.innerHTML = receivers.map(receiver => {
            const roleClass = String(receiver.role || "idle").toLowerCase().replace(/[^a-z0-9]+/g, "-");
            const configured = (receiver.configured_roles || []).map(roleLabel).join(", ") || "None";
            const verified = (receiver.verified_runtime_roles || []).map(roleLabel).join(", ") || "None";
            const authority = receiver.authority_status || "UNKNOWN";
            const metrics = (Array.isArray(receiver.display_metrics)
                ? receiver.display_metrics
                : legacyReceiverMetrics(receiver)
            ).map(metric => monitorMetric(metric.label || metric.key || "Metric", formatReceiverMetric(metric))).join("");
            return `<article class="receiver-monitor-item role-${escapeHtml(roleClass)}${receiver.configuration_drift ? " has-drift" : ""}">
                <div class="receiver-monitor-heading">
                    <div><strong>${escapeHtml(receiver.number || receiver.id || "SDR")}</strong><small>${escapeHtml(receiver.serial || "-")}</small></div>
                    <div class="receiver-monitor-badges"><span>${escapeHtml(receiver.role || "IDLE")}</span><span>${escapeHtml(receiver.status || "-")}</span></div>
                </div>
                <div class="receiver-monitor-authority">
                    <span>Configured<strong>${escapeHtml(configured)}</strong></span>
                    <span>Verified runtime<strong>${escapeHtml(verified)}</strong></span>
                    <span>Drift<strong data-state="${escapeHtml(String(authority).toLowerCase())}">${escapeHtml(authority)}</strong></span>
                </div>
                <div class="receiver-monitor-metrics">${metrics}</div>
                <p>${escapeHtml(receiver.detail || "-")}</p>
            </article>`;
        }).join("");
        if (!receivers.length) grid.textContent = "No receiver status available.";
        const updated = document.getElementById("receiver-monitor-updated");
        if (updated) {
            updated.textContent = data?.authority_status || (receivers.length ? "OBSERVED" : "UNAVAILABLE");
            updated.dataset.state = String(data?.authority_status || "unknown").toLowerCase();
        }
    }

    async function updateReceiverMonitor() {
        try {
            const response = await fetch("/api/receiver-monitor", {cache: "no-store"});
            const data = await response.json();
            if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
            renderReceiverMonitor(data);
        } catch (error) {
            const grid = document.getElementById("receiver-monitor-grid");
            if (grid) grid.textContent = `Receiver Monitor unavailable: ${error.message}`;
            const updated = document.getElementById("receiver-monitor-updated");
            if (updated) {
                updated.textContent = "ERROR";
                updated.dataset.state = "error";
            }
        }
    }

    updateRadioPage();
    updateReceiverMonitor();
    window.setInterval(updateRadioPage, 3000);
    window.setInterval(updateReceiverMonitor, 2000);
})();
