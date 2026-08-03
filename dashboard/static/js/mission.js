import {setText, formatCountdown} from "./utils.js";

const RECEIVERS = ["SDR1", "SDR2"];
const nextPassEpoch = {SDR1: null, SDR2: null};
const passEndEpoch = {SDR1: null, SDR2: null};
const passStatus = {SDR1: "", SDR2: ""};
let serverOffsetSeconds = 0;
let missionQueueAuthoritative = false;

const ids = {
    SDR1: {
        badge: "mission-sdr1-badge",
        phase: "mission-phase",
        detail: "mission-detail",
        progress: "mission-progress-bar",
        nextName: "next-name",
        nextStart: "next-start",
        nextCountdown: "next-countdown",
        countdownLabel: "mission-sdr1-countdown-label",
        passLabel: "mission-sdr1-pass-label",
        nextMaximum: "next-maximum",
        nextEnd: "next-end",
        nextElevation: "next-elevation",
        nextAzimuth: "next-azimuth",
        nextFrequency: "next-frequency",
        nextMode: "next-mode",
        nextPipeline: "next-pipeline"
    },
    SDR2: {
        badge: "mission-sdr2-badge",
        phase: "mission-sdr2-phase",
        detail: "mission-sdr2-detail",
        progress: "mission-sdr2-progress-bar",
        nextName: "mission-sdr2-next-name",
        nextStart: "mission-sdr2-next-start",
        nextCountdown: "mission-sdr2-next-countdown",
        countdownLabel: "mission-sdr2-countdown-label",
        passLabel: "mission-sdr2-pass-label",
        nextMaximum: "mission-sdr2-next-maximum",
        nextEnd: "mission-sdr2-next-end",
        nextElevation: "mission-sdr2-next-elevation",
        nextAzimuth: "mission-sdr2-next-azimuth",
        nextFrequency: "mission-sdr2-next-frequency",
        nextMode: "mission-sdr2-next-mode",
        nextPipeline: "mission-sdr2-next-pipeline"
    }
};

function normalizeReceiver(...values) {
    for (const value of values) {
        const normalized = String(value || "").trim().toUpperCase().replaceAll("_", "");
        if (normalized.includes("SDR1") || normalized === "1") return "SDR1";
        if (normalized.includes("SDR2") || normalized === "2") return "SDR2";
    }
    return "";
}

function missionReceiver(mission) {
    const activeJob = mission?.active_job;
    return normalizeReceiver(
        activeJob?.receiver_id,
        activeJob?.receiver,
        activeJob?.receiver_name,
        activeJob?.device,
        mission?.receiver_id,
        mission?.receiver
    );
}

function passReceiver(pass) {
    return normalizeReceiver(
        pass?.receiver_id,
        pass?.configured_receiver,
        pass?.receiver,
        pass?.receiver_name,
        pass?.device
    );
}

export function updateServerOffset(serverEpoch) {
    const browserNow = Math.floor(Date.now() / 1000);
    serverOffsetSeconds = Number(serverEpoch || browserNow) - browserNow;
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
    if (resultElement) resultElement.className = `last-mission-result ${resultClass(resultName)}`.trim();
}

function renderMissionCard(receiver, mission, activeReceiver) {
    const target = ids[receiver];
    const active = Boolean(mission?.active_job) && activeReceiver === receiver;
    const phase = active ? (mission.phase || mission.state || "ACTIVE") : "READY";
    const detail = active ? (mission.detail || "Mission active") : "No active mission";
    const progress = active ? Number(mission.progress || 0) : 0;

    setText(target.badge, String(phase).toUpperCase());
    setText(target.phase, phase);
    setText(target.detail, detail);
    const bar = document.getElementById(target.progress);
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
}

export function updateMissionEngine(mission) {
    if (!mission) return;
    const activeReceiver = missionReceiver(mission);
    RECEIVERS.forEach(receiver => renderMissionCard(receiver, mission, activeReceiver));
    updateLastMission(mission);

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

function clearNextPass(receiver) {
    const target = ids[receiver];
    nextPassEpoch[receiver] = null;
    passEndEpoch[receiver] = null;
    passStatus[receiver] = "";
    setText(target.passLabel, "NEXT PASS");
    setText(target.countdownLabel, "Time to start");
    setText(target.nextName, "No pass");
    [target.nextStart, target.nextCountdown, target.nextMaximum, target.nextEnd,
        target.nextElevation, target.nextAzimuth, target.nextFrequency,
        target.nextMode, target.nextPipeline].forEach(id => setText(id, "-"));
}

function renderNextPass(receiver, pass) {
    const target = ids[receiver];
    nextPassEpoch[receiver] = Number(pass.start_epoch || 0) || null;
    passEndEpoch[receiver] = Number(pass.end_epoch || 0) || null;
    passStatus[receiver] = String(pass.status || "QUEUED").toUpperCase();
    setText(target.nextName, pass.name || pass.satellite || "-");
    setText(target.nextStart, pass.start || "-");
    setText(target.nextMaximum, pass.maximum || "-");
    setText(target.nextEnd, pass.end || "-");
    setText(target.nextElevation, pass.max_elevation == null ? "-" : `${pass.max_elevation}°`);
    setText(target.nextAzimuth, pass.azimuth == null ? "-" : `${pass.azimuth}°`);
    setText(target.nextFrequency, pass.frequency_mhz == null ? "-" : `${pass.frequency_mhz} MHz`);
    setText(target.nextMode, pass.mode || "-");
    setText(target.nextPipeline, pass.pipeline || "-");
}

export function updateMissionQueueVisibility(payload) {
    const queue = Array.isArray(payload?.queue) ? payload.queue : [];
    const nextByReceiver = {};

    for (const item of queue) {
        if (!item || item.skipped) continue;
        const receiver = passReceiver(item);
        if (!receiver) continue;
        const active = ["IN PROGRESS", "ACTIVE", "RECORDING"].includes(String(item.status || "").toUpperCase());
        const current = nextByReceiver[receiver];
        const currentActive = current && ["IN PROGRESS", "ACTIVE", "RECORDING"].includes(String(current.status || "").toUpperCase());
        if (!current || (active && !currentActive)) nextByReceiver[receiver] = item;
    }

    RECEIVERS.forEach(receiver => {
        const pass = nextByReceiver[receiver];
        if (pass) renderNextPass(receiver, pass);
        else clearNextPass(receiver);
    });

    missionQueueAuthoritative = true;
    updateCountdown();
}

export function updateNextPass(data) {
    // Once Mission Queue has loaded, it is the authoritative source for
    // per-receiver mission visibility. Keep this compatibility path only
    // for the initial dashboard render before the queue response arrives.
    if (missionQueueAuthoritative) {
        updateCountdown();
        return;
    }

    RECEIVERS.forEach(clearNextPass);
    const pass = data?.next_pass;
    if (pass) {
        const receiver = passReceiver(pass)
            || normalizeReceiver(data?.assignments?.weather)
            || missionReceiver(data?.mission)
            || "SDR1";
        renderNextPass(receiver, pass);
    }
    updateCountdown();
}

export function updateCountdown() {
    const browserNow = Math.floor(Date.now() / 1000);
    const estimatedServerNow = browserNow + serverOffsetSeconds;
    RECEIVERS.forEach(receiver => {
        const epoch = nextPassEpoch[receiver];
        const endEpoch = passEndEpoch[receiver];
        const geometryActive = Boolean(epoch && endEpoch && estimatedServerNow >= epoch && estimatedServerNow < endEpoch);
        const statusActive = ["IN PROGRESS", "ACTIVE", "RECORDING"].includes(passStatus[receiver]);
        if (geometryActive || statusActive) {
            setText(ids[receiver].passLabel, "ACTIVE PASS");
            setText(ids[receiver].countdownLabel, "Remaining");
            setText(ids[receiver].nextCountdown, endEpoch ? formatCountdown(endEpoch - estimatedServerNow) : "NU / ACTIEF");
            return;
        }
        setText(ids[receiver].passLabel, "NEXT PASS");
        setText(ids[receiver].countdownLabel, "Time to start");
        setText(ids[receiver].nextCountdown, epoch ? formatCountdown(epoch - estimatedServerNow) : "-");
    });
}
