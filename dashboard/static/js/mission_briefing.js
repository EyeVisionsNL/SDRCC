(() => {
    const POLL_MS = 2000;
    const PIPELINE_STEPS = ["receiver", "recording", "decoder", "processing", "images", "archive"];
    const PIPELINE_LABELS = {
        waiting: "WACHTEN",
        active: "ACTIEF",
        complete: "GEREED",
        error: "FOUT",
    };
    const IMAGE_STATUS_LABELS = {
        waiting: "WACHTEN",
        decoding: "DECODER ACTIEF",
        building: "AFBEELDING OPBOUWEN",
        writing: "AFBEELDING OPSLAAN",
        complete: "GEREED",
        error: "FOUT",
    };

    let lastImageKey = "";

    async function getJson(url) {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
        return await response.json();
    }

    function setText(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    }

    function onlyTime(value) {
        if (!value || value === "-") return "-";
        const parts = String(value).split(" ");
        return parts.length > 1 ? parts[1] : String(value);
    }

    function formatDuration(value, empty = "--:--") {
        const seconds = Number(value);
        if (!Number.isFinite(seconds) || seconds < 0) return empty;
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const remainder = Math.floor(seconds % 60);
        return hours > 0
            ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
            : `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
    }

    function formatNumber(value, suffix = "") {
        if (value === null || value === undefined || value === "") return "-";
        return `${value}${suffix}`;
    }

    function formatDecimal(value, digits = 2, suffix = "") {
        const number = Number(value);
        if (!Number.isFinite(number)) return "-";
        return `${number.toFixed(digits)}${suffix}`;
    }

    function formatBytes(value) {
        const bytes = Number(value || 0);
        if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} kB`;
        return `${bytes} B`;
    }

    function normalizeState(mission, rf) {
        if (rf && rf.active) return String(rf.state || "RECORDING").toUpperCase();
        return String((mission && (mission.state || mission.phase)) || "STANDBY").toUpperCase();
    }

    function updateStateBadge(state) {
        const badge = document.getElementById("briefing-state");
        if (!badge) return;
        badge.textContent = state;
        badge.className = `live-mission-state state-${state.toLowerCase().replaceAll(" ", "-")}`;
    }

    function calculateProgress(mission, rf) {
        if (rf && rf.active && Number(rf.timeout_seconds) > 0) {
            return Math.max(0, Math.min(100, Math.round((Number(rf.elapsed_seconds || 0) / Number(rf.timeout_seconds)) * 100)));
        }
        return Math.max(0, Math.min(100, Number((mission && mission.progress) || 0)));
    }

    function setPipelineStep(name, state) {
        const step = document.querySelector(`[data-pipeline-step="${name}"]`);
        if (!step) return;
        const normalized = PIPELINE_LABELS[state] ? state : "waiting";
        step.className = `pipeline-step is-${normalized}`;
        const status = step.querySelector("small");
        if (status) status.textContent = PIPELINE_LABELS[normalized];
    }

    function decoderTelemetrySeen(rf) {
        const viterbi = String((rf && rf.viterbi) || "UNKNOWN").toUpperCase();
        const deframer = String((rf && rf.deframer) || "UNKNOWN").toUpperCase();
        return Number((rf && rf.frames) || 0) > 0
            || Number((rf && rf.cadu_bytes) || 0) > 0
            || viterbi !== "UNKNOWN"
            || deframer !== "UNKNOWN";
    }

    function derivePipeline(mission, rf) {
        const state = normalizeState(mission, rf);
        const job = mission.active_job || null;
        const hasLiveMission = Boolean(job || (rf && rf.active));
        const result = String((rf && rf.result) || (job && job.result) || "").toUpperCase();
        const failed = ["FAILED", "NO SIGNAL", "NO SYNC", "NO IMAGES", "CANCELLED", "ERROR"].includes(result)
            || state === "ERROR"
            || state === "FAILED";
        const images = Number((rf && rf.image_count) ?? (job && job.image_count) ?? 0);
        const decoderSeen = decoderTelemetrySeen(rf)
            || Number((job && job.frames) || 0) > 0
            || Number((job && job.cadu_bytes) || 0) > 0;

        const statuses = Object.fromEntries(PIPELINE_STEPS.map((name) => [name, "waiting"]));
        let currentStage = "Wachten op AOS";

        if (!hasLiveMission) return { statuses, currentStage };

        switch (state) {
        case "WAIT FOR PASS":
        case "READY":
        case "STANDBY":
            currentStage = "Wachten op AOS";
            break;
        case "LOCK RECEIVER":
            statuses.receiver = "active";
            currentStage = "Receiver voorbereiden en locken";
            break;
        case "RECORDING":
            statuses.receiver = "complete";
            statuses.recording = "active";
            if (decoderSeen) statuses.decoder = "active";
            currentStage = decoderSeen ? "Opnemen en live decoderen" : "Satellietsignaal opnemen";
            break;
        case "DECODING":
            statuses.receiver = "complete";
            statuses.recording = "complete";
            statuses.decoder = "active";
            currentStage = "Opname decoderen";
            break;
        case "PROCESSING":
            statuses.receiver = "complete";
            statuses.recording = "complete";
            statuses.decoder = "complete";
            statuses.processing = "active";
            statuses.images = images > 0 ? "complete" : "active";
            currentStage = images > 0 ? "Afbeeldingen verwerken" : "Producten genereren";
            break;
        case "ARCHIVING":
            statuses.receiver = "complete";
            statuses.recording = "complete";
            statuses.decoder = decoderSeen || images > 0 ? "complete" : "waiting";
            statuses.processing = "complete";
            statuses.images = images > 0 ? "complete" : "waiting";
            statuses.archive = "active";
            currentStage = "Missie-output archiveren";
            break;
        default:
            currentStage = String(state).toLowerCase().replaceAll("_", " ");
            currentStage = currentStage.charAt(0).toUpperCase() + currentStage.slice(1);
        }

        if (failed) {
            if (state === "LOCK RECEIVER") statuses.receiver = "error";
            else if (state === "RECORDING") statuses.recording = "error";
            else if (!decoderSeen && images === 0) statuses.decoder = "error";
            else if (images === 0) statuses.images = "error";
            else statuses.archive = "error";
            currentStage = result ? `Missie gestopt: ${result}` : "Pipelinefout";
        }

        return { statuses, currentStage };
    }

    function updatePipeline(mission, rf) {
        const pipeline = derivePipeline(mission, rf);
        for (const name of PIPELINE_STEPS) setPipelineStep(name, pipeline.statuses[name]);
        setText("briefing-current-stage", pipeline.currentStage);
    }

    function setImageStatus(status) {
        const badge = document.getElementById("briefing-image-status");
        if (!badge) return;
        const normalized = IMAGE_STATUS_LABELS[status] ? status : "waiting";
        badge.textContent = IMAGE_STATUS_LABELS[normalized];
        badge.className = `live-image-status is-${normalized}`;
    }

    function updateImagePreview(capture, relevant) {
        const image = document.getElementById("briefing-image-preview");
        const empty = document.getElementById("briefing-image-empty");
        if (!image || !empty) return;

        if (!capture || !relevant) {
            image.classList.add("hidden");
            image.removeAttribute("src");
            empty.classList.remove("hidden");
            empty.textContent = "Nog geen live product";
            lastImageKey = "";
            return;
        }

        const key = `${capture.relative_path || capture.filename}-${capture.modified}-${capture.size_kb}`;
        if (key !== lastImageKey) {
            image.src = `${capture.url}?t=${capture.age_seconds || 0}-${Date.now()}`;
            lastImageKey = key;
        }
        empty.classList.add("hidden");
        image.classList.remove("hidden");
    }

    function deriveImageStatus(mission, rf, capture, relevantCapture) {
        const state = normalizeState(mission, rf);
        const job = mission.active_job || null;
        const result = String((rf && rf.result) || (job && job.result) || "").toUpperCase();
        if (["FAILED", "ERROR"].includes(result) || ["FAILED", "ERROR"].includes(state)) return "error";
        if (state === "PROCESSING") return relevantCapture ? "writing" : "building";
        if (state === "DECODING" || (state === "RECORDING" && decoderTelemetrySeen(rf))) return "decoding";
        if (state === "ARCHIVING" || (relevantCapture && ["READY", "STANDBY"].includes(state))) return "complete";
        if (relevantCapture && capture && capture.live) return "writing";
        return "waiting";
    }

    function updateImageProcessing(mission, rf, captureData) {
        const job = mission.active_job || null;
        const capture = captureData && captureData.available ? captureData.latest_capture : null;
        const hasActiveMission = Boolean(job || (rf && rf.active));
        const relevantCapture = Boolean(capture && (!hasActiveMission || capture.live));
        const telemetryCount = Number((rf && rf.image_count) ?? (job && job.image_count) ?? 0);
        const products = Math.max(telemetryCount, relevantCapture ? 1 : 0);

        setImageStatus(deriveImageStatus(mission, rf, capture, relevantCapture));
        setText("briefing-image-products", products);
        setText("briefing-image-product", relevantCapture ? (capture.product || capture.filename || "-") : "-");
        setText("briefing-image-resolution", relevantCapture ? (capture.resolution || "-") : "-");
        setText("briefing-image-updated", relevantCapture ? onlyTime(capture.modified) : "-");
        updateImagePreview(capture, relevantCapture);
    }

    function resultClass(value) {
        return String(value || "waiting").toLowerCase().replaceAll(" ", "-");
    }

    function updateOperationSummary(summary, receiverManager) {
        const data = summary || {};
        const result = String(data.result || data.status || (data.active ? "ACTIVE" : "WACHTEN")).toUpperCase();
        const detail = data.detail || (data.active ? "Missie is actief." : "Nog geen afgeronde missie.");
        const reservation = receiverManager && receiverManager.reservation;
        const receiverStatus = String(
            data.receiver_status
            || (reservation && reservation.status)
            || (receiverManager && receiverManager.last_release && receiverManager.last_release.status)
            || "AVAILABLE"
        ).toUpperCase();

        setText("briefing-result", result);
        setText("briefing-receiver-status", receiverStatus);
        setText("briefing-result-detail", detail);

        const resultElement = document.getElementById("briefing-result");
        if (resultElement) resultElement.className = `operation-result is-${resultClass(result)}`;
        const receiverElement = document.getElementById("briefing-receiver-status");
        if (receiverElement) receiverElement.className = `receiver-operation-status is-${resultClass(receiverStatus)}`;
    }

    function updateDashboard(status, rf, captureData, summary = null, receiverManager = null) {
        const mission = status.mission || {};
        const job = mission.active_job || null;
        const pass = mission.next_pass || status.next_pass || null;
        const activeRf = rf && (rf.active || rf.state === "COMPLETE") ? rf : {};
        const state = normalizeState(mission, rf);
        const progress = calculateProgress(mission, rf);

        const satellite = (job && job.satellite) || activeRf.satellite || (pass && pass.name) || "Geen actieve missie";
        const mode = (job && job.mode) || (pass && pass.mode) || "-";
        const receiver = (job && job.receiver) || activeRf.receiver || "-";
        const frequencyMhz = (job && job.frequency_mhz)
            || (activeRf.frequency_hz ? Number(activeRf.frequency_hz) / 1_000_000 : null)
            || (pass && pass.frequency_mhz);
        const pipeline = (job && job.pipeline) || (pass && pass.pipeline) || "-";

        setText("briefing-name", satellite);
        setText("briefing-mode", mode);
        setText("briefing-receiver", receiver);
        setText("briefing-frequency", frequencyMhz == null ? "-" : `${Number(frequencyMhz).toFixed(3)} MHz`);
        setText("briefing-pipeline", pipeline);
        updateStateBadge(state);

        setText("briefing-elapsed", formatDuration(activeRf.elapsed_seconds, "00:00"));
        setText("briefing-remaining", formatDuration(activeRf.remaining_seconds));
        setText("briefing-progress-text", `${progress}%`);
        const progressBar = document.getElementById("briefing-progress-bar");
        if (progressBar) progressBar.style.width = `${progress}%`;

        setText("briefing-frames", activeRf.frames ?? (job && job.frames) ?? 0);
        setText("briefing-cadu", formatBytes(activeRf.cadu_bytes ?? (job && job.cadu_bytes) ?? 0));
        setText("briefing-peak-snr", formatNumber(activeRf.peak_snr_db ?? (job && job.peak_snr_db), " dB"));
        setText("briefing-images", activeRf.image_count ?? (job && job.image_count) ?? 0);
        setText("briefing-snr", formatDecimal(activeRf.snr_db ?? (summary && summary.snr_db), 2, " dB"));
        setText("briefing-ber", formatDecimal(activeRf.ber ?? (summary && summary.ber), 5));
        setText("briefing-viterbi", String(activeRf.viterbi ?? (summary && summary.viterbi) ?? "UNKNOWN").toUpperCase());
        setText("briefing-deframer", String(activeRf.deframer ?? (summary && summary.deframer) ?? "UNKNOWN").toUpperCase());
        updateOperationSummary(summary, receiverManager);

        setText("briefing-start", pass ? onlyTime(pass.start) : "-");
        setText("briefing-maximum", pass ? onlyTime(pass.maximum) : "-");
        setText("briefing-end", pass ? onlyTime(pass.end) : "-");
        setText("briefing-elevation", pass && pass.max_elevation !== undefined ? `${pass.max_elevation}°` : "-");
        setText("briefing-azimuth", pass && pass.azimuth !== undefined ? `${pass.azimuth}°` : "-");
        setText("briefing-samplerate", activeRf.sample_rate ? `${Number(activeRf.sample_rate).toLocaleString("nl-NL")} S/s` : "-");

        let gain = "-";
        if (activeRf.gain_mode) {
            gain = String(activeRf.gain_mode).toUpperCase() === "AUTO"
                ? "AUTO"
                : activeRf.gain_db == null ? String(activeRf.gain_mode) : `${activeRf.gain_db} dB`;
        }
        setText("briefing-gain", gain);

        const locked = state === "LOCK RECEIVER" || state === "RECORDING" || Boolean(rf && rf.active);
        setText("briefing-lock", locked ? "LOCKED" : "VRIJ");
        const lockElement = document.getElementById("briefing-lock");
        if (lockElement) lockElement.className = locked ? "live-lock locked" : "live-lock";

        updatePipeline(mission, rf || {});
        updateImageProcessing(mission, rf || {}, captureData || {});
    }

    async function refresh() {
        try {
            const [operations, captureData] = await Promise.all([
                getJson("/api/mission-operations"),
                getJson("/api/capture-status").catch(() => ({ available: false, latest_capture: null })),
            ]);
            const status = {
                mission: operations.mission || {},
                scheduler: operations.scheduler || {},
                assignments: {},
                next_pass: (operations.scheduler || {}).next_pass || null,
            };
            updateDashboard(
                status,
                operations.live_rf || {},
                captureData,
                operations.summary || null,
                operations.receiver_manager || null,
            );
        } catch (error) {
            console.log("Live Mission Dashboard update mislukt:", error.message);
            updateStateBadge("ERROR");
            setText("briefing-current-stage", "Telemetrie niet beschikbaar");
            setImageStatus("error");
        }
    }

    refresh();
    setInterval(refresh, POLL_MS);
})();
