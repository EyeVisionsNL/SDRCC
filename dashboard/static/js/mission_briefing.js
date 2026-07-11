(() => {
    const POLL_MS = 2000;

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

    function updateDashboard(status, rf) {
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
    }

    async function refresh() {
        try {
            const [status, rf] = await Promise.all([
                getJson("/api/status"),
                getJson("/api/live-rf").catch(() => ({})),
            ]);
            updateDashboard(status, rf);
        } catch (error) {
            console.log("Live Mission Dashboard update mislukt:", error.message);
            updateStateBadge("ERROR");
        }
    }

    refresh();
    setInterval(refresh, POLL_MS);
})();
