(() => {
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
            const selected = (data.assignments || {}).weather;
            const radio = document.querySelector(`input[name="weather_receiver"][value="${selected}"]`);
            if (radio) radio.checked = true;
            populateRf(data.weather_rf || {});
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


    const gainMode = document.getElementById("weather-gain-mode");
    if (gainMode) gainMode.addEventListener("change", () => {
        const gain = document.getElementById("weather-gain-db");
        if (gain) gain.disabled = gainMode.value !== "manual";
    });

    const rfForm = document.getElementById("weather-rf-form");
    if (rfForm) rfForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const result = document.getElementById("weather-rf-result");
        const payload = {
            gain_mode: document.getElementById("weather-gain-mode").value,
            gain_db: Number(document.getElementById("weather-gain-db").value),
            dc_block: document.getElementById("weather-dc-block").checked,
            iq_swap: document.getElementById("weather-iq-swap").checked,
        };
        try {
            const response = await fetch("/api/weather-rf", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
            const data = await response.json();
            if (result) result.textContent = data.message || "-";
            if (response.ok) populateRf(data.settings);
        } catch (error) { if (result) result.textContent = `Opslaan mislukt: ${error.message}`; }
    });

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

    updateRadioPage();
    setInterval(updateRadioPage, 3000);
})();
