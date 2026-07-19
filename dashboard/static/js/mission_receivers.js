let lastSignature = null;

function text(value, fallback = "-") {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
}

function normaliseReceiver(receiverId, receiver) {
    const context = receiver?.context || {};
    const identity = context.identity || {};
    const lifecycle = context.lifecycle || {};
    const roles = context.roles || {};
    const hardware = context.hardware || {};
    const metrics = context.live_metrics || {};
    const reservation = context.reservation ?? receiver?.reservation ?? null;
    const activeMission = context.active_mission ?? receiver?.active_mission ?? null;

    return {
        id: receiverId,
        number: identity.number || receiver?.number || receiverId.toUpperCase(),
        name: identity.name || receiver?.name || receiverId.toUpperCase(),
        serial: identity.serial || receiver?.serial || null,
        state: lifecycle.state || receiver?.state || "UNKNOWN",
        health: lifecycle.health || receiver?.health || "UNKNOWN",
        detail: lifecycle.detail || receiver?.detail || "No runtime detail",
        role: roles.current || receiver?.current_role || "unassigned",
        requestedRole: roles.requested || null,
        frequencyHz: hardware.frequency_hz,
        gainDb: hardware.gain_db,
        mission: activeMission,
        reservation,
        metrics,
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

function card(receiver) {
    const article = document.createElement("section");
    article.className = `card receiver-mission-card ${stateClass(receiver.state)}`;
    article.dataset.receiverId = receiver.id;

    article.innerHTML = `
        <div class="receiver-mission-header">
            <div>
                <h2>${text(receiver.number)} Mission Status</h2>
                <p>${text(receiver.name)} · ${text(receiver.serial)}</p>
            </div>
            <div class="receiver-mission-badges">
                <span class="receiver-health ${stateClass(receiver.health)}">${text(receiver.health)}</span>
                <span class="receiver-state ${stateClass(receiver.state)}">${text(receiver.state)}</span>
            </div>
        </div>
        <div class="receiver-mission-primary">
            <span>Mission<strong>${text(missionLabel(receiver))}</strong></span>
            <span>Status<strong>${text(missionState(receiver))}</strong></span>
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

export async function updateMissionReceiverGrid() {
    const container = document.getElementById("mission-receiver-grid");
    if (!container) return;

    try {
        const response = await fetch("/api/runtime", {cache: "no-store"});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const runtime = await response.json();
        const receivers = Object.entries(runtime.receivers || {})
            .map(([receiverId, receiver]) => normaliseReceiver(receiverId, receiver))
            .sort((a, b) => a.number.localeCompare(b.number, undefined, {numeric: true}));

        const signature = JSON.stringify(receivers);
        if (signature === lastSignature) return;
        lastSignature = signature;
        container.replaceChildren();

        if (!receivers.length) {
            container.innerHTML = '<section class="card receiver-mission-card receiver-mission-empty"><h2>Receiver Mission Status</h2><p>No runtime receivers configured.</p></section>';
            return;
        }

        receivers.forEach((receiver) => container.appendChild(card(receiver)));
    } catch (error) {
        lastSignature = null;
        container.innerHTML = `<section class="card receiver-mission-card receiver-mission-error"><h2>Receiver Mission Status</h2><p>Runtime API unavailable: ${text(error.message)}</p></section>`;
    }
}
