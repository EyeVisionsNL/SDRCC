import {setText, formatCountdown} from "./utils.js";

let nextPassEpoch = null;
let serverOffsetSeconds = 0;

export function updateServerOffset(serverEpoch) {
    const browserNow = Math.floor(Date.now() / 1000);
    serverOffsetSeconds = serverEpoch - browserNow;
}

export function updateMissionEngine(mission) {
    if (!mission) return;

    setText("mission-phase", mission.phase);
    setText("mission-detail", mission.detail);

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

        setText("next-name", "Geen passage");
        setText("next-start", "-");
        setText("next-maximum", "-");
        setText("next-end", "-");
        setText("next-elevation", "-");
        setText("next-azimuth", "-");
        setText("next-frequency", "-");
        setText("next-mode", "-");
        setText("next-pipeline", "-");
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
    const remaining = nextPassEpoch - estimatedServerNow;

    setText("next-countdown", formatCountdown(remaining));
}
