export function updateServices(data) {
    setServiceState("ais", data.ais || {});
    setServiceState("adsb", data.adsb || {});
    setServiceState("ais-control", data.ais_control || {});
}

function lifecycleState(service) {
    if (service && service.lifecycle_state) {
        return String(service.lifecycle_state).trim().toUpperCase();
    }
    return service && service.active ? "RUNNING" : "STOPPED";
}

function stateTone(state) {
    if (state === "RUNNING") return "is-running";
    if (state === "STOPPED") return "is-stopped";
    if (state === "STARTING") return "is-starting";
    if (state === "PARTIAL") return "is-partial";
    return "is-attention";
}

function setServiceState(pluginId, service) {
    const state = lifecycleState(service);
    const tone = stateTone(state);
    const cardId = `system-service-${pluginId}`;
    const stateId = `${pluginId}-status-radio`;
    const card = document.getElementById(cardId);
    const stateBadge = document.getElementById(stateId);
    const headerBadge = document.getElementById(`${pluginId}-status`);
    const detail = document.getElementById(`${pluginId}-service-detail`);

    if (card) {
        card.classList.remove(
            "is-loading",
            "is-running",
            "is-stopped",
            "is-starting",
            "is-partial",
            "is-attention"
        );
        card.classList.add(tone);
    }
    if (stateBadge) {
        stateBadge.textContent = state;
        stateBadge.className = `system-service-state ${tone}`;
    }
    if (headerBadge) {
        headerBadge.textContent = state;
        headerBadge.className = ["STARTING", "PARTIAL"].includes(state)
            ? "warn"
            : state === "RUNNING" ? "ok" : "bad";
    }
    if (detail) {
        detail.textContent = service.detail || "Service status unavailable.";
    }
}

export function updateServiceButtons(data) {
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

    setPair("start_ais", "stop_ais", data.ais || {});
    setPair("start_adsb", "stop_adsb", data.adsb || {});
    setPair(
        "start_ais_control",
        "stop_ais_control",
        data.ais_control || {}
    );
    updateSchedulerButtons(data.scheduler);
}

function setPair(startAction, stopAction, service) {
    const startButton = document.querySelector(
        `[data-action="${startAction}"]`
    );

    const stopButton = document.querySelector(
        `[data-action="${stopAction}"]`
    );

    if (!startButton || !stopButton) return;

    const state = lifecycleState(service);
    const canStart = service.can_start !== undefined
        ? Boolean(service.can_start)
        : state === "STOPPED";
    const canStop = service.can_stop !== undefined
        ? Boolean(service.can_stop)
        : state !== "STOPPED";

    if (!canStart) {
        startButton.disabled = true;
        startButton.classList.add("disabled");
    } else {
        startButton.classList.add("running");
    }
    if (!canStop) {
        stopButton.disabled = true;
        stopButton.classList.add("disabled");
    } else {
        stopButton.classList.add("running");
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
