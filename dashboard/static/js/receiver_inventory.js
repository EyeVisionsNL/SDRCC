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

    let editing = false;
    function render(data) {
        if (editing) return;
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
                        <h3>${esc(receiver.name || receiver.number || receiver.id)}</h3>
                        <div class="receiver-inventory-serial">${receiver.serial ? `RTL-SDR #${esc(receiver.serial)}` : "No hardware binding"}</div>
                    </div>
                    <span class="receiver-inventory-state ${tone}" data-state="${esc(receiver.runtime_state)}">${esc(displayState(receiver.runtime_state))}</span>
                </div>
                <dl class="receiver-inventory-details">
                    ${detail("Canonical ID", receiver.canonical_id)}
                    ${detail("Runtime alias", receiver.runtime_id)}
                    ${detail("USB status", receiver.presence)}
                    ${detail("Driver", receiver.driver)}
                    ${detail("Assigned roles", displayList(receiver.assigned_roles), "receiver-inventory-detail-wide")}
                    ${detail("Available", receiver.available ? "YES" : "NO")}
                    ${detail("Active services", displayList(receiver.active_services), "receiver-inventory-detail-wide")}
                </dl>
                <div class="receiver-inventory-tags">${capabilities.map((item) => `<span class="receiver-inventory-tag">${esc(roleLabels[String(item).toLowerCase()] || item)}</span>`).join("")}</div>
            </article>`;
        }).join("");

        const hardware = data.hardware || {};
        const detected = hardware.receivers || [];
        root.insertAdjacentHTML("beforeend", `<article class="receiver-inventory-item receiver-hardware-panel">
            <div class="receiver-hardware-head">
                <div><h3>Receiver hardware</h3><p>${esc(data.binding?.message || hardware.error || "")}</p></div>
                <button type="button" id="receiver-binding-edit">Change bindings</button>
            </div>
            <div class="receiver-hardware-bindings">
                ${items.filter(r => r.enabled).map(r => `<div class="receiver-hardware-binding">
                    <span><strong>${esc(r.name)}</strong><small>${esc(r.canonical_id)}</small></span>
                    <code>${r.serial ? esc(r.serial) : "NO BINDING"}</code>
                    <span class="receiver-hardware-presence is-${esc(String(r.presence || "unknown").toLowerCase())}">${esc(displayState(r.presence))}</span>
                </div>`).join("")}
            </div>
            <div class="receiver-hardware-detected"><span>Detected USB:</span>
                ${detected.map(d => `<span class="receiver-hardware-device">${esc(d.description)} · ${esc(d.serial || "NO SERIAL")}</span>`).join("") || "<em>No RTL-SDR connected</em>"}
            </div>
            <form id="receiver-binding-form" hidden>
                <div class="receiver-binding-fields">${items.filter(r => r.enabled).map(r => `<label><span>${esc(r.name)} <small>Current: ${esc(r.serial || "NO BINDING")}</small></span>
                    <select name="${esc(r.canonical_id)}"><option value="__KEEP__">Keep current binding</option>
                    <option value="__UNBOUND__">No binding (UNBOUND)</option>
                    ${detected.filter(d => d.serial).map(d => `<option value="${esc(d.serial)}">${esc(d.serial)} · ${esc(d.description)}</option>`).join("")}</select></label>`).join("")}
                </div>
                <div class="receiver-binding-actions"><p>Stop reception on receivers being changed. Roles and settings are retained.</p>
                <span><button type="submit">Apply bindings</button><button type="button" id="receiver-binding-cancel">Cancel</button></span></div>
                <p id="receiver-binding-result" role="status"></p>
            </form></article>`);
        document.getElementById("receiver-binding-edit").onclick = () => {
            editing = true;
            document.getElementById("receiver-binding-form").hidden = false;
        };
        document.getElementById("receiver-binding-cancel").onclick = () => { editing = false; load(); };
        document.getElementById("receiver-binding-form").onsubmit = async (event) => {
            event.preventDefault();
            const resultElement = document.getElementById("receiver-binding-result");
            const bindings = Object.fromEntries(
                [...new FormData(event.target)]
                    .filter(([, value]) => value !== "__KEEP__")
                    .map(([key, value]) => [key, value === "__UNBOUND__" ? "" : value])
            );
            if (!Object.keys(bindings).length) {
                resultElement.textContent = "Choose a new binding or No binding first.";
                return;
            }
            const button = event.target.querySelector('[type="submit"]');
            button.disabled = true;
            try {
                const response = await fetch("/api/receiver-bindings", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({bindings})});
                const result = await response.json();
                if (!result.ok) throw new Error(result.message || "Binding failed");
                editing = false;
                await load();
            } catch (error) { resultElement.textContent = error.message; }
            finally { button.disabled = false; }
        };
        if (status) status.textContent = `${items.length} receiver slots · ${hardware.ok ? detected.length + " USB receivers" : "USB status UNKNOWN"}`;
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
