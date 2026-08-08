(() => {
    const state = {busy: false, timer: null, formDirty: false};

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

    function formatTime(value) {
        if (!value) return "-";
        const parts = String(value).split(" ");
        return (parts[1] || parts[0] || "-").slice(0, 5);
    }

    function eligibility(item) {
        const label = String(item.decision || "ELIGIBLE").toUpperCase();
        const reason = String(item.decision_reason || "Pass meets its satellite planning policy.");
        const cls = String(item.decision_class || "eligible").toLowerCase();
        return {label, reason, cls};
    }

    function renderTleStatus(tle) {
        const node = byId("mission-planner-tle-status");
        if (!node) return;
        const stateName = String(tle?.state || "INVALID").toUpperCase();
        const ages = [tle?.weather?.age_hours, tle?.iss_voice?.age_hours]
            .map(Number)
            .filter(Number.isFinite);
        const age = ages.length ? Math.max(...ages) : null;
        node.textContent = stateName === "CURRENT"
            ? `TLE CURRENT · ${age?.toFixed(1) ?? "-"} h`
            : stateName === "STALE"
                ? `TLE STALE · ${age?.toFixed(1) ?? "-"} h`
                : "TLE INVALID";
        node.className = `mission-planner-tle-status is-${stateName.toLowerCase()}`;
        node.title = `${tle?.source || "CelesTrak"}; ISS 25544, METEOR 57166 and 59051`;
    }

    function renderSettings(profiles) {
        const form = byId("mission-planner-settings-form");
        if (!form || state.formDirty || form.contains(document.activeElement)) return;
        form.querySelectorAll("[data-planning-profile]").forEach(group => {
            const profile = profiles?.[group.dataset.planningProfile];
            if (!profile) return;
            group.querySelectorAll("[data-planning-field]").forEach(input => {
                const value = Number(profile[input.dataset.planningField]);
                if (Number.isFinite(value)) input.value = String(value);
            });
            const choice = group.querySelector("[data-frequency-choice]");
            const custom = group.querySelector("[data-frequency-custom]");
            if (choice && custom) {
                const frequency = Number(profile.frequency_mhz);
                choice.value = ["primary", "secondary", "custom"].includes(profile.frequency_choice)
                    ? profile.frequency_choice
                    : (frequency === 137.9 ? "primary" : frequency === 137.1 ? "secondary" : "custom");
                if (Number.isFinite(frequency)) custom.value = frequency.toFixed(4);
                updateFrequencyControl(group);
            }
        });
    }

    function updateFrequencyControl(group) {
        const choice = group.querySelector("[data-frequency-choice]");
        const custom = group.querySelector("[data-frequency-custom]");
        const customLabel = group.querySelector(".mission-planner-custom-frequency");
        if (!choice || !custom || !customLabel) return;
        const isCustom = choice.value === "custom";
        customLabel.hidden = !isCustom;
        custom.required = isCustom;
        if (!isCustom) {
            custom.value = choice.value === "secondary" ? "137.1000" : "137.9000";
        }
    }

    function render(payload) {
        const queue = Array.isArray(payload.queue) ? payload.queue : [];
        renderSettings(payload.planning_profiles || payload.planning_policy?.profiles || {});
        renderTleStatus(payload.tle_status || {});
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
            const result = eligibility(item);
            const receiver = item.active_receiver || item.reserved_receiver || item.configured_receiver || item.receiver || "-";
            const elevation = Number(item.max_elevation);
            const frequency = Number(item.frequency_mhz);
            const begin = Number(item.begin_elevation);
            const close = Number(item.close_elevation);
            const quality = item.quality?.label || "-";
            const windowAngles = Number.isFinite(begin) && Number.isFinite(close)
                ? `${begin.toFixed(1)}° rising · ${close.toFixed(1)}° falling`
                : "-";
            return `<tr class="mission-planner-row is-${escapeHtml(result.cls)}">
                <td><strong>${escapeHtml(item.name || "Unknown satellite")}</strong><span>${escapeHtml(item.mode || item.pipeline || "-")}</span></td>
                <td><strong>${escapeHtml(formatDateTime(item.start))} → ${escapeHtml(formatTime(item.end))}</strong><small>${escapeHtml(windowAngles)}</small></td>
                <td>${Number.isFinite(elevation) ? `${elevation.toFixed(1)}°` : "-"}</td>
                <td>${Number.isFinite(frequency) ? `${frequency.toFixed(3)} MHz` : "-"}</td>
                <td>${escapeHtml(receiver)}</td>
                <td>${escapeHtml(quality)}</td>
                <td><span class="mission-planner-state is-${escapeHtml(result.cls)}">${escapeHtml(result.label)}</span></td>
                <td>${escapeHtml(result.reason)}</td>
            </tr>`;
        }).join("");
    }

    async function loadPlanner({quiet = false} = {}) {
        try {
            const response = await fetch("/api/mission-queue?limit=50&hours=48", {cache: "no-store"});
            const payload = await response.json();
            if (!response.ok || payload.ok === false) throw new Error(payload.error || "Mission Planner is unavailable.");
            render(payload);
            if (!quiet) {
                setMessage(`Updated ${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"})}.`);
            }
        } catch (error) {
            setMessage(`Refresh failed: ${error.message}`, true);
        }
    }

    function collectProfiles(form) {
        const profiles = {};
        form.querySelectorAll("[data-planning-profile]").forEach(group => {
            const values = {};
            group.querySelectorAll("[data-planning-field]").forEach(input => {
                values[input.dataset.planningField] = Number(input.value);
            });
            if (values.begin_elevation > values.minimum_peak_elevation) {
                throw new Error(`${group.querySelector("legend")?.textContent || "Profile"}: begin angle exceeds minimum peak.`);
            }
            if (values.close_elevation > values.minimum_peak_elevation) {
                throw new Error(`${group.querySelector("legend")?.textContent || "Profile"}: close angle exceeds minimum peak.`);
            }
            const frequencyChoice = group.querySelector("[data-frequency-choice]");
            const customFrequency = group.querySelector("[data-frequency-custom]");
            if (frequencyChoice && customFrequency) {
                const choice = frequencyChoice.value;
                const frequencyMhz = choice === "primary"
                    ? 137.9
                    : choice === "secondary"
                        ? 137.1
                        : Number(customFrequency.value);
                if (!Number.isFinite(frequencyMhz) || frequencyMhz < 136 || frequencyMhz > 138) {
                    throw new Error(`${group.querySelector("legend")?.textContent || "Profile"}: custom frequency must be between 136 and 138 MHz.`);
                }
                values.frequency_choice = choice;
                values.frequency_hz = Math.round(frequencyMhz * 1000000);
            }
            profiles[group.dataset.planningProfile] = values;
        });
        return profiles;
    }

    async function savePassWindows(event) {
        event.preventDefault();
        if (state.busy) return;
        const form = event.currentTarget;
        const button = form.querySelector('button[type="submit"]');
        state.busy = true;
        if (button) button.disabled = true;
        setMessage("Saving satellite plans...");
        try {
            const profiles = collectProfiles(form);
            const response = await fetch("/api/weather-planning", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({profiles}),
            });
            const payload = await response.json();
            if (!response.ok || payload.ok === false) throw new Error(payload.message || "Save failed.");
            state.formDirty = false;
            renderSettings(payload.settings?.profiles || {});
            renderTleStatus(payload.tle || {});
            setMessage(payload.message || "Satellite plans saved.");
            window.dispatchEvent(new CustomEvent("sdrcc:weather-planning-changed", {detail: payload.settings}));
            await loadPlanner({quiet: true});
        } catch (error) {
            setMessage(`Save failed: ${error.message}`, true);
        } finally {
            state.busy = false;
            if (button) button.disabled = false;
        }
    }

    async function refreshTleAndPlanning() {
        if (state.busy) return;
        const button = byId("mission-planner-refresh");
        state.busy = true;
        if (button) button.disabled = true;
        setMessage("Checking the validated CelesTrak TLE cache...");
        try {
            const response = await fetch("/api/weather-planning", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({action: "refresh"}),
            });
            const payload = await response.json();
            if (!response.ok || payload.ok === false) throw new Error(payload.error || payload.message || "TLE refresh failed.");
            renderTleStatus(payload.tle || {});
            setMessage(payload.warning && payload.error
                ? `${payload.message} ${payload.error}`
                : (payload.message || "TLE cache checked."), Boolean(payload.warning));
            await loadPlanner({quiet: true});
        } catch (error) {
            setMessage(`Refresh failed: ${error.message}`, true);
        } finally {
            state.busy = false;
            if (button) button.disabled = false;
        }
    }

    const form = byId("mission-planner-settings-form");
    form?.addEventListener("input", () => { state.formDirty = true; });
    form?.querySelectorAll("[data-frequency-choice]").forEach(control => {
        control.addEventListener("change", () => {
            updateFrequencyControl(control.closest("[data-planning-profile]"));
            state.formDirty = true;
        });
    });
    form?.addEventListener("submit", savePassWindows);
    byId("mission-planner-refresh")?.addEventListener("click", refreshTleAndPlanning);
    window.addEventListener("sdrcc:weather-planning-changed", () => loadPlanner({quiet: true}));
    loadPlanner();
    state.timer = window.setInterval(() => loadPlanner({quiet: true}), 15000);
})();
