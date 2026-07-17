(() => {
    const state = {busy: false, timer: null};

    const byId = (id) => document.getElementById(id);
    const escapeHtml = (value) => String(value ?? "-")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    function setMessage(message, isError = false) {
        const node = byId("mission-planner-message");
        if (!node) return;
        node.textContent = message;
        node.classList.toggle("error-text", isError);
    }

    function formatDateTime(value) {
        if (!value) return "-";
        const [date = "", time = ""] = String(value).split(" ");
        return `${date} ${time.slice(0, 5)}`.trim();
    }

    function eligibility(item, minimumElevation) {
        if (item.skipped) return {label: "SKIPPED", reason: "Manually skipped by the operator.", cls: "skipped"};
        if ((item.conflict_with || []).length) return {label: "CONFLICT", reason: `Receiver conflict with ${(item.conflict_with || []).join(", ")}.`, cls: "conflict"};
        const elevation = Number(item.max_elevation);
        if (Number.isFinite(elevation) && elevation < minimumElevation) {
            return {label: "BELOW LIMIT", reason: `Maximum elevation ${elevation.toFixed(1)}° is below the ${minimumElevation.toFixed(1)}° limit.`, cls: "blocked"};
        }
        const status = String(item.status || "QUEUED").toUpperCase();
        if (["TARGET", "NEXT"].includes(status)) return {label: "TARGET", reason: "Selected as the next automated mission.", cls: "target"};
        if (["ACTIVE", "IN PROGRESS", "RECORDING"].includes(status)) return {label: "ACTIVE", reason: "Mission is currently active.", cls: "active"};
        return {label: "ELIGIBLE", reason: "Pass meets the current planning rules.", cls: "eligible"};
    }

    function render(payload) {
        const queue = Array.isArray(payload.queue) ? payload.queue : [];
        const minimumElevation = Number(payload.minimum_elevation ?? 40);
        byId("mission-planner-minimum-elevation").value = String(minimumElevation);
        byId("mission-planner-pass-count").textContent = String(queue.length);
        byId("mission-planner-conflict-count").textContent = String(payload.conflicts || 0);
        byId("mission-planner-skipped-count").textContent = String(payload.skipped || 0);
        byId("mission-planner-window").textContent = `${payload.hours_ahead || 48} hours`;

        const body = byId("mission-planner-table-body");
        if (!body) return;
        if (!queue.length) {
            body.innerHTML = '<tr><td colspan="8" class="mission-planner-empty">No eligible missions found in the planning window.</td></tr>';
            return;
        }

        body.innerHTML = queue.map((item) => {
            const result = eligibility(item, minimumElevation);
            const receiver = item.active_receiver || item.reserved_receiver || item.configured_receiver || item.receiver || "-";
            const elevation = Number(item.max_elevation);
            const frequency = Number(item.frequency_mhz);
            const quality = item.quality?.label || "-";
            return `<tr class="mission-planner-row is-${escapeHtml(result.cls)}">
                <td><strong>${escapeHtml(item.name || "Unknown satellite")}</strong><span>${escapeHtml(item.mode || item.pipeline || "-")}</span></td>
                <td>${escapeHtml(formatDateTime(item.start))}</td>
                <td>${Number.isFinite(elevation) ? `${elevation.toFixed(1)}°` : "-"}</td>
                <td>${Number.isFinite(frequency) ? `${frequency.toFixed(3)} MHz` : "-"}</td>
                <td>${escapeHtml(receiver)}</td>
                <td>${escapeHtml(quality)}</td>
                <td><span class="mission-planner-state is-${escapeHtml(result.cls)}">${escapeHtml(result.label)}</span></td>
                <td>${escapeHtml(result.reason)}</td>
            </tr>`;
        }).join("");
    }

    async function loadPlanner() {
        try {
            const response = await fetch("/api/mission-queue?limit=50&hours=48", {cache: "no-store"});
            const payload = await response.json();
            if (!response.ok || payload.ok === false) throw new Error(payload.error || "Mission Planner is unavailable.");
            render(payload);
            setMessage(`Updated ${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"})}.`);
        } catch (error) {
            setMessage(`Refresh failed: ${error.message}`, true);
        }
    }

    async function saveMinimumElevation(event) {
        event.preventDefault();
        if (state.busy) return;
        const form = event.currentTarget;
        const input = byId("mission-planner-minimum-elevation");
        const button = form.querySelector('button[type="submit"]');
        state.busy = true;
        if (button) button.disabled = true;
        setMessage("Saving minimum elevation...");
        try {
            const response = await fetch("/api/weather-planning", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({minimum_elevation: Number(input.value)}),
            });
            const payload = await response.json();
            if (!response.ok || payload.ok === false) throw new Error(payload.message || "Save failed.");
            setMessage(payload.message || "Minimum elevation saved.");
            window.dispatchEvent(new CustomEvent("sdrcc:weather-planning-changed", {detail: payload.settings}));
            await loadPlanner();
        } catch (error) {
            setMessage(`Save failed: ${error.message}`, true);
        } finally {
            state.busy = false;
            if (button) button.disabled = false;
        }
    }

    byId("mission-planner-settings-form")?.addEventListener("submit", saveMinimumElevation);
    byId("mission-planner-refresh")?.addEventListener("click", loadPlanner);
    window.addEventListener("sdrcc:weather-planning-changed", loadPlanner);
    loadPlanner();
    state.timer = window.setInterval(loadPlanner, 15000);
})();
