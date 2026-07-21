(() => {
    const CAPTURE_POLL_MS = 2000;
    const PIPELINE_STEPS = ["receiver", "recording", "decoder", "processing", "images", "archive"];
    const PIPELINE_LABELS = {
        waiting: "WAITING",
        active: "ACTIEF",
        complete: "GEREED",
        error: "FOUT",
    };
    const IMAGE_STATUS_LABELS = {
        waiting: "WAITING",
        decoding: "DECODER ACTIEF",
        building: "AFBEELDING OPBOUWEN",
        writing: "AFBEELDING OPSLAAN",
        complete: "GEREED",
        error: "FOUT",
    };

    let lastImageKey = "";
    let latestCaptureData = { available: false, latest_capture: null };
    let captureRequestInProgress = false;
    let currentMissionSnapshot = null;

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
        let currentStage = window.SDRCC_UI_TEXT.t("waiting_aos");

        if (!hasLiveMission) return { statuses, currentStage };

        switch (state) {
        case "WAIT FOR PASS":
        case "READY":
        case "STANDBY":
            currentStage = window.SDRCC_UI_TEXT.t("waiting_aos");
            break;
        case "LOCK RECEIVER":
            statuses.receiver = "active";
            currentStage = "Receiver voorbereiden en locken";
            break;
        case "RECORDING":
            statuses.receiver = "complete";
            statuses.recording = "active";
            if (decoderSeen) statuses.decoder = "active";
            currentStage = decoderSeen ? "Recording and live decoding" : "Recording satellite signal";
            break;
        case "DECODING":
            statuses.receiver = "complete";
            statuses.recording = "complete";
            statuses.decoder = "active";
            currentStage = "Decoding recording";
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
            currentStage = window.SDRCC_UI_TEXT.t("archiving_output");
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
            currentStage = result ? window.SDRCC_UI_TEXT.tf("mission_stopped", {result}) : window.SDRCC_UI_TEXT.t("pipeline_error");
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
            empty.textContent = window.SDRCC_UI_TEXT.t("no_live_product");
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
        const result = String(data.result || data.status || (data.active ? "ACTIVE" : "WAITING")).toUpperCase();
        const detail = window.SDRCC_UI_TEXT.runtime(data.detail) || (data.active ? window.SDRCC_UI_TEXT.t("mission_active") : window.SDRCC_UI_TEXT.t("no_completed_mission"));
        const reservation = receiverManager && receiverManager.reservation;
        const receiverStatus = String(
            data.receiver_status
            || (reservation && reservation.status)
            || (receiverManager && receiverManager.last_release && receiverManager.last_release.status)
            || "AVAILABLE"
        ).toUpperCase();

        setText("briefing-result", window.SDRCC_UI_TEXT.runtime(result));
        setText("briefing-receiver-status", window.SDRCC_UI_TEXT.runtime(receiverStatus));
        setText("briefing-result-detail", detail);

        const resultElement = document.getElementById("briefing-result");
        if (resultElement) resultElement.className = `operation-result is-${resultClass(result)}`;
        const receiverElement = document.getElementById("briefing-receiver-status");
        if (receiverElement) receiverElement.className = `receiver-operation-status is-${resultClass(receiverStatus)}`;
    }


    function updateStopMissionButton(snapshot) {
        const button = document.getElementById("stop-mission-button");
        if (!button) return;

        const active = Boolean(snapshot && snapshot.active === true);
        const shouldDisable = !active;

        button.disabled = shouldDisable;
        button.className = active
            ? "control-button danger"
            : "control-button stop-mission-inactive";
        button.title = active
            ? "Stop active mission safely"
            : "There is no active mission";
    }

    async function stopMission() {
        const button = document.getElementById("stop-mission-button");
        if (!button || button.disabled) return;
        if (!window.confirm("Stop the current mission? The Scheduler will be set to MANUAL.")) return;

        button.disabled = true;
        button.textContent = "■ STOPPING...";
        try {
            const response = await fetch("/api/mission/stop", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: "{}",
            });
            const data = await response.json();
            if (!response.ok || data.ok === false) {
                throw new Error(data.message || data.error || `HTTP ${response.status}`);
            }
            const result = document.getElementById("control-result");
            if (result) result.textContent = window.SDRCC_UI_TEXT.runtime(data.message) || window.SDRCC_UI_TEXT.t("mission_stopped_plain");
        } catch (error) {
            const result = document.getElementById("control-result");
            if (result) result.textContent = `Stop Mission failed: ${error.message}`;
        } finally {
            button.textContent = "■ STOP MISSION";
            await window.MissionState.refresh({ force: true });
        }
    }

    function updateDashboard(status, rf, captureData, summary = null, receiverManager = null, snapshot = null) {
        const mission = status.mission || {};
        const isActive = Boolean(snapshot && snapshot.active === true);
        const job = isActive ? (mission.active_job || null) : null;
        const pass = mission.next_pass || status.next_pass || null;
        const activeRf = isActive && rf ? rf : {};
        const state = snapshot && snapshot.state
            ? String(snapshot.state).toUpperCase()
            : normalizeState(mission, activeRf);
        const progress = isActive ? calculateProgress(mission, activeRf) : 0;

        const satellite = (job && job.satellite) || activeRf.satellite || (pass && pass.name) || "No active mission";
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
        setText("briefing-snr", formatDecimal(isActive ? activeRf.snr_db : null, 2, " dB"));
        setText("briefing-ber", formatDecimal(isActive ? activeRf.ber : null, 5));
        setText("briefing-viterbi", String(isActive ? (activeRf.viterbi ?? "UNKNOWN") : "UNKNOWN").toUpperCase());
        setText("briefing-deframer", String(isActive ? (activeRf.deframer ?? "UNKNOWN") : "UNKNOWN").toUpperCase());
        updateOperationSummary(summary, receiverManager);
        updateStopMissionButton(snapshot);

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

        const locked = isActive && (state === "LOCK RECEIVER" || state === "RECORDING" || Boolean(activeRf.active));
        setText("briefing-lock", locked ? "LOCKED" : "FREE");
        const lockElement = document.getElementById("briefing-lock");
        if (lockElement) lockElement.className = locked ? "live-lock locked" : "live-lock";

        updatePipeline(mission, activeRf);
        updateImageProcessing(mission, activeRf, captureData || {});
    }

    function renderSnapshot(snapshot) {
        currentMissionSnapshot = snapshot;

        if (!snapshot || snapshot.loading) return;
        if (snapshot.error) {
            console.log("Live Mission Dashboard update failed:", snapshot.error);
            updateStateBadge("ERROR");
            setText("briefing-current-stage", window.SDRCC_UI_TEXT.t("telemetry_unavailable"));
            setImageStatus("error");
            updateStopMissionButton(snapshot);
            return;
        }

        const status = {
            mission: snapshot.mission || {},
            scheduler: snapshot.scheduler || {},
            assignments: {},
            next_pass: (snapshot.scheduler || {}).next_pass || null,
        };

        updateDashboard(
            status,
            snapshot.live_rf || {},
            latestCaptureData,
            snapshot.summary || null,
            snapshot.receiver_manager || null,
            snapshot,
        );
    }

    async function refreshCapture() {
        if (captureRequestInProgress) return;
        captureRequestInProgress = true;

        try {
            latestCaptureData = await getJson("/api/capture-status");
        } catch (error) {
            latestCaptureData = { available: false, latest_capture: null };
        } finally {
            captureRequestInProgress = false;
        }

        if (currentMissionSnapshot) renderSnapshot(currentMissionSnapshot);
    }

    const stopButton = document.getElementById("stop-mission-button");
    if (stopButton) stopButton.addEventListener("click", stopMission);

    if (!window.MissionState) {
        console.error("MissionState is niet geladen vóór mission_briefing.js");
        updateStateBadge("ERROR");
        setText("briefing-current-stage", window.SDRCC_UI_TEXT.t("mission_state_unavailable"));
        updateStopMissionButton({ active: false });
        return;
    }

    window.MissionState.subscribe(renderSnapshot);
    refreshCapture();
    window.setInterval(refreshCapture, CAPTURE_POLL_MS);
})();
