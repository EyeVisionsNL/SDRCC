(() => {
    let rfFormDirty = false;
    let rfFormSaving = false;
    let rfFormFocused = false;
    let receiverRolesDirty = false;

    function rfFormIsBeingEdited() {
        return rfFormDirty || rfFormSaving || rfFormFocused;
    }

    async function getStatus() {
        const response = await fetch("/api/status", {cache: "no-store"});
        if (!response.ok) throw new Error("status api fout");
        return await response.json();
    }

    function setText(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    }

    function setPill(id, service) {
        const element = document.getElementById(id);
        if (!element) return;
        const running = service && service.active;
        element.textContent = running ? "RUNNING" : (service ? String(service.state || "-").toUpperCase() : "-");
        element.classList.toggle("running", running);
    }


    function drawSpectrum(points) {
        const canvas = document.getElementById("weather-spectrum-canvas");
        if (!canvas || !points || points.length < 2) return;
        const ctx = canvas.getContext("2d");
        const width = canvas.width;
        const height = canvas.height;
        ctx.clearRect(0, 0, width, height);
        ctx.fillStyle = "#020712";
        ctx.fillRect(0, 0, width, height);
        const values = points.map(p => Number(p.dbm));
        const min = Math.min(...values) - 3;
        const max = Math.max(...values) + 3;
        ctx.strokeStyle = "#1e3652";
        ctx.lineWidth = 1;
        for (let i = 1; i < 5; i++) {
            const y = (height * i) / 5;
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
        }
        ctx.strokeStyle = "#21d4ff";
        ctx.lineWidth = 2;
        ctx.beginPath();
        points.forEach((point, index) => {
            const x = (index / (points.length - 1)) * width;
            const y = height - ((Number(point.dbm) - min) / Math.max(1, max - min)) * height;
            if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
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
        if (dc) dc.checked = Boolean(settings.dc_block);
        if (iq) iq.checked = Boolean(settings.iq_swap);
    }

    function populateReceiverRoles(data) {
        if (receiverRolesDirty) return;
        const devices = Array.isArray(data.devices) ? data.devices : [];
        const assignments = data.assignments || {};
        for (const receiverId of ["sdr1", "sdr2"]) {
            const select = document.getElementById(`receiver-role-${receiverId}`);
            const label = document.getElementById(`receiver-role-${receiverId}-label`);
            const device = devices.find(item => String(item.id || "").toLowerCase() === receiverId)
                || devices.find((item, index) => receiverNumber(item, index).toLowerCase() === receiverId);
            if (label) {
                const number = device ? (device.number || receiverId.toUpperCase()) : receiverId.toUpperCase();
                const serial = device && device.serial ? ` · ${device.serial}` : "";
                label.textContent = `${number}${serial}`;
            }
            if (!select) continue;
            let role = "manual";
            if (String(assignments.ais || "").toLowerCase() === receiverId) role = "ais";
            else if (String(assignments.adsb || "").toLowerCase() === receiverId) role = "adsb";
            select.value = role;
        }
    }

    function receiverNumber(dev, index) {
        const name = String(dev.name || dev.id || "");
        const match = name.match(/SDR\s*(\d+)/i);
        return match ? `SDR${match[1]}` : `SDR${index + 1}`;
    }

    function renderDevices(devices) {
        const container = document.getElementById("radio-devices");
        if (!container) return;
        container.innerHTML = "";

        for (const [index, dev] of (devices || []).entries()) {
            const number = receiverNumber(dev, index);
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
                    <span>Volgende taak<strong>${dev.next_task || "-"}</strong></span>
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

        setText("live-rf-satellite", data.satellite || (active ? "Weather-missie" : "Geen actieve Weather-missie"));
        setText("live-rf-detail", data.detail || data.last_line || (active ? "SatDump-telemetrie actief." : "SatDump-telemetrie verschijnt hier tijdens een opname."));
        setText("live-rf-updated", data.updated_at ? `Bijgewerkt ${data.updated_at}` : "Wachten op telemetrie...");
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
            populateReceiverRoles(data);
            const selected = (data.assignments || {}).weather;
            const radio = document.querySelector(`input[name="weather_receiver"][value="${selected}"]`);
            if (radio) radio.checked = true;
            if (!rfFormIsBeingEdited()) {
                populateRf(data.weather_rf || {});
            }
            const weatherDevice = (data.devices || []).find(item => item.weather_selected);
            setText("spectrum-device", weatherDevice ? `${weatherDevice.number} · ${weatherDevice.serial}` : "-");
        } catch (error) {
            console.log("Radio update mislukt:", error.message);
        }
    }

    const form = document.getElementById("receiver-assignment-form");
    if (form) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const selected = form.querySelector('input[name="weather_receiver"]:checked');
            const result = document.getElementById("receiver-assignment-result");
            if (!selected) {
                if (result) result.textContent = "Kies eerst SDR1 of SDR2.";
                return;
            }
            try {
                const response = await fetch("/api/receiver-assignment", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({weather: selected.value}),
                });
                const data = await response.json();
                if (result) result.textContent = data.message || (response.ok ? "Opgeslagen." : "Mislukt.");
                if (!response.ok) return;
                await updateRadioPage();
            } catch (error) {
                if (result) result.textContent = `Opslaan mislukt: ${error.message}`;
            }
        });
    }


    const receiverRolesForm = document.getElementById("receiver-roles-form");
    if (receiverRolesForm) {
        for (const select of receiverRolesForm.querySelectorAll("select")) {
            select.addEventListener("change", () => { receiverRolesDirty = true; });
        }
        receiverRolesForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const sdr1 = document.getElementById("receiver-role-sdr1")?.value || "manual";
            const sdr2 = document.getElementById("receiver-role-sdr2")?.value || "manual";
            const result = document.getElementById("receiver-roles-result");
            const submitButton = receiverRolesForm.querySelector('button[type="submit"]');
            if (sdr1 === sdr2 && ["ais", "adsb"].includes(sdr1)) {
                if (result) result.textContent = `${sdr1.toUpperCase()} kan niet tegelijk aan SDR1 en SDR2 worden toegewezen.`;
                return;
            }
            if (submitButton) submitButton.disabled = true;
            if (result) result.textContent = "Receiverrollen worden opgeslagen...";
            try {
                const response = await fetch("/api/receiver-roles", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({sdr1, sdr2}),
                });
                const data = await response.json();
                if (result) result.textContent = data.message || (response.ok ? "Opgeslagen." : "Mislukt.");
                if (!response.ok) return;
                receiverRolesDirty = false;
                await updateRadioPage();
            } catch (error) {
                if (result) result.textContent = `Opslaan mislukt: ${error.message}`;
            } finally {
                if (submitButton) submitButton.disabled = false;
            }
        });
    }

    const applyReceiverRolesButton = document.getElementById("apply-receiver-roles");
    if (applyReceiverRolesButton) {
        applyReceiverRolesButton.addEventListener("click", async () => {
            const result = document.getElementById("receiver-roles-apply-result");
            if (receiverRolesDirty) {
                if (result) result.textContent = "Bewaar eerst de gewijzigde rollen.";
                return;
            }
            applyReceiverRolesButton.disabled = true;
            if (result) result.textContent = "Services worden netjes gestopt, omgezet en opnieuw gestart...";
            try {
                const response = await fetch("/api/receiver-roles/apply", {method: "POST"});
                const data = await response.json();
                if (result) result.textContent = data.message || (response.ok ? "Toegepast." : "Mislukt.");
                if (response.ok) await updateRadioPage();
            } catch (error) {
                if (result) result.textContent = `Toepassen mislukt: ${error.message}`;
            } finally {
                applyReceiverRolesButton.disabled = false;
            }
        });
    }

    const gainMode = document.getElementById("weather-gain-mode");
    if (gainMode) gainMode.addEventListener("change", () => {
        rfFormDirty = true;
        const gain = document.getElementById("weather-gain-db");
        if (gain) gain.disabled = gainMode.value !== "manual";
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

    const scanButton = document.getElementById("start-spectrum-scan");
    if (scanButton) scanButton.addEventListener("click", async () => {
        const result = document.getElementById("spectrum-result");
        scanButton.disabled = true;
        if (result) result.textContent = "Spectrummeting bezig; ontvangerservice wordt tijdelijk gepauzeerd...";
        try {
            const frequency = Number(document.getElementById("spectrum-frequency").value);
            const response = await fetch("/api/weather-spectrum", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({frequency_hz:frequency})});
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || "Meting mislukt");
            const spectrum = data.spectrum;
            drawSpectrum(spectrum.points);
            setText("spectrum-peak-frequency", `${(spectrum.peak.frequency_hz / 1e6).toFixed(4)} MHz`);
            setText("spectrum-peak-db", `${spectrum.peak.dbm.toFixed(1)} dB`);
            setText("spectrum-noise-db", `${spectrum.noise_floor_dbm.toFixed(1)} dB`);
            setText("spectrum-snr-db", `${spectrum.signal_above_noise_db.toFixed(1)} dB`);
            if (result) result.textContent = `Meting voltooid met ${spectrum.device.number}; service is hersteld.`;
            await updateRadioPage();
        } catch (error) { if (result) result.textContent = error.message; }
        finally { scanButton.disabled = false; }
    });



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
            card.className = `receiver-monitor-item role-${roleClass}`;
            card.innerHTML = `
                <div class="receiver-monitor-heading">
                    <div><strong>${receiver.number || receiver.id || "SDR"}</strong><small>${receiver.serial || "-"}</small></div>
                    <div class="receiver-monitor-badges"><span>${receiver.role || "IDLE"}</span><span>${receiver.status || "-"}</span></div>
                </div>
                <div class="receiver-monitor-metrics">${renderReceiverMetrics(receiver)}</div>
                <p>${receiver.detail || "-"}</p>
            `;
            grid.appendChild(card);
        }
        if (!receivers.length) grid.textContent = "Geen receiverstatus beschikbaar.";
        setText("receiver-monitor-updated", data && data.generated_at ? `Bijgewerkt ${data.generated_at}` : "Niet beschikbaar");
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
