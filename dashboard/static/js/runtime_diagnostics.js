(() => {
    "use strict";

    const endpoint = "/api/receiver-runtime";
    const refreshIntervalMs = 5000;

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function displayRole(role) {
        const labels = {weather: "Weather / METEOR", ais: "AIS", adsb: "ADS-B", iss_voice: "ISS Voice"};
        return labels[String(role || "").toLowerCase()] || String(role || "-");
    }

    function displayState(state) {
        return String(state || "UNKNOWN").replaceAll("_", " ");
    }

    function stateClass(state) {
        const normalized = String(state || "").toUpperCase();
        if (normalized === "MISSION_ACTIVE") return "is-mission";
        if (normalized === "RESERVED") return "is-reserved";
        if (normalized === "SERVICE_ACTIVE") return "is-service";
        if (normalized === "IDLE") return "is-idle";
        return "is-unknown";
    }

    function serviceText(services) {
        if (!Array.isArray(services) || services.length === 0) return "None";

        return services.map((service) => {
            const name = service.service || service.role || "unknown";
            const state = service.state || "unknown";
            return `${name} (${state})`;
        }).join(", ");
    }

    function reservationText(receiver) {
        if (!receiver || !receiver.reserved) return "None";

        return receiver.reservation_owner
            || receiver.reservation?.mission_key
            || receiver.reservation?.mission_id
            || "Reserved";
    }

    function missionText(receiver, snapshot) {
        const mission = receiver?.observed_mission;

        if (mission && typeof mission === "object") {
            return mission.mission_id
                || mission.satellite
                || mission.name
                || "Active mission";
        }

        if (receiver?.runtime_state === "MISSION_ACTIVE") {
            return snapshot.active_mission_id || "Active mission";
        }

        return snapshot.mission_phase || "None";
    }

    function assignmentVerification(snapshot) {
        const verification = snapshot?.assignment_verification || {};
        const status = String(verification.status || "UNVERIFIED").toUpperCase();
        const configured = verification.configured_assignments || {};
        const runtime = verification.verified_runtime_assignments || {};
        const drift = Array.isArray(verification.drift) ? verification.drift : [];
        const roleText = ["weather", "ais", "adsb", "iss_voice"].map((role) => {
            const expected = configured[role] || "-";
            const observed = runtime[role] || "inactive / not verified";
            return `${displayRole(role)}: ${expected} → ${observed}`;
        }).join(" · ");
        const detail = drift.length
            ? drift.map((item) => `${displayRole(item.role)}: ${item.type}`).join(" · ")
            : "No configuration drift observed.";

        return `
            <div class="runtime-assignment-verification is-${escapeHtml(status.toLowerCase())}">
                <div>
                    <strong>Assignment Authority: ${escapeHtml(status)}</strong>
                    <small>${escapeHtml(verification.assignment_authority || "config/station.yaml:assignments")}</small>
                </div>
                <p>${escapeHtml(roleText)}</p>
                <p>${escapeHtml(detail)}</p>
            </div>`;
    }

    function receiverRow(receiverId, receiver, snapshot) {
        const roles = Array.isArray(receiver.configured_roles)
            ? receiver.configured_roles.map(displayRole).join(", ")
            : "-";
        const runtimeState = receiver.runtime_state || "UNKNOWN";
        const serial = receiver.serial || receiver.device?.serial || "-";
        const authority = receiver.authority || snapshot.authority || "-";

        return `
            <tr>
                <th scope="row">
                    <strong>${escapeHtml(receiverId.toUpperCase())}</strong>
                    <small>${escapeHtml(serial)}</small>
                </th>
                <td>
                    <strong>${escapeHtml(authority)}</strong>
                    <small>read-only observer</small>
                </td>
                <td>
                    <span class="runtime-state-badge ${stateClass(runtimeState)}">
                        ${escapeHtml(displayState(runtimeState))}
                    </span>
                </td>
                <td>
                    <strong>${escapeHtml(missionText(receiver, snapshot))}</strong>
                    <small>${receiver.observed_mission ? "Active mission" : "No active mission"}</small>
                </td>
                <td>
                    <strong>${escapeHtml(reservationText(receiver))}</strong>
                    <small>${receiver.reserved ? "Receiver reserved" : "Not reserved"}</small>
                </td>
                <td>
                    <strong>${escapeHtml(roles || "-")}</strong>
                    <small>${Array.isArray(receiver.configured_roles) ? receiver.configured_roles.length : 0} role(s)</small>
                </td>
                <td>
                    <strong>${escapeHtml(serviceText(receiver.observed_services))}</strong>
                </td>
            </tr>`;
    }

    function render(snapshot) {
        const grid = document.getElementById("receiver-runtime-grid");
        const updated = document.getElementById("receiver-runtime-updated");
        const authority = document.getElementById("receiver-runtime-authority");

        if (!grid || !updated || !authority) return;

        const receivers = snapshot?.receivers;
        if (!receivers || typeof receivers !== "object") {
            throw new Error("Receiver Runtime did not return a valid receiver list.");
        }

        const entries = Object.entries(receivers);

        grid.innerHTML = assignmentVerification(snapshot) + (entries.length
            ? `
                <div class="runtime-diagnostics-table-wrap">
                    <table class="runtime-diagnostics-table">
                        <thead>
                            <tr>
                                <th>SDR</th>
                                <th>Authority</th>
                                <th>Runtime status</th>
                                <th>Mission / phase</th>
                                <th>Reservation</th>
                                <th>Roles</th>
                                <th>Observed services</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${entries.map(([receiverId, receiver]) =>
                                receiverRow(receiverId, receiver, snapshot)
                            ).join("")}
                        </tbody>
                    </table>
                </div>`
            : '<div class="runtime-diagnostics-empty">No receivers observed.</div>');

        authority.textContent =
            `Authority: ${snapshot.authority || "unknown"} · read-only`;

        updated.textContent = snapshot.updated_at
            ? `UPDATED ${new Date(snapshot.updated_at).toLocaleTimeString("en-GB")}`
            : "UPDATED";

        updated.classList.remove("runtime-diagnostics-error");
    }

    function renderError(error) {
        const grid = document.getElementById("receiver-runtime-grid");
        const updated = document.getElementById("receiver-runtime-updated");
        const authority = document.getElementById("receiver-runtime-authority");

        if (grid) {
            grid.innerHTML = `
                <div class="runtime-diagnostics-empty runtime-diagnostics-error">
                    Runtime Diagnostics unavailable:
                    ${escapeHtml(error)}
                </div>`;
        }

        if (updated) {
            updated.textContent = "ERROR";
            updated.classList.add("runtime-diagnostics-error");
        }

        if (authority) {
            authority.textContent = "Read-only observation";
        }
    }

    async function refreshRuntimeDiagnostics() {
        if (!document.getElementById("receiver-runtime-grid")) return;

        try {
            const response = await fetch(endpoint, {
                headers: {"Accept": "application/json"},
                cache: "no-store",
            });
            const data = await response.json();

            if (!response.ok || data.ok === false) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }

            render(data);
        } catch (error) {
            console.error("Receiver Runtime Diagnostics:", error);
            renderError(error instanceof Error ? error.message : String(error));
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        refreshRuntimeDiagnostics();
        window.setInterval(refreshRuntimeDiagnostics, refreshIntervalMs);
    });
})();
