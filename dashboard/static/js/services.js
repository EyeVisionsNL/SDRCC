import {setStatus} from "./utils.js";

export function updateServices(data) {
    const aisActive = Boolean(data.ais && data.ais.active);
    const adsbActive = Boolean(data.adsb && data.adsb.active);

    setStatus("ais-status", aisActive);
    setStatus("ais-status-radio", aisActive);
    setStatus("adsb-status", adsbActive);
    setStatus("adsb-status-radio", adsbActive);

    setServiceState("system-service-ais", "ais-status-radio", aisActive);
    setServiceState("system-service-adsb", "adsb-status-radio", adsbActive);
}

function setServiceState(cardId, stateId, active) {
    const card = document.getElementById(cardId);
    const state = document.getElementById(stateId);
    const tone = active ? "is-running" : "is-stopped";

    if (card) {
        card.classList.remove("is-loading", "is-running", "is-stopped");
        card.classList.add(tone);
    }
    if (state) {
        state.className = `system-service-state ${tone}`;
    }
}

export function updateServiceButtons(data) {
    const aisActive = Boolean(data.ais && data.ais.active);
    const adsbActive = Boolean(data.adsb && data.adsb.active);

    document.querySelectorAll(".control-button").forEach(button => {
        button.disabled = false;
        button.classList.remove(
            "disabled",
            "running",
            "scheduler-auto-active",
            "scheduler-manual-active",
            "scheduler-paused-active"
        );
    });

    setPair("start_ais", "stop_ais", aisActive);
    setPair("start_adsb", "stop_adsb", adsbActive);
    updateSchedulerButtons(data.scheduler);
}

function setPair(startAction, stopAction, active) {
    const startButton = document.querySelector(
        `[data-action="${startAction}"]`
    );

    const stopButton = document.querySelector(
        `[data-action="${stopAction}"]`
    );

    if (!startButton || !stopButton) return;

    if (active) {
        startButton.disabled = true;
        startButton.classList.add("disabled");
        stopButton.classList.add("running");
    } else {
        stopButton.disabled = true;
        stopButton.classList.add("disabled");
        startButton.classList.add("running");
    }
}

function updateSchedulerButtons(scheduler) {
    if (!scheduler) return;

    const mode = String(scheduler.mode || "").toUpperCase();

    const autoButton = document.querySelector(
        '[data-action="scheduler_auto"]'
    );

    const manualButton = document.querySelector(
        '[data-action="scheduler_manual"]'
    );

    const pausedButton = document.querySelector(
        '[data-action="scheduler_paused"]'
    );

    if (mode === "AUTO" && autoButton) {
        autoButton.classList.add("scheduler-auto-active");
    }

    if (mode === "MANUAL" && manualButton) {
        manualButton.classList.add("scheduler-manual-active");
    }

    if (mode === "PAUSED" && pausedButton) {
        pausedButton.classList.add("scheduler-paused-active");
    }
}
