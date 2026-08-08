import {setText} from "./utils.js";
import {updateMissionQueueVisibility} from "./mission.js?v=0.54.0n-r1";

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

function formatOverlap(totalSeconds) {
    let seconds = Math.max(0, Number(totalSeconds) || 0);
    const minutes = Math.floor(seconds / 60);
    seconds = Math.floor(seconds % 60);
    return minutes > 0 ? `${minutes}m ${pad(seconds)}s` : `${seconds}s`;
}

/* v0.19.0a - Mission Queue */
let missionQueueBusy = false;

async function refreshMissionQueue() {
    try {
        const response = await fetch("/api/mission-queue?limit=10&hours=48", {cache: "no-store"});
        const payload = await response.json();
        if (!response.ok || payload.ok === false) throw new Error(payload.error || "Mission Queue unavailable");
        renderMissionQueue(payload);
    } catch (error) {
        setQueueMessage(String(error), "bad");
    }
}

function renderMissionQueue(payload) {
    const queue = Array.isArray(payload.queue) ? payload.queue : [];

    // Mission Queue is the single source of truth for all per-receiver
    // next-mission views on Mission Control and Radio Control.
    updateMissionQueueVisibility(payload);
    window.dispatchEvent(new CustomEvent("sdrcc:mission-queue-updated", {detail: payload}));

    const list = document.getElementById("mission-queue-list");
    if (!list) return;
    setText("mission-queue-summary", `${queue.length} PASSAGES`);
    if (!queue.length) {
        list.innerHTML = '<div class="mission-queue-empty">No eligible passes scheduled.</div>';
        return;
    }
    list.innerHTML = queue.map(item => {
        const start = String(item.start || "").split(" ")[1] || "-";
        const skipAction = item.skipped ? "activate" : "skip";
        const skipLabel = item.skipped ? "↩" : "⏭";
        const rawStatus = String(item.status || "QUEUED").toUpperCase();
        const classes = rawStatus.toLowerCase().replaceAll(" ", "-");
        const satellite = item.name || "Unknown satellite";
        const receiver = item.active_receiver || item.reserved_receiver || item.configured_receiver || item.receiver || "-";
        const frequency = Number(item.frequency_mhz);
        const frequencyLabel = Number.isFinite(frequency) ? frequency.toFixed(3) : "-";
        const elevation = Number(item.max_elevation);
        const elevationLabel = Number.isFinite(elevation) ? elevation.toFixed(1) : "-";
        const liveStatus = String(item.live_mission_status || "").toUpperCase();
        const stateLabel = ["TARGET", "NEXT"].includes(rawStatus)
            ? "NEXT"
            : ["IN PROGRESS", "ACTIVE", "RECORDING"].includes(rawStatus)
                ? (liveStatus === "RECORDING" ? "RECORDING" : "ACTIVE")
                : item.skipped
                    ? "SKIPPED"
                    : rawStatus === "BLOCKED"
                        ? "BLOCKED"
                        : rawStatus === "CONFLICT"
                            ? "CONFLICT"
                            : "QUEUED";
        const warning = rawStatus === "BLOCKED"
            ? `ENGINE BUSY · ${item.blocked_by_name || "another mission"} on ${item.blocked_by_receiver || "another receiver"} · ${formatOverlap(item.overlap_seconds)} overlap`
            : item.overlap_warning
                ? `OVERLAP · ${Number(item.blocking?.length || 0)} mission${Number(item.blocking?.length || 0) === 1 ? "" : "s"} cannot start`
                : "";
        const itemClasses = [
            "mission-queue-item",
            `is-${classes}`,
            `is-${stateLabel.toLowerCase()}`,
            item.overlap_warning ? "has-overlap" : "",
        ].filter(Boolean).join(" ");
        return `<div class="${escapeQueue(itemClasses)}">
            <div class="mission-queue-topline">
                <time class="mission-queue-time">${escapeQueue(start.slice(0, 5))}</time>
                <span class="mission-queue-state is-${escapeQueue(stateLabel.toLowerCase())}">${escapeQueue(stateLabel)}</span>
            </div>
            <div class="mission-queue-title" title="${escapeQueue(satellite)}">
                <span class="mission-queue-satellite-icon" aria-hidden="true">🛰</span>
                <strong>${escapeQueue(satellite)}</strong>
            </div>
            <div class="mission-queue-details">
                <span>📡 ${escapeQueue(receiver)}</span>
                <span>▲ ${escapeQueue(elevationLabel)}°</span>
                <span class="mission-queue-frequency">${escapeQueue(frequencyLabel)} MHz</span>
            </div>
            ${warning ? `<div class="mission-queue-warning">⚠ ${escapeQueue(warning)}</div>` : ""}
            <div class="mission-queue-actions">
                <button type="button" data-queue-key="${escapeQueue(item.queue_key)}" data-queue-action="priority_down" title="Lower priority">−</button>
                <button type="button" data-queue-key="${escapeQueue(item.queue_key)}" data-queue-action="priority_up" title="Raise priority">+</button>
                <button type="button" data-queue-key="${escapeQueue(item.queue_key)}" data-queue-action="${skipAction}" title="${item.skipped ? "Activate" : "Skip"}">${skipLabel}</button>
            </div>
        </div>`;
    }).join("");
    list.querySelectorAll("[data-queue-action]").forEach(button => {
        button.addEventListener("click", () => updateMissionQueueItem(button.dataset.queueKey, button.dataset.queueAction));
    });
    setQueueMessage(`${payload.blocked || payload.conflicts || 0} blocked, ${payload.skipped || 0} skipped.`, "");
}

async function updateMissionQueueItem(queueKey, action) {
    if (missionQueueBusy) return;
    missionQueueBusy = true;
    document.querySelectorAll("[data-queue-action]").forEach(button => { button.disabled = true; });
    try {
        const response = await fetch("/api/mission-queue?limit=10&hours=48", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({queue_key: queueKey, action}),
        });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) throw new Error(payload.error || "Queue update failed");
        renderMissionQueue(payload);
        setQueueMessage("Mission Queue saved.", "ok");
    } catch (error) {
        setQueueMessage(String(error), "bad");
    } finally {
        missionQueueBusy = false;
    }
}

function setQueueMessage(message, stateClass) {
    const element = document.getElementById("mission-queue-message");
    if (!element) return;
    element.textContent = message;
    element.classList.remove("ok", "bad");
    if (stateClass) element.classList.add(stateClass);
}

function escapeQueue(value) {
    return String(value == null ? "-" : value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

refreshMissionQueue();
window.setInterval(refreshMissionQueue, 15000);
