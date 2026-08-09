(() => {
    "use strict";

    const endpoint = "/api/traffic-voice";
    let refreshTimer = null;

    function text(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value ?? "-";
    }

    function receiverLabel(receiver) {
        if (!receiver || typeof receiver !== "object") return "Unassigned";
        const name = receiver.name || receiver.runtime_id || receiver.canonical_id || "Receiver";
        const serial = receiver.serial ? ` · ${receiver.serial}` : "";
        return `${name}${serial}`;
    }

    function displayToken(value) {
        return String(value || "-")
            .replaceAll("_", " ")
            .replace(/\b\w/g, letter => letter.toUpperCase());
    }

    function renderMode(mode) {
        const card = document.querySelector(`[data-traffic-mode="${mode.id}"]`);
        if (!card) return;
        card.classList.toggle("is-selected", Boolean(mode.selected));
        const state = card.querySelector("[data-traffic-mode-state]");
        if (state) state.textContent = mode.selected ? "SELECTED MODE" : "AVAILABLE MODE";
        const modulation = card.querySelector("[data-traffic-mode-modulation]");
        const context = card.querySelector("[data-traffic-mode-context]");
        const receiver = card.querySelector("[data-traffic-mode-receiver]");
        const bank = card.querySelector("[data-traffic-mode-bank]");
        if (modulation) modulation.textContent = mode.modulation || "-";
        if (context) context.textContent = String(mode.context_plugin || "-").toUpperCase();
        if (receiver) receiver.textContent = receiverLabel(mode.derived_voice_receiver);
        if (bank) bank.textContent = displayToken(mode.channel_bank);
    }

    function render(payload) {
        const status = document.getElementById("traffic-voice-status");
        const assignmentBadge = document.getElementById("traffic-voice-assignment-state");
        const message = document.getElementById("traffic-voice-contract-message");
        const assignment = payload.assignment || {};
        const modes = Array.isArray(payload.modes) ? payload.modes : [];
        const selected = modes.find(mode => mode.selected) || {};

        if (status) {
            status.textContent = payload.ok ? "FOUNDATION READY" : "ATTENTION";
            status.classList.toggle("is-foundation", Boolean(payload.ok));
            status.classList.toggle("is-attention", !payload.ok);
        }

        modes.forEach(renderMode);
        text("traffic-voice-selected-mode", selected.label || displayToken(payload.selected_mode));
        text("traffic-voice-voice-receiver", receiverLabel(assignment.voice_receiver));
        text("traffic-voice-context-receiver", receiverLabel(assignment.context_receiver));
        text("traffic-voice-receiver-policy", displayToken(payload.receiver_policy));
        text("traffic-voice-backend", displayToken((payload.backend || {}).name));
        text("traffic-voice-speaker-label", displayToken((payload.speaker_context || {}).label));
        text("traffic-voice-execution", payload.execution_enabled ? "EXECUTION ENABLED" : "EXECUTION DISABLED");

        const assignmentValid = Boolean(assignment.separated && assignment.matches_policy);
        if (assignmentBadge) {
            assignmentBadge.textContent = assignmentValid ? "ASSIGNMENT VALID" : "ASSIGNMENT ATTENTION";
            assignmentBadge.classList.toggle("is-valid", assignmentValid);
            assignmentBadge.classList.toggle("is-attention", !assignmentValid);
        }

        if (message) {
            const errors = ((payload.validation || {}).errors || []).filter(Boolean);
            message.textContent = payload.ok
                ? "Configuration, receiver separation and non-execution protections are valid."
                : errors.join(" · ") || "Traffic Voice foundation validation failed.";
            message.classList.toggle("is-error", !payload.ok);
        }
    }

    function renderError(error) {
        const status = document.getElementById("traffic-voice-status");
        const message = document.getElementById("traffic-voice-contract-message");
        if (status) {
            status.textContent = "UNAVAILABLE";
            status.classList.remove("is-foundation");
            status.classList.add("is-attention");
        }
        if (message) {
            message.textContent = `Foundation API unavailable: ${error.message}`;
            message.classList.add("is-error");
        }
    }

    async function refresh() {
        if (document.hidden) return;
        const page = document.getElementById("tab-traffic-voice");
        if (!page || !page.classList.contains("active")) return;
        try {
            const response = await fetch(endpoint, {cache: "no-store"});
            const payload = await response.json();
            if (!response.ok && !payload.validation) {
                throw new Error(payload.error || `HTTP ${response.status}`);
            }
            render(payload);
        } catch (error) {
            renderError(error);
        }
    }

    function initialize() {
        document.querySelector('.tab-button[data-tab="traffic-voice"]')
            ?.addEventListener("click", () => window.setTimeout(refresh, 0));
        document.addEventListener("visibilitychange", refresh);
        refreshTimer = window.setInterval(refresh, 10000);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
        initialize();
    }

    window.addEventListener("beforeunload", () => {
        if (refreshTimer !== null) window.clearInterval(refreshTimer);
    }, {once: true});
})();
