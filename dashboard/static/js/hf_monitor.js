(() => {
    "use strict";

    let snapshot = null;
    let initialized = false;
    let actionBusy = false;
    let audio = null;
    let frequencyDirty = false;
    let hoverIndex = null;
    let spectrumView = null;
    let rfDirty = false;

    const byId = (id) => document.getElementById(id);

    function setText(id, value) {
        const element = byId(id);
        if (element) element.textContent = value;
    }

    function formatState(value) {
        return String(value || "-").replaceAll("_", " ");
    }

    function formatMHz(value) {
        const frequency = Number(value);
        return Number.isFinite(frequency) ? (frequency / 1_000_000).toFixed(6) : "-";
    }

    function selectedBand() {
        const bandId = byId("hf-monitor-band")?.value;
        return (snapshot?.bands || []).find((band) => band.id === bandId) || null;
    }

    function selectedReceiverOption() {
        const receiverId = byId("hf-monitor-receiver")?.value;
        return (snapshot?.receivers || []).find((receiver) => receiver.id === receiverId) || null;
    }

    function rfControlsFromForm() {
        return {
            gain_mode: byId("hf-monitor-auto-gain")?.checked ? "auto" : "manual",
            gain_db: Number(byId("hf-monitor-gain-db")?.value || 0),
            squelch_enabled: Boolean(byId("hf-monitor-squelch-enabled")?.checked),
            squelch_threshold_dbfs: Number(byId("hf-monitor-squelch-threshold")?.value || -42),
        };
    }

    function renderRfControlState(data) {
        const controls = data?.rf_controls || {};
        const autoGain = byId("hf-monitor-auto-gain");
        const gain = byId("hf-monitor-gain-db");
        const squelchEnabled = byId("hf-monitor-squelch-enabled");
        const squelch = byId("hf-monitor-squelch-threshold");
        const gains = Array.isArray(controls.valid_gains) ? controls.valid_gains : [];
        populateSelect(gain, gains, item => String(item), item => `${Number(item).toFixed(1)} dB`, String(controls.gain_db ?? 28));
        if (!rfDirty && !actionBusy) {
            if (autoGain) autoGain.checked = String(controls.gain_mode || "auto") === "auto";
            if (gain && gains.length) gain.value = String(controls.gain_db ?? gains[0]);
            if (squelchEnabled) squelchEnabled.checked = Boolean(controls.squelch_enabled);
            if (squelch) squelch.value = String(controls.squelch_threshold_dbfs ?? -42);
        }
        const isAuto = Boolean(autoGain?.checked);
        const band = selectedBand();
        const directSampling = data?.runtime_state === "LISTENING"
            ? data?.backend?.runtime?.settings?.sampling_mode === "Q_BRANCH_DIRECT"
            : Number(band?.maximum_hz || 0) < 25_000_000;
        if (gain) gain.disabled = actionBusy || isAuto || directSampling;
        if (squelch) squelch.disabled = actionBusy || !Boolean(squelchEnabled?.checked);
        setText("hf-monitor-squelch-value", `${Number(squelch?.value || -42).toFixed(0)} dBFS`);
        setText(
            "hf-monitor-gain-note",
            directSampling
                ? "Q-branch direct sampling bypasses the tuner: Auto Gain controls RTL AGC; numeric tuner gain is not effective on this band."
                : (isAuto ? "Automatic tuner gain / RTL AGC is active." : "Manual tuner gain is active on the normal tuner path."),
        );
        const signal = Number(controls.signal_dbfs);
        const signalText = Number.isFinite(signal) ? `${signal.toFixed(1)} dBFS` : "no RF level yet";
        const squelchState = controls.squelch_enabled
            ? (controls.squelch_open ? "squelch open" : "squelch closed")
            : "squelch off";
        setText("hf-monitor-rf-state", `${String(controls.gain_mode || "auto").toUpperCase()} gain · ${signalText} · ${squelchState}`);
        const apply = byId("hf-monitor-apply-rf");
        if (apply) apply.disabled = actionBusy || data?.runtime_state !== "LISTENING" || !rfDirty;
    }

    function populateSelect(element, items, valueFor, labelFor, preferred) {
        if (!element) return;
        const previous = element.value || preferred;
        const signature = items.map((item) => `${valueFor(item)}:${labelFor(item)}`).join("|");
        if (element.dataset.signature !== signature) {
            element.replaceChildren(...items.map((item) => {
                const option = document.createElement("option");
                option.value = valueFor(item);
                option.textContent = labelFor(item);
                return option;
            }));
            element.dataset.signature = signature;
        }
        if (items.some((item) => valueFor(item) === previous)) element.value = previous;
        else if (items.some((item) => valueFor(item) === preferred)) element.value = preferred;
    }

    function renderBandDetails({resetFrequency = false} = {}) {
        const band = selectedBand();
        if (!band) return;
        const frequency = byId("hf-monitor-frequency");
        if (frequency) {
            frequency.min = formatMHz(band.minimum_hz);
            frequency.max = formatMHz(band.maximum_hz);
            if (resetFrequency || !frequency.value) frequency.value = formatMHz(band.default_hz);
        }
        const points = snapshot?.spectrum?.points || [];
        const center = Number(byId("hf-monitor-frequency")?.value || formatMHz(band.default_hz)) * 1_000_000;
        const minimum = points.length ? points[0].frequency_hz : center - 120000;
        const maximum = points.length ? points[points.length - 1].frequency_hz : center + 120000;
        setText("hf-monitor-axis-min", `${formatMHz(minimum)} MHz`);
        setText("hf-monitor-axis-band", String(band.id || "HF").toUpperCase());
        setText("hf-monitor-axis-max", `${formatMHz(maximum)} MHz`);
    }

    function renderHandover() {
        const receiver = selectedReceiverOption();
        const target = byId("hf-monitor-handover");
        if (!target || !receiver) return;
        const heading = document.createElement("strong");
        let detail;
        if (receiver.pause_label) {
            heading.textContent = `${receiver.name} · pauses ${receiver.pause_label}`;
            detail = `Receiver Manager stops ${receiver.pause_label} only when it is active and restores that exact pre-start state after Stop or failure.`;
        } else {
            heading.textContent = `${receiver.name} · no continuous context assigned`;
            detail = "Receiver Manager still reserves this receiver and never starts a service that was inactive beforehand.";
        }
        target.replaceChildren(heading, document.createElement("br"), document.createTextNode(detail));
    }

    function fitCanvas(canvas) {
        if (!canvas) return null;
        const ratio = Math.max(1, window.devicePixelRatio || 1);
        const width = Math.max(320, Math.round(canvas.clientWidth * ratio));
        const height = Math.max(120, Math.round(canvas.clientHeight * ratio));
        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width;
            canvas.height = height;
        }
        return {context: canvas.getContext("2d"), width, height, ratio};
    }

    function levelRange(rows) {
        const values = rows.flat().filter(Number.isFinite);
        if (!values.length) return {minimum: -100, maximum: -20};
        const low = Math.min(...values);
        const high = Math.max(...values);
        return {
            minimum: Math.min(-45, Math.floor((low - 5) / 5) * 5),
            maximum: Math.max(-30, Math.ceil((high + 3) / 5) * 5),
        };
    }

    function drawSpectrum(points) {
        const fitted = fitCanvas(byId("hf-monitor-spectrum-canvas"));
        if (!fitted) return;
        const {context: ctx, width, height, ratio} = fitted;
        const plot = {
            left: 58 * ratio,
            right: width - (12 * ratio),
            top: 12 * ratio,
            bottom: height - (29 * ratio),
        };
        const plotWidth = Math.max(1, plot.right - plot.left);
        const plotHeight = Math.max(1, plot.bottom - plot.top);
        ctx.clearRect(0, 0, width, height);
        ctx.fillStyle = "#030c19";
        ctx.fillRect(0, 0, width, height);
        spectrumView = null;
        if (!points.length) {
            hoverIndex = null;
            byId("hf-monitor-spectrum-tooltip")?.setAttribute("hidden", "");
            return;
        }
        const levels = points.map((point) => Number(point.dbfs));
        const range = levelRange([levels]);
        const span = Math.max(10, range.maximum - range.minimum);
        ctx.font = `${10 * ratio}px system-ui, sans-serif`;
        ctx.lineWidth = ratio;
        ctx.textBaseline = "middle";
        for (let index = 0; index <= 5; index += 1) {
            const fraction = index / 5;
            const y = plot.top + (plotHeight * fraction);
            const level = range.maximum - (span * fraction);
            ctx.strokeStyle = index === 5 ? "rgba(56, 189, 248, 0.27)" : "rgba(56, 189, 248, 0.13)";
            ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(plot.right, y); ctx.stroke();
            ctx.fillStyle = "#7798ba";
            ctx.textAlign = "right";
            ctx.fillText(`${Math.round(level)} dB`, plot.left - (7 * ratio), y);
        }
        const minimumFrequency = Number(points[0].frequency_hz);
        const maximumFrequency = Number(points[points.length - 1].frequency_hz);
        for (let index = 0; index <= 6; index += 1) {
            const fraction = index / 6;
            const x = plot.left + (plotWidth * fraction);
            const frequency = minimumFrequency + ((maximumFrequency - minimumFrequency) * fraction);
            ctx.strokeStyle = "rgba(56, 189, 248, 0.13)";
            ctx.beginPath(); ctx.moveTo(x, plot.top); ctx.lineTo(x, plot.bottom); ctx.stroke();
            ctx.fillStyle = "#7798ba";
            ctx.textBaseline = "bottom";
            ctx.textAlign = index === 0 ? "left" : index === 6 ? "right" : "center";
            ctx.fillText((frequency / 1_000_000).toFixed(4), x, height - (3 * ratio));
        }
        ctx.textBaseline = "middle";
        const coordinates = levels.map((level, index) => ({
            x: plot.left + ((index / Math.max(1, levels.length - 1)) * plotWidth),
            y: plot.bottom - ((Math.max(range.minimum, Math.min(range.maximum, level)) - range.minimum) / span) * plotHeight,
        }));
        const gradient = ctx.createLinearGradient(0, plot.top, 0, plot.bottom);
        gradient.addColorStop(0, "rgba(250, 204, 21, 0.42)");
        gradient.addColorStop(0.6, "rgba(34, 211, 238, 0.16)");
        gradient.addColorStop(1, "rgba(15, 23, 42, 0)");
        ctx.beginPath();
        ctx.moveTo(coordinates[0].x, plot.bottom);
        coordinates.forEach((point) => ctx.lineTo(point.x, point.y));
        ctx.lineTo(coordinates[coordinates.length - 1].x, plot.bottom);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();
        ctx.beginPath();
        coordinates.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
        ctx.strokeStyle = "#facc15";
        ctx.lineWidth = 1.6 * ratio;
        ctx.shadowColor = "rgba(250, 204, 21, 0.6)";
        ctx.shadowBlur = 5 * ratio;
        ctx.stroke();
        ctx.shadowBlur = 0;
        spectrumView = {points, coordinates, plot, ratio};
        if (hoverIndex !== null && coordinates[hoverIndex]) {
            const coordinate = coordinates[hoverIndex];
            ctx.strokeStyle = "rgba(255, 255, 255, 0.72)";
            ctx.setLineDash([4 * ratio, 4 * ratio]);
            ctx.beginPath(); ctx.moveTo(coordinate.x, plot.top); ctx.lineTo(coordinate.x, plot.bottom); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(plot.left, coordinate.y); ctx.lineTo(plot.right, coordinate.y); ctx.stroke();
            ctx.setLineDash([]);
            ctx.beginPath();
            ctx.arc(coordinate.x, coordinate.y, 4 * ratio, 0, Math.PI * 2);
            ctx.fillStyle = "#ffffff";
            ctx.fill();
            ctx.strokeStyle = "#facc15";
            ctx.lineWidth = 2 * ratio;
            ctx.stroke();
        }
    }

    function spectrumIndexForEvent(event) {
        const canvas = byId("hf-monitor-spectrum-canvas");
        if (!canvas || !spectrumView?.points?.length) return null;
        const rect = canvas.getBoundingClientRect();
        const canvasX = (event.clientX - rect.left) * (canvas.width / Math.max(1, rect.width));
        const fraction = (canvasX - spectrumView.plot.left) /
            Math.max(1, spectrumView.plot.right - spectrumView.plot.left);
        if (fraction < 0 || fraction > 1) return null;
        return Math.max(0, Math.min(
            spectrumView.points.length - 1,
            Math.round(fraction * (spectrumView.points.length - 1)),
        ));
    }

    function moveSpectrumCursor(event) {
        const index = spectrumIndexForEvent(event);
        const tooltip = byId("hf-monitor-spectrum-tooltip");
        if (index === null || !tooltip) {
            hoverIndex = null;
            tooltip?.setAttribute("hidden", "");
            drawSpectrum(snapshot?.spectrum?.available ? snapshot.spectrum.points || [] : []);
            return;
        }
        hoverIndex = index;
        const point = spectrumView.points[index];
        tooltip.textContent = `${formatMHz(point.frequency_hz)} MHz · ${Number(point.dbfs).toFixed(1)} dBFS`;
        tooltip.removeAttribute("hidden");
        const stage = byId("hf-monitor-spectrum-stage");
        const rect = stage.getBoundingClientRect();
        const x = Math.max(78, Math.min(rect.width - 78, event.clientX - rect.left));
        const y = Math.max(12, Math.min(rect.height - 42, event.clientY - rect.top - 36));
        tooltip.style.left = `${x}px`;
        tooltip.style.top = `${y}px`;
        drawSpectrum(snapshot?.spectrum?.available ? snapshot.spectrum.points || [] : []);
    }

    function leaveSpectrum() {
        hoverIndex = null;
        byId("hf-monitor-spectrum-tooltip")?.setAttribute("hidden", "");
        drawSpectrum(snapshot?.spectrum?.available ? snapshot.spectrum.points || [] : []);
    }

    function chooseSpectrumFrequency(event) {
        const index = spectrumIndexForEvent(event);
        const point = index === null ? null : spectrumView?.points?.[index];
        const frequency = byId("hf-monitor-frequency");
        if (!point || !frequency) return;
        frequency.value = formatMHz(point.frequency_hz);
        frequencyDirty = true;
        renderBandDetails();
        if (snapshot?.retune_allowed) action("retune");
        else setText("hf-monitor-action-message", `Selected ${formatMHz(point.frequency_hz)} MHz; start HF listening when ready.`);
    }

    function waterfallColor(normalized) {
        const value = Math.max(0, Math.min(1, normalized));
        if (value < 0.45) {
            const amount = value / 0.45;
            return [2, Math.round(30 + 115 * amount), Math.round(62 + 150 * amount)];
        }
        if (value < 0.78) {
            const amount = (value - 0.45) / 0.33;
            return [Math.round(20 + 150 * amount), Math.round(145 + 85 * amount), Math.round(212 - 120 * amount)];
        }
        const amount = (value - 0.78) / 0.22;
        return [Math.round(170 + 85 * amount), Math.round(230 - 85 * amount), Math.round(92 - 55 * amount)];
    }

    function drawWaterfall(rows) {
        const fitted = fitCanvas(byId("hf-monitor-waterfall-canvas"));
        if (!fitted) return;
        const {context: ctx, width, height} = fitted;
        ctx.fillStyle = "#030c19";
        ctx.fillRect(0, 0, width, height);
        if (!rows.length || !rows[0]?.length) return;
        const range = levelRange(rows);
        const span = Math.max(10, range.maximum - range.minimum);
        const image = ctx.createImageData(rows[0].length, rows.length);
        rows.forEach((row, y) => row.forEach((level, x) => {
            const [red, green, blue] = waterfallColor((Number(level) - range.minimum) / span);
            const offset = ((y * row.length) + x) * 4;
            image.data[offset] = red;
            image.data[offset + 1] = green;
            image.data[offset + 2] = blue;
            image.data[offset + 3] = 255;
        }));
        const buffer = document.createElement("canvas");
        buffer.width = image.width;
        buffer.height = image.height;
        buffer.getContext("2d").putImageData(image, 0, 0);
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(buffer, 0, 0, width, height);
    }

    function stopAudio() {
        if (audio) {
            audio.pause();
            audio.removeAttribute("src");
            audio.load();
            audio = null;
        }
        const button = byId("hf-monitor-audio-toggle");
        if (button) button.textContent = "▶ Live audio";
    }

    async function toggleAudio() {
        if (audio) {
            stopAudio();
            setText("hf-monitor-audio-state", "Live audio stopped in this browser.");
            return;
        }
        const url = snapshot?.audio?.stream_url;
        if (!url) return;
        audio = new Audio(`${url}?t=${Date.now()}`);
        audio.volume = Number(byId("hf-monitor-audio-volume")?.value || 0.85);
        audio.addEventListener("error", () => {
            stopAudio();
            setText("hf-monitor-audio-state", "The live audio stream stopped.");
        }, {once: true});
        try {
            await audio.play();
            const button = byId("hf-monitor-audio-toggle");
            if (button) button.textContent = "■ Stop audio";
            setText("hf-monitor-audio-state", "Playing 16 kHz live HF audio.");
        } catch (error) {
            stopAudio();
            setText("hf-monitor-audio-state", error.message || "Browser audio could not start.");
        }
    }

    function render(data) {
        snapshot = data;
        const listening = data.runtime_state === "LISTENING";
        const selectionLocked = listening || data.runtime_state === "STARTING" || actionBusy;
        const status = byId("hf-monitor-status");
        if (status) {
            status.textContent = formatState(data.status);
            status.classList.toggle("is-error", ["ATTENTION", "BACKEND_UNAVAILABLE", "CONFIGURATION_ERROR"].includes(data.status));
        }
        setText("hf-monitor-runtime-state", `RECEIVER ${formatState(data.runtime_state)}`);
        setText("hf-monitor-controller-state", listening ? "LIVE DSP" : "BOUNDED CONTROL");
        setText("hf-monitor-backend", data.backend?.selected === "librtlsdr_qbranch_dsp" ? "LIBRTLSDR · HF DSP" : formatState(data.backend?.status));
        setText("hf-monitor-execution", data.execution_enabled ? "ENABLED" : "DISABLED");
        setText("hf-monitor-spectrum-state", data.spectrum?.available ? "LIVE MEASURED" : "NO LIVE DATA");

        populateSelect(byId("hf-monitor-receiver"), data.receivers || [], (item) => item.id, (item) => item.label, data.selected_receiver || data.default_receiver);
        populateSelect(byId("hf-monitor-band"), data.bands || [], (item) => item.id, (item) => `${String(item.id).toUpperCase()} · ${item.label}`, data.selected_band);
        populateSelect(byId("hf-monitor-mode"), data.modes || [], (item) => item, (item) => item, data.selected_mode);

        if (!initialized || listening) {
            if (byId("hf-monitor-receiver")) byId("hf-monitor-receiver").value = data.selected_receiver || data.default_receiver;
            if (byId("hf-monitor-band")) byId("hf-monitor-band").value = data.selected_band;
            if (byId("hf-monitor-mode")) byId("hf-monitor-mode").value = data.selected_mode;
            if (byId("hf-monitor-frequency") && (!listening || !frequencyDirty)) {
                byId("hf-monitor-frequency").value = formatMHz(data.selected_frequency_hz);
            }
        }
        renderRfControlState(data);

        ["hf-monitor-receiver", "hf-monitor-band", "hf-monitor-mode"].forEach((id) => {
            const control = byId(id);
            if (control) control.disabled = selectionLocked;
        });
        const frequency = byId("hf-monitor-frequency");
        if (frequency) frequency.disabled = actionBusy || data.runtime_state === "STARTING";
        const start = byId("hf-monitor-start");
        const retune = byId("hf-monitor-retune");
        const stop = byId("hf-monitor-stop");
        if (start) {
            start.disabled = actionBusy || !data.start_allowed;
            start.title = data.start_block_reason || "";
        }
        if (retune) retune.disabled = actionBusy || !data.retune_allowed;
        if (stop) stop.disabled = actionBusy || !data.stop_allowed;

        const message = listening
            ? `Live ${data.selected_mode} on ${formatMHz(data.selected_frequency_hz)} MHz via ${String(data.selected_receiver || "").toUpperCase()}.`
            : data.start_block_reason || "Ready to start one bounded HF session.";
        setText("hf-monitor-action-message", message);
        setText("hf-monitor-contract-message", "HF Monitor uses one measured librtlsdr IQ stream for spectrum, waterfall and audio. Receiver Manager restores only services that were active before Start.");

        const points = data.spectrum?.available && Array.isArray(data.spectrum?.points) ? data.spectrum.points : [];
        const rows = data.spectrum?.available && Array.isArray(data.spectrum?.waterfall) ? data.spectrum.waterfall : [];
        drawSpectrum(points);
        drawWaterfall(rows);
        const placeholder = byId("hf-monitor-spectrum-placeholder");
        if (placeholder) {
            placeholder.hidden = Boolean(data.spectrum?.available);
            if (!data.spectrum?.available) {
                const heading = placeholder.querySelector("strong");
                const detail = placeholder.querySelector("small");
                if (heading) heading.textContent = listening ? "ACQUIRING LIVE IQ" : "RECEIVER STOPPED";
                if (detail) detail.textContent = listening
                    ? "Waiting for the first measured spectrum after tuning."
                    : "Choose a receiver, band, mode and frequency, then start HF listening.";
            }
        }
        const hint = byId("hf-monitor-spectrum-hint");
        if (hint) hint.hidden = !data.spectrum?.available;
        if (!data.spectrum?.available) leaveSpectrum();

        const audioButton = byId("hf-monitor-audio-toggle");
        const volume = byId("hf-monitor-audio-volume");
        if (audioButton) audioButton.disabled = !data.audio?.available;
        if (volume) volume.disabled = !data.audio?.available;
        if (!listening && audio) stopAudio();
        if (!audio) {
            setText("hf-monitor-audio-state", data.audio?.available ? "Live 16 kHz audio is ready." : "Audio starts from the same live IQ stream.");
        }

        renderBandDetails();
        renderHandover();
        initialized = true;
    }

    function renderError(error) {
        setText("hf-monitor-status", "UNAVAILABLE");
        byId("hf-monitor-status")?.classList.add("is-error");
        setText("hf-monitor-action-message", error.message || "HF Monitor API unavailable.");
        const start = byId("hf-monitor-start");
        if (start) start.disabled = true;
    }

    async function load() {
        try {
            const response = await fetch("/api/hf-monitor", {cache: "no-store"});
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "HF Monitor configuration is invalid.");
            render(data);
        } catch (error) {
            renderError(error);
        }
    }

    async function action(name) {
        if (actionBusy) return;
        actionBusy = true;
        if (snapshot) render(snapshot);
        setText("hf-monitor-action-message", (
            name === "start" ? "Preparing receiver handover..." :
            name === "retune" ? "Retuning the live HF receiver..." :
            name === "rf_settings" ? "Applying gain and squelch in the live IQ worker..." :
            "Stopping HF and restoring receiver context..."
        ));
        const frequencyMHz = Number(byId("hf-monitor-frequency")?.value);
        const body = {
            action: name,
            selection: {
                receiver_id: byId("hf-monitor-receiver")?.value,
                band: byId("hf-monitor-band")?.value,
                mode: byId("hf-monitor-mode")?.value,
                frequency_hz: Math.round(frequencyMHz * 1_000_000),
                rf_controls: rfControlsFromForm(),
            },
            rf_controls: rfControlsFromForm(),
        };
        try {
            const response = await fetch("/api/hf-monitor/action", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(body),
            });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.message || "HF action failed.");
            if (name === "retune") frequencyDirty = false;
            if (name === "rf_settings") rfDirty = false;
            if (result.snapshot) render(result.snapshot);
            setText("hf-monitor-action-message", result.message);
        } catch (error) {
            setText("hf-monitor-action-message", error.message || "HF action failed.");
            await load();
        } finally {
            actionBusy = false;
            if (snapshot) render(snapshot);
        }
    }

    function isActive() {
        return byId("tab-hf-monitor")?.classList.contains("active");
    }

    byId("hf-monitor-receiver")?.addEventListener("change", renderHandover);
    byId("hf-monitor-band")?.addEventListener("change", () => {
        const band = selectedBand();
        if (band && byId("hf-monitor-mode")) byId("hf-monitor-mode").value = String(band.default_mode || "USB");
        renderBandDetails({resetFrequency: true});
        if (snapshot) renderRfControlState(snapshot);
    });
    byId("hf-monitor-frequency")?.addEventListener("input", () => {
        frequencyDirty = Boolean(snapshot?.runtime_state === "LISTENING");
        renderBandDetails();
    });
    ["hf-monitor-auto-gain", "hf-monitor-gain-db", "hf-monitor-squelch-enabled"].forEach((id) => {
        byId(id)?.addEventListener("change", () => {
            rfDirty = true;
            if (snapshot) renderRfControlState(snapshot);
        });
    });
    byId("hf-monitor-squelch-threshold")?.addEventListener("input", () => {
        rfDirty = true;
        if (snapshot) renderRfControlState(snapshot);
    });
    byId("hf-monitor-apply-rf")?.addEventListener("click", () => action("rf_settings"));
    byId("hf-monitor-start")?.addEventListener("click", () => action("start"));
    byId("hf-monitor-retune")?.addEventListener("click", () => action("retune"));
    byId("hf-monitor-stop")?.addEventListener("click", () => action("stop"));
    byId("hf-monitor-audio-toggle")?.addEventListener("click", toggleAudio);
    byId("hf-monitor-audio-volume")?.addEventListener("input", (event) => {
        if (audio) audio.volume = Number(event.target.value);
    });
    byId("hf-monitor-spectrum-canvas")?.addEventListener("mousemove", moveSpectrumCursor);
    byId("hf-monitor-spectrum-canvas")?.addEventListener("mouseleave", leaveSpectrum);
    byId("hf-monitor-spectrum-canvas")?.addEventListener("click", chooseSpectrumFrequency);
    document.querySelector('[data-tab="hf-monitor"]')?.addEventListener("click", load);
    window.addEventListener("resize", () => {
        if (snapshot) {
            drawSpectrum(snapshot.spectrum?.available ? snapshot.spectrum?.points || [] : []);
            drawWaterfall(snapshot.spectrum?.available ? snapshot.spectrum?.waterfall || [] : []);
        }
    });

    load();
    window.setInterval(() => {
        if (isActive()) load();
    }, 1000);
})();
