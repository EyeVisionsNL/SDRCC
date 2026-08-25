(() => {
    "use strict";

    const esc = (value) => String(value ?? "-").replace(
        /[&<>"']/g,
        (character) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        })[character]
    );

    const roleLabels = Object.freeze({
        weather: "Weather",
        ais: "AIS",
        adsb: "ADS-B",
        iss_voice: "ISS Voice",
        hf_monitor: "HF Monitor",
        live_rf: "Live RF",
        recording: "Recording",
    });

    function displayValue(value) {
        return value === null || value === undefined || value === "" ? "-" : String(value);
    }

    function displayList(value) {
        if (!Array.isArray(value) || !value.length) return "-";
        return value.map((item) => roleLabels[String(item).toLowerCase()] || item).join(", ");
    }

    function displayState(value) {
        return displayValue(value).replaceAll("_", " ").toUpperCase();
    }

    function stateClass(receiver) {
        const state = String(receiver?.runtime_state || "UNKNOWN").trim().toUpperCase();
        const observedState = String(receiver?.observed_runtime_state || "").trim().toUpperCase();
        if (state === "MISSION_ACTIVE" || observedState === "MISSION_ACTIVE" || receiver?.observed_mission) {
            return "is-mission-active";
        }
        if (receiver?.reserved || ["RESERVED", "ATTENTION", "DRIFT", "BUSY"].includes(state)) {
            return "is-attention";
        }
        if (state === "SERVICE_ACTIVE" || observedState === "SERVICE_ACTIVE" || state === "ACTIVE" || (receiver?.active_services || []).length) {
            return "is-service-active";
        }
        if (!receiver?.available || ["ERROR", "DISABLED", "UNAVAILABLE", "MISSING", "OFFLINE"].includes(state)) {
            return "is-unavailable";
        }
        return "is-ready";
    }

    function detail(label, value, extraClass = "") {
        return `<div class="${extraClass}"><dt>${esc(label)}</dt><dd title="${esc(displayValue(value))}">${esc(displayValue(value))}</dd></div>`;
    }

    function render(data) {
        const root = document.getElementById("receiver-inventory");
        const status = document.getElementById("receiver-inventory-status");
        if (!root) return;

        const items = Array.isArray(data.receivers) ? data.receivers : [];
        if (!data.ok || !items.length) {
            root.innerHTML = '<div class="receiver-inventory-empty">No receiver data available.</div>';
            if (status) status.textContent = data.error || "Receiver Inventory is unavailable.";
            return;
        }

        root.innerHTML = items.map((receiver) => {
            const tone = stateClass(receiver);
            const capabilities = Array.isArray(receiver.capabilities) ? receiver.capabilities : [];
            return `<article class="receiver-inventory-item ${tone}">
                <div class="receiver-inventory-head">
                    <div>
                        <h3>${esc(receiver.number)} · ${esc(receiver.name)}</h3>
                        <div class="receiver-inventory-serial">RTL-SDR #${esc(receiver.serial)}</div>
                    </div>
                    <span class="receiver-inventory-state ${tone}" data-state="${esc(receiver.runtime_state)}">${esc(displayState(receiver.runtime_state))}</span>
                </div>
                <dl class="receiver-inventory-details">
                    ${detail("Canonical ID", receiver.canonical_id)}
                    ${detail("Runtime alias", receiver.runtime_id)}
                    ${detail("Driver", receiver.driver)}
                    ${detail("Assigned roles", displayList(receiver.assigned_roles), "receiver-inventory-detail-wide")}
                    ${detail("Available", receiver.available ? "YES" : "NO")}
                    ${detail("Active services", displayList(receiver.active_services), "receiver-inventory-detail-wide")}
                </dl>
                <div class="receiver-inventory-tags">${capabilities.map((item) => `<span class="receiver-inventory-tag">${esc(roleLabels[String(item).toLowerCase()] || item)}</span>`).join("")}</div>
            </article>`;
        }).join("");

        if (status) {
            status.textContent = `${items.length} receivers · identity authority: ${data.identity_authority} · read-only`;
        }
    }

    async function load() {
        try {
            const response = await fetch("/api/receiver-inventory", {cache: "no-store"});
            render(await response.json());
        } catch (error) {
            render({ok: false, error: error.message, receivers: []});
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        load();
        window.setInterval(load, 10000);
    });
})();
