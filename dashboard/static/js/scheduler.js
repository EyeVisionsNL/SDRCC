import {setText} from "./utils.js";

let startEpoch = null;
let serverOffsetSeconds = 0;
let automationPolicyInitialized = false;
let automationPolicySaving = false;

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
        updateAutomationPolicy(null);
        startEpoch = null;
        return;
    }

    setText("scheduler-mode", scheduler.mode || "-");
    setText("scheduler-observer-phase", observer.phase || "-");
    setText("scheduler-observer-detail", observer.detail || "-");
    setText("scheduler-preflight-at", timeOnly(observer.preflight_at));
    setText("scheduler-prepare-at", timeOnly(observer.prepare_at));
    setText("scheduler-lock-at", timeOnly(observer.lock_at));

    updateAutomationPolicy(scheduler.automation || {
        mode: scheduler.mode,
        policy: null,
    });

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

function setupAutomationPolicy() {
    if (automationPolicyInitialized) return;

    const inputs = document.querySelectorAll("[data-policy-key]");
    if (!inputs.length) return;

    inputs.forEach(input => {
        input.addEventListener("change", async () => {
            if (automationPolicySaving) return;

            const key = input.dataset.policyKey;
            if (!key) return;

            const previousValue = !input.checked;
            setAutomationPolicySaving(true);
            setAutomationPolicyStatus("Instelling opslaan...", "");

            try {
                const response = await fetch("/api/automation-policy", {
                    method: "PUT",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        policy: {[key]: input.checked},
                    }),
                });
                const payload = await response.json();

                if (!response.ok || payload.ok === false) {
                    throw new Error(payload.error || "Opslaan mislukt");
                }

                updateAutomationPolicy(payload);
                setAutomationPolicyStatus("Automation Policy opgeslagen.", "ok");
            } catch (error) {
                input.checked = previousValue;
                setAutomationPolicyStatus(String(error), "bad");
                console.error(error);
            } finally {
                setAutomationPolicySaving(false);
            }
        });
    });

    automationPolicyInitialized = true;
}

function updateAutomationPolicy(automation) {
    setupAutomationPolicy();

    const mode = String((automation && automation.mode) || "MANUAL").toUpperCase();
    const policy = automation && automation.policy;
    const modeElement = document.getElementById("automation-policy-mode");

    if (modeElement) {
        modeElement.textContent = mode;
        modeElement.classList.toggle("is-auto", mode === "AUTO");
        modeElement.classList.toggle("is-paused", mode === "PAUSED");
    }

    if (!policy || typeof policy !== "object") {
        setAutomationPolicyStatus("Policy niet beschikbaar.", "bad");
        return;
    }

    document.querySelectorAll("[data-policy-key]").forEach(input => {
        const key = input.dataset.policyKey;
        if (Object.prototype.hasOwnProperty.call(policy, key)) {
            input.checked = Boolean(policy[key]);
        }
    });

    if (!automationPolicySaving) {
        const message = mode === "AUTO"
            ? "AUTO gebruikt alleen de ingeschakelde stappen."
            : mode === "PAUSED"
                ? "PAUSED start geen nieuwe automatische missie."
                : "MANUAL voert geen automatische stappen uit.";
        setAutomationPolicyStatus(message, "");
    }
}

function setAutomationPolicySaving(saving) {
    automationPolicySaving = saving;
    document.querySelectorAll(".automation-policy-switch").forEach(element => {
        element.classList.toggle("is-saving", saving);
    });
    document.querySelectorAll("[data-policy-key]").forEach(input => {
        input.disabled = saving;
    });
}

function setAutomationPolicyStatus(message, stateClass) {
    const element = document.getElementById("automation-policy-status");
    if (!element) return;
    element.textContent = message;
    element.classList.remove("ok", "bad");
    if (stateClass) element.classList.add(stateClass);
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
