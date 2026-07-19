let lastSignature = null;

function text(value, fallback = "-") {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
}

function normaliseReceiver(receiverId, receiver, operationsReceiver = null) {
    const context = receiver?.context || {};
    const identity = context.identity || {};
    const lifecycle = context.lifecycle || {};
    const roles = context.roles || {};
    const hardware = context.hardware || {};
    const metrics = context.live_metrics || {};
    const reservation = context.reservation ?? receiver?.reservation ?? null;
    const activeMission = context.active_mission ?? receiver?.active_mission ?? null;
    const operations = operationsReceiver?.operations || {};

    return {
        id: receiverId,
        number: identity.number || receiver?.number || operationsReceiver?.identity?.number || receiverId.toUpperCase(),
        name: identity.name || receiver?.name || operationsReceiver?.identity?.name || receiverId.toUpperCase(),
        serial: identity.serial || receiver?.serial || operationsReceiver?.identity?.serial || null,
        state: lifecycle.state || receiver?.state || "UNKNOWN",
        health: lifecycle.health || receiver?.health || "UNKNOWN",
        detail: lifecycle.detail || receiver?.detail || "No runtime detail",
        role: roles.current || receiver?.current_role || operationsReceiver?.identity?.role || "unassigned",
        requestedRole: roles.requested || null,
        frequencyHz: hardware.frequency_hz,
        gainDb: hardware.gain_db,
        mission: activeMission,
        reservation,
        metrics,
        available: operationsReceiver?.available === true,
        operationConsistency: operationsReceiver?.consistency || {ok: true, issues: []},
        operations,
    };
}

function stateClass(value) {
    return `state-${String(value || "unknown").toLowerCase().replaceAll("_", "-")}`;
}

function formatFrequency(value) {
    const frequency = Number(value);
    if (!Number.isFinite(frequency) || frequency <= 0) return "-";
    if (frequency >= 1_000_000_000) return `${(frequency / 1_000_000_000).toFixed(3)} GHz`;
    return `${(frequency / 1_000_000).toFixed(3)} MHz`;
}

function missionLabel(receiver) {
    const mission = receiver.mission || receiver.reservation;
    if (!mission) return "No Active Mission";
    return mission.target || mission.satellite || mission.mission_type || mission.mission_key || "Reserved Mission";
}

function missionState(receiver) {
    const mission = receiver.mission || receiver.reservation;
    if (!mission) return "STANDBY";
    return mission.status || (receiver.mission ? "ACTIVE" : "RESERVED");
}

function metric(value, suffix = "") {
    if (value === null || value === undefined || value === "") return "-";
    return `${value}${suffix}`;
}

function operationState(receiver) {
    if (!receiver.operationConsistency?.ok) {
        return {label: "CONTEXT ERROR", className: "state-error", detail: "Receiver context is inconsistent."};
    }
    if (receiver.operations.stop_mission?.allowed) {
        return {label: "MISSION ACTIVE", className: "state-active", detail: "Stop Mission is available."};
    }
    if (receiver.reservation) {
        return {label: "RESERVED", className: "state-reserved", detail: "Receiver is reserved for a mission."};
    }
    if (receiver.operations.record_now?.allowed) {
        return {label: "READY", className: "state-online", detail: "Receiver is ready for Record NOW."};
    }
    return {
        label: receiver.available ? "WAITING" : "UNAVAILABLE",
        className: receiver.available ? "state-restoring" : "state-offline",
        detail: receiver.operations.record_now?.detail || "Receiver is not available for an operation.",
    };
}

function operationItem(label, operation) {
    const allowed = operation?.allowed === true;
    const detail = operation?.detail || "No operation information available.";
    return `
        <span class="receiver-operation ${allowed ? "is-allowed" : "is-blocked"}" title="${text(detail)}">
            ${label}<strong>${allowed ? "AVAILABLE" : "BLOCKED"}</strong>
        </span>
    `;
}

function card(receiver) {
    const article = document.createElement("section");
    const operation = operationState(receiver);
    article.className = `card receiver-mission-card ${stateClass(receiver.state)}`;
    article.dataset.receiverId = receiver.id;

    article.innerHTML = `
        <div class="receiver-mission-header">
            <div>
                <h2>${text(receiver.number)} Mission Status</h2>
                <p>${text(receiver.name)} · ${text(receiver.serial)}</p>
            </div>
            <div class="receiver-mission-badges">
                <span class="receiver-operation-state ${operation.className}" title="${text(operation.detail)}">${operation.label}</span>
                <span class="receiver-health ${stateClass(receiver.health)}">${text(receiver.health)}</span>
                <span class="receiver-state ${stateClass(receiver.state)}">${text(receiver.state)}</span>
            </div>
        </div>
        <div class="receiver-mission-primary">
            <span>Mission<strong>${text(missionLabel(receiver))}</strong></span>
            <span>Status<strong>${text(missionState(receiver))}</strong></span>
        </div>
        <div class="receiver-operation-grid" aria-label="Receiver operation availability">
            ${operationItem("Record NOW", receiver.operations.record_now)}
            ${operationItem("Stop Mission", receiver.operations.stop_mission)}
            ${operationItem("Mission Next", receiver.operations.mission_next)}
        </div>
        <div class="receiver-mission-grid">
            <span>Role<strong>${text(receiver.role).toUpperCase()}</strong></span>
            <span>Requested<strong>${text(receiver.requestedRole).toUpperCase()}</strong></span>
            <span>Frequency<strong>${formatFrequency(receiver.frequencyHz)}</strong></span>
            <span>Gain<strong>${metric(receiver.gainDb, " dB")}</strong></span>
            <span>SNR<strong>${metric(receiver.metrics.snr_db, " dB")}</strong></span>
            <span>Peak SNR<strong>${metric(receiver.metrics.peak_snr_db, " dB")}</strong></span>
            <span>Frames<strong>${metric(receiver.metrics.frames)}</strong></span>
            <span>Images<strong>${metric(receiver.metrics.images)}</strong></span>
        </div>
        <p class="receiver-mission-detail">${text(receiver.detail)}</p>
    `;
    return article;
}

function updateGlobalOperationButtons(operationsData) {
    const receivers = Object.values(operationsData?.receivers || {});
    const anyRecordAllowed = receivers.some(receiver => receiver?.operations?.record_now?.allowed === true);
    const anyNextAllowed = receivers.some(receiver => receiver?.operations?.mission_next?.allowed === true);

    const recordButton = document.querySelector('[data-action="record"]');
    if (recordButton) {
        recordButton.disabled = !anyRecordAllowed;
        recordButton.title = anyRecordAllowed
            ? "At least one receiver is available for Record NOW."
            : "No receiver is currently available for Record NOW.";
    }

    const nextButton = document.querySelector('[data-mission-action="next"]');
    if (nextButton) {
        nextButton.disabled = !anyNextAllowed;
        nextButton.title = anyNextAllowed
            ? "Mission Next is available for the active receiver."
            : "Mission Next requires an active receiver mission.";
    }
}

async function getJson(url) {
    const response = await fetch(url, {cache: "no-store"});
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response.json();
}

export async function updateMissionReceiverGrid() {
    const container = document.getElementById("mission-receiver-grid");
    if (!container) return;

    try {
        const [runtime, operationsData] = await Promise.all([
            getJson("/api/runtime"),
            getJson("/api/receiver-operations"),
        ]);

        updateGlobalOperationButtons(operationsData);

        const operationsReceivers = operationsData.receivers || {};
        const receiverIds = new Set([
            ...Object.keys(runtime.receivers || {}),
            ...Object.keys(operationsReceivers),
        ]);

        const receivers = Array.from(receiverIds)
            .map(receiverId => normaliseReceiver(
                receiverId,
                runtime.receivers?.[receiverId] || {},
                operationsReceivers[receiverId] || null,
            ))
            .sort((a, b) => a.number.localeCompare(b.number, undefined, {numeric: true}));

        const signature = JSON.stringify({receivers, consistency: operationsData.consistency});
        if (signature === lastSignature) return;
        lastSignature = signature;
        container.replaceChildren();

        if (!receivers.length) {
            container.innerHTML = '<section class="card receiver-mission-card receiver-mission-empty"><h2>Receiver Mission Status</h2><p>No runtime receivers configured.</p></section>';
            return;
        }

        receivers.forEach(receiver => container.appendChild(card(receiver)));
    } catch (error) {
        lastSignature = null;
        container.innerHTML = `<section class="card receiver-mission-card receiver-mission-error"><h2>Receiver Mission Status</h2><p>Receiver Operations API unavailable: ${text(error.message)}</p></section>`;
    }
}
