import {setText} from "./utils.js";

let startEpoch = null;
let serverOffsetSeconds = 0;

export function updateScheduler(data) {
    const scheduler = data && data.scheduler;
    const observer = scheduler && scheduler.observer;

    if (!scheduler || !observer) {
        setText("scheduler-mode", "-");
        setText("scheduler-observer-phase", "-");
        setText("scheduler-countdown", "T--:--:--");
        setText("scheduler-observer-detail", "-");
        setText("scheduler-preflight-at", "-");
        setText("scheduler-prepare-at", "-");
        setText("scheduler-lock-at", "-");
        startEpoch = null;
        return;
    }

    setText("scheduler-mode", scheduler.mode || "-");
    setText("scheduler-observer-phase", observer.phase || "-");
    setText("scheduler-observer-detail", observer.detail || "-");
    setText("scheduler-preflight-at", timeOnly(observer.preflight_at));
    setText("scheduler-prepare-at", timeOnly(observer.prepare_at));
    setText("scheduler-lock-at", timeOnly(observer.lock_at));

    const nextPass = scheduler.next_pass;
    startEpoch = nextPass ? Number(nextPass.start_epoch) : null;

    updateSchedulerCountdown();
}

export function updateSchedulerServerOffset(serverEpoch) {
    const parsed = Number(serverEpoch);

    if (!Number.isFinite(parsed)) {
        serverOffsetSeconds = 0;
        return;
    }

    serverOffsetSeconds = parsed - Math.floor(Date.now() / 1000);
}

export function updateSchedulerCountdown() {
    const element = document.getElementById("scheduler-countdown");
    if (!element) return;

    if (!Number.isFinite(startEpoch)) {
        element.textContent = "T--:--:--";
        return;
    }

    const nowEpoch = Math.floor(Date.now() / 1000) + serverOffsetSeconds;
    const difference = startEpoch - nowEpoch;

    element.textContent = formatCountdown(difference);
}

function formatCountdown(totalSeconds) {
    const prefix = totalSeconds >= 0 ? "T-" : "T+";
    let seconds = Math.abs(Math.trunc(totalSeconds));

    const days = Math.floor(seconds / 86400);
    seconds %= 86400;

    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;

    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;

    if (days > 0) {
        return `${prefix}${days}d ${pad(hours)}:${pad(minutes)}:${pad(remainingSeconds)}`;
    }

    return `${prefix}${pad(hours)}:${pad(minutes)}:${pad(remainingSeconds)}`;
}

function timeOnly(value) {
    if (!value || typeof value !== "string") return "-";

    const parts = value.split(" ");
    return parts.length > 1 ? parts[1] : value;
}

function pad(value) {
    return String(value).padStart(2, "0");
}
