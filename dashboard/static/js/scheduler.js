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

/* v0.18.0b - Automation Controller Status & Safe Override */
let automationControllerInitialized = false;
let automationControllerBusy = false;
let automationControllerData = null;

function setupAutomationController() {
    if (automationControllerInitialized) return;
    const dryRun = document.getElementById("automation-dry-run");
    const override = document.getElementById("automation-manual-override");
    const skip = document.getElementById("automation-skip-pass");
    if (!dryRun || !override || !skip) return;

    dryRun.addEventListener("click", () => sendControllerAction("dry_run", !Boolean(automationControllerData && automationControllerData.dry_run)));
    override.addEventListener("click", () => sendControllerAction("manual_override", !Boolean(automationControllerData && automationControllerData.manual_override)));
    skip.addEventListener("click", () => sendControllerAction("skip_next_pass"));

    automationControllerInitialized = true;
    refreshAutomationController();
    window.setInterval(refreshAutomationController, 2000);
}

async function refreshAutomationController() {
    try {
        const response = await fetch("/api/automation-controller", {cache: "no-store"});
        const payload = await response.json();
        if (!response.ok || payload.ok === false) throw new Error(payload.error || "Controller status unavailable");
        updateAutomationController(payload);
    } catch (error) {
        setText("automation-controller-state", "ERROR");
        setText("automation-controller-detail", String(error));
    }
}

async function sendControllerAction(action, enabled) {
    if (automationControllerBusy) return;
    automationControllerBusy = true;
    setControllerButtonsDisabled(true);
    setControllerMessage("Running action...", "");
    try {
        const body = {action};
        if (typeof enabled === "boolean") body.enabled = enabled;
        const response = await fetch("/api/automation-controller", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body),
        });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) throw new Error(payload.error || "Controlleractie mislukt");
        updateAutomationController(payload);
        setControllerMessage("Controller setting saved.", "ok");
    } catch (error) {
        setControllerMessage(String(error), "bad");
    } finally {
        automationControllerBusy = false;
        setControllerButtonsDisabled(false);
    }
}

function updateAutomationController(data) {
    automationControllerData = data || {};
    const state = String(data.status || data.mode || "IDLE").toUpperCase();
    const badge = document.getElementById("automation-controller-state");
    if (badge) {
        badge.textContent = state;
        badge.className = "automation-controller-state";
        if (["ERROR", "FAILED"].includes(state)) badge.classList.add("is-error");
        else if (data.dry_run || data.manual_override || data.pass_skipped || ["PAUSED", "SKIPPED", "MANUAL OVERRIDE"].includes(state)) badge.classList.add("is-safe");
        else if (!["MANUAL", "IDLE", "WAITING"].includes(state)) badge.classList.add("is-active");
    }

    const passData = data.target_pass || data.next_pass || null;
    setText("automation-controller-pass", passData ? (passData.name || "-") : "-");
    setText("automation-controller-countdown", passData && Number.isFinite(Number(passData.start_epoch))
        ? formatCountdown(Number(passData.start_epoch) - (Math.floor(Date.now() / 1000) + serverOffsetSeconds))
        : "T--:--:--");
    setText("automation-controller-next-action", data.next_action || "-");
    setText("automation-controller-detail", data.detail || "-");
    setText("automation-controller-safety", data.manual_override ? "Manual Override" : data.dry_run ? "Dry Run" : data.pass_skipped ? "Pass overgeslagen" : "Normal");

    const dryRun = document.getElementById("automation-dry-run");
    const override = document.getElementById("automation-manual-override");
    const skip = document.getElementById("automation-skip-pass");
    if (dryRun) {
        dryRun.textContent = `🧪 Dry Run ${data.dry_run ? "AAN" : "UIT"}`;
        dryRun.classList.toggle("is-on", Boolean(data.dry_run));
    }
    if (override) {
        override.textContent = `✋ Override ${data.manual_override ? "AAN" : "UIT"}`;
        override.classList.toggle("is-on", Boolean(data.manual_override));
    }
    if (skip) skip.disabled = automationControllerBusy || !data.next_pass || Boolean(data.pass_skipped);
}

function setControllerButtonsDisabled(disabled) {
    document.querySelectorAll(".automation-controller-button").forEach(button => { button.disabled = disabled; });
}

function setControllerMessage(message, stateClass) {
    const element = document.getElementById("automation-controller-message");
    if (!element) return;
    element.textContent = message;
    element.classList.remove("ok", "bad");
    if (stateClass) element.classList.add(stateClass);
}

setupAutomationController();

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
    const list = document.getElementById("mission-queue-list");
    if (!list) return;
    const queue = Array.isArray(payload.queue) ? payload.queue : [];
    setText("mission-queue-summary", `${queue.length} PASSAGES`);
    if (!queue.length) {
        list.innerHTML = '<div class="mission-queue-empty">No suitable passes scheduled.</div>';
        return;
    }
    list.innerHTML = queue.map(item => {
        const start = String(item.start || "").split(" ")[1] || "-";
        const skipAction = item.skipped ? "activate" : "skip";
        const skipLabel = item.skipped ? "↩" : "⏭";
        const rawStatus = String(item.status || "QUEUED").toUpperCase();
        const classes = rawStatus.toLowerCase().replaceAll(" ", "-");
        const satellite = item.name || "Unknown Satellite";
        const receiver = item.active_receiver || item.reserved_receiver || item.configured_receiver || item.receiver || "-";
        const frequency = Number(item.frequency_mhz);
        const frequencyLabel = Number.isFinite(frequency) ? frequency.toFixed(3) : "-";
        const elevation = Number(item.max_elevation);
        const elevationLabel = Number.isFinite(elevation) ? elevation.toFixed(1) : "-";
        const stateLabel = ["TARGET", "NEXT"].includes(rawStatus)
            ? "NEXT"
            : ["IN PROGRESS", "ACTIVE", "RECORDING"].includes(rawStatus)
                ? "ACTIVE"
                : item.skipped
                    ? "SKIPPED"
                    : "QUEUED";
        return `<div class="mission-queue-item is-${escapeQueue(classes)}">
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
            <div class="mission-queue-actions">
                <button type="button" data-queue-key="${escapeQueue(item.queue_key)}" data-queue-action="priority_down" title="Prioriteit lager">−</button>
                <button type="button" data-queue-key="${escapeQueue(item.queue_key)}" data-queue-action="priority_up" title="Prioriteit hoger">+</button>
                <button type="button" data-queue-key="${escapeQueue(item.queue_key)}" data-queue-action="${skipAction}" title="${item.skipped ? "Enable" : "Skip"}">${skipLabel}</button>
            </div>
        </div>`;
    }).join("");
    list.querySelectorAll("[data-queue-action]").forEach(button => {
        button.addEventListener("click", () => updateMissionQueueItem(button.dataset.queueKey, button.dataset.queueAction));
    });
    setQueueMessage(`${payload.conflicts || 0} conflict(en), ${payload.skipped || 0} overgeslagen.`, "");
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
        if (!response.ok || payload.ok === false) throw new Error(payload.error || "Queuewijziging mislukt");
        renderMissionQueue(payload);
        setQueueMessage("Mission Queue opgeslagen.", "ok");
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
