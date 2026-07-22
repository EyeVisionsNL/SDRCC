import {setText, formatCountdown} from "./utils.js";

let nextPassEpoch = null;
let serverOffsetSeconds = 0;

export function updateServerOffset(serverEpoch) {
    const browserNow = Math.floor(Date.now() / 1000);
    serverOffsetSeconds = serverEpoch - browserNow;
}

function resultClass(result) {
    const normalized = String(result || "").toLowerCase().replaceAll(" ", "-");
    if (normalized === "success") return "success";
    if (normalized === "no-sync") return "no-sync";
    if (normalized === "no-signal") return "no-signal";
    if (normalized === "failed") return "failed";
    return "";
}

function updateLastMission(mission) {
    const result = mission.last_result || (mission.history || [])[0] || null;
    const resultElement = document.getElementById("last-mission-result");

    if (!result) {
        setText("last-mission-result", "GEEN RESULTAAT");
        setText("last-mission-satellite", "-");
        setText("last-mission-snr", "-");
        setText("last-mission-frames", "-");
        setText("last-mission-images", "-");
        setText("last-mission-duration", "-");
        setText("last-mission-ended", "-");
        setText("last-mission-detail", "Nog geen missie-uitkomst beschikbaar.");
        if (resultElement) resultElement.className = "last-mission-result";
        return;
    }

    const resultName = result.result || "-";
    setText("last-mission-result", resultName);
    setText("last-mission-satellite", result.satellite || "-");
    setText("last-mission-snr", result.peak_snr_db == null ? "-" : `${result.peak_snr_db} dB`);
    setText("last-mission-frames", result.frames ?? "-");
    setText("last-mission-images", result.image_count ?? "-");
    setText("last-mission-duration", result.duration_seconds == null ? "-" : `${result.duration_seconds} s`);
    setText("last-mission-ended", result.ended_at || "-");
    setText("last-mission-detail", result.detail || "-");

    if (resultElement) {
        resultElement.className = `last-mission-result ${resultClass(resultName)}`.trim();
    }
}

export function updateMissionEngine(mission) {
    if (!mission) return;

    setText("mission-phase", mission.phase);
    setText("mission-detail", mission.detail);
    updateLastMission(mission);

    const bar = document.getElementById("mission-progress-bar");
    if (bar) bar.style.width = `${mission.progress || 0}%`;

    const stepsBox = document.getElementById("mission-steps");
    if (!stepsBox) return;

    const steps = mission.steps || [];
    const activeIndex = mission.active_index ?? 0;
    stepsBox.innerHTML = "";

    steps.forEach((step, index) => {
        const div = document.createElement("div");
        div.className = index === activeIndex ? "mission-step active" : "mission-step";
        div.textContent = index === activeIndex ? `➤ ${step}` : `· ${step}`;
        stepsBox.appendChild(div);
    });
}

export function updateNextPass(data) {
    if (data.next_pass) {
        nextPassEpoch = data.next_pass.start_epoch;
        setText("next-name", data.next_pass.name);
        setText("next-start", data.next_pass.start);
        setText("next-maximum", data.next_pass.maximum);
        setText("next-end", data.next_pass.end);
        setText("next-elevation", data.next_pass.max_elevation + "°");
        setText("next-azimuth", data.next_pass.azimuth + "°");
        setText("next-frequency", data.next_pass.frequency_mhz + " MHz");
        setText("next-mode", data.next_pass.mode);
        setText("next-pipeline", data.next_pass.pipeline);
    } else {
        nextPassEpoch = null;
        ["next-name","next-start","next-maximum","next-end","next-elevation","next-azimuth","next-frequency","next-mode","next-pipeline"].forEach(id => setText(id, id === "next-name" ? "No pass" : "-"));
    }
    updateCountdown();
}

export function updateCountdown() {
    if (!nextPassEpoch) {
        setText("next-countdown", "-");
        return;
    }
    const browserNow = Math.floor(Date.now() / 1000);
    const estimatedServerNow = browserNow + serverOffsetSeconds;
    setText("next-countdown", formatCountdown(nextPassEpoch - estimatedServerNow));
}
