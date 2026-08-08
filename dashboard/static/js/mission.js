import {setText, formatCountdown} from "./utils.js";

const RECEIVERS = ["SDR1", "SDR2"];
const nextPassEpoch = {SDR1: null, SDR2: null};
const passEndEpoch = {SDR1: null, SDR2: null};
const passStatus = {SDR1: "", SDR2: ""};
const visiblePass = {SDR1: null, SDR2: null};
let serverOffsetSeconds = 0;
let missionQueueAuthoritative = false;
let dashboardSnapshot = {mission: {}, iss_voice: {}};
let operationsSnapshot = null;

const ids = {
    SDR1: {
        card: "mission-sdr1-card",
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
        card: "mission-sdr2-card",
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
        const normalized = String(value || "").trim().toUpperCase().replaceAll("_", "").replaceAll(" ", "");
        if (normalized.includes("SDR1") || normalized.includes("RECEIVER01") || normalized === "1") return "SDR1";
        if (normalized.includes("SDR2") || normalized.includes("RECEIVER02") || normalized === "2") return "SDR2";
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
        pass?.active_receiver,
        pass?.reserved_receiver,
        pass?.configured_receiver,
        pass?.receiver,
        pass?.receiver_name,
        pass?.device
    );
}

function estimatedServerNow() {
    return Math.floor(Date.now() / 1000) + serverOffsetSeconds;
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
        setText("last-mission-result", "NO RESULT");
        setText("last-mission-satellite", "-");
        setText("last-mission-snr", "-");
        setText("last-mission-frames", "-");
        setText("last-mission-images", "-");
        setText("last-mission-duration", "-");
        setText("last-mission-ended", "-");
        setText("last-mission-detail", "No mission result available yet.");
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

function runtimeForReceiver(receiver) {
    const summary = operationsSnapshot?.summary;
    if (summary?.active && normalizeReceiver(summary.receiver, summary.receiver_id) === receiver) {
        return {
            active: true,
            satellite: summary.satellite || summary.name || "",
            phase: summary.status || operationsSnapshot?.state || "ACTIVE",
            detail: summary.detail || "Mission active",
            progress: summary.progress,
            remainingSeconds: summary.remaining_seconds,
            source: summary.mission_type || summary.plugin_id || "mission_operations"
        };
    }

    const iss = dashboardSnapshot.iss_voice || {};
    if (iss.active && normalizeReceiver(iss.receiver_id, iss.receiver) === receiver) {
        return {
            active: true,
            satellite: iss.satellite || "ISS (ZARYA)",
            phase: iss.phase || "ACTIVE",
            detail: iss.detail || "ISS Voice mission active",
            progress: iss.progress,
            remainingSeconds: iss.remaining_seconds,
            source: "iss_voice"
        };
    }

    const mission = dashboardSnapshot.mission || {};
    if (mission.active_job && missionReceiver(mission) === receiver) {
        return {
            active: true,
            satellite: mission.active_job.satellite || mission.active_job.name || mission.satellite || "",
            phase: mission.phase || mission.state || mission.active_job.status || "ACTIVE",
            detail: mission.detail || mission.active_job.detail || "Mission active",
            progress: mission.progress ?? mission.active_job.progress,
            remainingSeconds: null,
            source: "mission_engine"
        };
    }

    const pass = visiblePass[receiver];
    const activeStatus = ["IN PROGRESS", "ACTIVE", "RECORDING"].includes(
        String(pass?.status || "").toUpperCase()
    );
    if (activeStatus) {
        return {
            active: true,
            satellite: pass.name || pass.satellite || "",
            phase: pass.live_mission_status || "ACTIVE",
            detail: `${pass.name || "Mission"} active on ${receiver}`,
            progress: null,
            remainingSeconds: pass.end_epoch ? Math.max(0, Number(pass.end_epoch) - estimatedServerNow()) : null,
            source: "mission_queue"
        };
    }
    return null;
}

function geometryProgress(pass) {
    const start = Number(pass?.start_epoch);
    const end = Number(pass?.end_epoch);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
    return Math.max(0, Math.min(100, (estimatedServerNow() - start) * 100 / (end - start)));
}

function phaseTone(phase) {
    const normalized = String(phase || "").toUpperCase();
    if (normalized === "RECORDING") return "recording";
    if (["FAILED", "ERROR", "CANCELLED"].includes(normalized)) return "failed";
    if (["DECODING", "PROCESSING", "ARCHIVING", "DEMODULATING", "FINALIZING"].includes(normalized)) return "processing";
    return "active";
}

function satelliteTone(value) {
    const normalized = String(value || "").toUpperCase().replaceAll("_", " ").replaceAll("-", " ");
    if (normalized.includes("ISS")) return "is-iss";
    if (normalized.includes("M2 3") || normalized.includes("M2-3")) return "is-meteor-3";
    if (normalized.includes("M2 4") || normalized.includes("M2-4")) return "is-meteor-4";
    return "is-neutral";
}

function blockedCopy(pass) {
    const blocker = pass?.blocked_by_name || "another mission";
    const blockerReceiver = pass?.blocked_by_receiver || "another receiver";
    if (pass?.conflict_scope === "receiver") {
        return `${pass.receiver || "This receiver"} is already reserved by ${blocker}.`;
    }
    return `Mission Automation is busy with ${blocker} on ${blockerReceiver}.`;
}

function applyCardTone(receiver, tone) {
    const target = ids[receiver];
    const card = document.getElementById(target.card);
    const badge = document.getElementById(target.badge);
    const classes = ["is-ready", "is-next", "is-active", "is-recording", "is-processing", "is-blocked", "is-failed"];
    if (card) {
        card.classList.remove(...classes);
        card.classList.add(`is-${tone}`);
    }
    if (badge) {
        badge.classList.remove(...classes);
        badge.classList.add(`is-${tone}`);
    }
}

function applySatelliteTone(receiver, satellite) {
    const card = document.getElementById(ids[receiver].card);
    if (!card) return;
    card.classList.remove("is-meteor-3", "is-meteor-4", "is-iss", "is-neutral");
    card.classList.add(satelliteTone(satellite));
}

function renderMissionCard(receiver) {
    const target = ids[receiver];
    const runtime = runtimeForReceiver(receiver);
    const pass = visiblePass[receiver];
    const satellite = runtime?.satellite || pass?.name || pass?.satellite || "";
    let phase = "READY";
    let badge = "READY";
    let detail = pass ? "Receiver ready for the scheduled mission" : "No active mission";
    let progress = 0;
    let tone = pass ? "next" : "ready";

    if (runtime?.active) {
        phase = String(runtime.phase || "ACTIVE").toUpperCase();
        badge = phase;
        detail = runtime.detail || "Mission active";
        const passProgress = geometryProgress(pass);
        progress = Number.isFinite(passProgress) ? passProgress : Number(runtime.progress || 0);
        tone = phaseTone(phase);
    } else if (String(pass?.status || "").toUpperCase() === "BLOCKED") {
        const now = estimatedServerNow();
        const start = Number(pass.start_epoch || 0);
        const end = Number(pass.end_epoch || 0);
        const missedStart = start > 0 && now >= start && (!end || now < end);
        phase = missedStart ? "NOT STARTED" : "MISSION OVERLAP";
        badge = "BLOCKED";
        detail = missedStart
            ? `Not started because it overlaps another mission. ${blockedCopy(pass)}`
            : blockedCopy(pass);
        tone = "blocked";
    }

    setText(target.badge, badge);
    setText(target.phase, phase);
    setText(target.detail, detail);
    const bar = document.getElementById(target.progress);
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
    applyCardTone(receiver, tone);
    applySatelliteTone(receiver, satellite);
}

function renderMissionCards() {
    RECEIVERS.forEach(renderMissionCard);
}

export function updateMissionEngine(data) {
    if (!data) return;
    dashboardSnapshot = data.mission
        ? {mission: data.mission || {}, iss_voice: data.iss_voice || {}}
        : {mission: data, iss_voice: dashboardSnapshot.iss_voice || {}};
    const mission = dashboardSnapshot.mission;
    renderMissionCards();
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
    visiblePass[receiver] = null;
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
    visiblePass[receiver] = pass;
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

function applyCountdownTone(receiver, tone) {
    const target = ids[receiver];
    const label = document.getElementById(target.passLabel);
    const countdown = document.getElementById(target.nextCountdown);
    const classes = ["is-next", "is-active", "is-blocked"];
    for (const node of [label, countdown]) {
        if (!node) continue;
        node.classList.remove(...classes);
        node.classList.add(`is-${tone}`);
    }
}

export function updateCountdown() {
    const now = estimatedServerNow();
    RECEIVERS.forEach(receiver => {
        const epoch = nextPassEpoch[receiver];
        const endEpoch = passEndEpoch[receiver];
        const blocked = passStatus[receiver] === "BLOCKED";
        const geometryActive = Boolean(epoch && endEpoch && now >= epoch && now < endEpoch);
        const statusActive = ["IN PROGRESS", "ACTIVE", "RECORDING"].includes(passStatus[receiver]);

        if (blocked) {
            setText(ids[receiver].passLabel, geometryActive ? "NOT STARTED" : "MISSION OVERLAP");
            setText(ids[receiver].countdownLabel, geometryActive ? "Window closes" : "Starts in");
            setText(
                ids[receiver].nextCountdown,
                geometryActive && endEpoch
                    ? formatCountdown(endEpoch - now)
                    : epoch ? formatCountdown(epoch - now) : "-"
            );
            applyCountdownTone(receiver, "blocked");
            return;
        }
        if (geometryActive || statusActive) {
            setText(ids[receiver].passLabel, "ACTIVE PASS");
            setText(ids[receiver].countdownLabel, "Remaining");
            setText(ids[receiver].nextCountdown, endEpoch ? formatCountdown(endEpoch - now) : "NOW / ACTIVE");
            applyCountdownTone(receiver, "active");
            return;
        }
        setText(ids[receiver].passLabel, "NEXT PASS");
        setText(ids[receiver].countdownLabel, "Time to start");
        setText(ids[receiver].nextCountdown, epoch ? formatCountdown(epoch - now) : "-");
        applyCountdownTone(receiver, "next");
    });
    renderMissionCards();
}

function updateOperationsSnapshot(snapshot) {
    if (!snapshot || snapshot.loading) return;
    operationsSnapshot = snapshot;
    renderMissionCards();
}

if (window.MissionState?.subscribe) {
    window.MissionState.subscribe(updateOperationsSnapshot);
} else {
    window.addEventListener("sdrcc:mission-state", event => updateOperationsSnapshot(event.detail));
}
