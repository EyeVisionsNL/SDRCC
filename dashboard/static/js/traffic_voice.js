(() => {
    "use strict";

    const endpoint = "/api/traffic-voice";
    const actionEndpoint = "/api/traffic-voice/action";
    let refreshTimer = null;
    let actionBusy = false;
    let settingsDirty = false;
    let lastPayload = null;
    let channelSignature = "";
    let gainSignature = "";

    function byId(id) {
        return document.getElementById(id);
    }

    function text(id, value) {
        const element = byId(id);
        if (element) element.textContent = value ?? "-";
    }

    function receiverLabel(receiver) {
        if (!receiver || typeof receiver !== "object") return "Unassigned";
        const name = receiver.name || receiver.runtime_id || receiver.canonical_id || "Receiver";
        return name + (receiver.serial ? " · " + receiver.serial : "");
    }

    function displayToken(value) {
        return String(value || "-")
            .replaceAll("_", " ")
            .replace(/\b\w/g, letter => letter.toUpperCase());
    }

    function selectedMode(payload) {
        return (Array.isArray(payload.modes) ? payload.modes : [])
            .find(mode => mode.selected) || {};
    }

    function channelFrequencyLabel(channel) {
        const carrier = Number(channel.frequency_mhz);
        const designator = Number(channel.channel_mhz);
        if (
            Number.isFinite(designator)
            && Number.isFinite(carrier)
            && Math.abs(designator - carrier) >= 0.0005
        ) {
            return designator.toFixed(3) + " MHz · tune " + carrier.toFixed(6) + " MHz";
        }
        return Number.isFinite(carrier) ? carrier.toFixed(3) + " MHz" : "-";
    }

    function renderMode(mode, running) {
        const card = document.querySelector('[data-traffic-mode="' + mode.id + '"]');
        if (!card) return;
        card.classList.toggle("is-selected", Boolean(mode.selected));
        card.classList.toggle("is-planned", !mode.execution_enabled);
        const state = card.querySelector("[data-traffic-mode-state]");
        if (state) {
            state.textContent = mode.execution_enabled
                ? (mode.selected ? "ACTIVE MODE" : "AVAILABLE")
                : "PLANNED";
        }
        const modulation = card.querySelector("[data-traffic-mode-modulation]");
        const context = card.querySelector("[data-traffic-mode-context]");
        const receiver = card.querySelector("[data-traffic-mode-receiver]");
        const bank = card.querySelector("[data-traffic-mode-bank]");
        const activityState = card.querySelector("[data-traffic-mode-activity-state]");
        if (modulation) modulation.textContent = mode.modulation || "-";
        if (context) context.textContent = String(mode.context_plugin || "-").toUpperCase();
        if (receiver) receiver.textContent = receiverLabel(mode.derived_voice_receiver);
        if (bank) bank.textContent = displayToken(mode.channel_bank) + " · " + mode.channel_count;
        if (activityState) {
            activityState.textContent = mode.selected
                ? (running ? "LIVE ACTIVITY" : "SELECTED · STOPPED")
                : (running ? "STANDBY" : "AVAILABLE");
        }
    }

    function populateSelect(select, values, signature, previousSignature, formatter) {
        if (!select || signature === previousSignature) return previousSignature;
        const current = select.value;
        select.replaceChildren();
        values.forEach(item => {
            const option = document.createElement("option");
            const rendered = formatter(item);
            option.value = rendered.value;
            option.textContent = rendered.label;
            select.append(option);
        });
        if ([...select.options].some(option => option.value === current)) {
            select.value = current;
        }
        return signature;
    }

    function renderSettings(payload, running) {
        const settings = payload.receiver_settings || {};
        const channels = Array.isArray(settings.channels) ? settings.channels : [];
        const gains = Array.isArray(settings.valid_gains) ? settings.valid_gains : [];
        const channelSelect = byId("traffic-voice-channel-select");
        const gainSelect = byId("traffic-voice-gain");
        const tuningMode = byId("traffic-voice-tuning-mode");
        const squelch = byId("traffic-voice-squelch");

        const nextChannelSignature = String(settings.mode_id || "") + "|" + channels
            .map(item => item.id + ":" + item.frequency_mhz + ":" + (item.channel_mhz || "")).join("|");
        channelSignature = populateSelect(
            channelSelect,
            channels,
            nextChannelSignature,
            channelSignature,
            item => ({
                value: String(item.id),
                label: String(item.label) + " · " + channelFrequencyLabel(item),
            }),
        );
        const nextGainSignature = gains.join("|");
        gainSignature = populateSelect(
            gainSelect,
            gains,
            nextGainSignature,
            gainSignature,
            item => ({value: String(item), label: Number(item).toFixed(1) + " dB"}),
        );

        if (!settingsDirty && !actionBusy) {
            if (tuningMode) tuningMode.value = settings.tuning_mode || "scan";
            if (channelSelect) channelSelect.value = settings.selected_channel_id || "";
            if (gainSelect) gainSelect.value = String(settings.gain_db ?? "28");
            if (squelch) squelch.value = String(settings.squelch_snr_db ?? "6");
        }
        text(
            "traffic-voice-squelch-value",
            Number(squelch?.value || settings.squelch_snr_db || 0).toFixed(1) + " dB",
        );

        const open = Boolean(settings.open_squelch);
        const openButton = byId("traffic-voice-open-squelch");
        if (openButton) {
            openButton.textContent = open ? "Close squelch" : "Open squelch / Test";
            openButton.classList.toggle("is-open", open);
            openButton.disabled = actionBusy || !running;
        }
        const applyButton = byId("traffic-voice-apply-settings");
        if (applyButton) applyButton.disabled = actionBusy || !payload.ok;

        const chosen = channels.find(item => item.id === settings.selected_channel_id);
        const tuningLabel = open
            ? "FIXED · SQUELCH OPEN"
            : settings.tuning_mode === "fixed"
                ? "FIXED · " + (chosen?.label || "-")
                : "SCAN ALL · " + channels.length;
        text("traffic-voice-tuning-state", tuningLabel);
        text(
            "traffic-voice-rf-settings",
            Number(settings.gain_db || 0).toFixed(1) + " dB · "
                + Number(settings.squelch_snr_db || 0).toFixed(1) + " dB",
        );
    }

    function renderChannelBank(mode, payload) {
        const container = document.querySelector(
            '[data-traffic-channel-bank="' + mode.id + '"]',
        );
        if (!container) return;
        const configured = Array.isArray(mode.channels) ? mode.channels : [];
        const selected = Boolean(mode.selected);
        const measured = selected && Array.isArray((payload.activity || {}).channels)
            ? payload.activity.channels : [];
        const measurements = new Map(
            measured.map(item => [Number(item.frequency_mhz).toFixed(6), item]),
        );
        const settings = payload.receiver_settings || {};
        container.replaceChildren();
        if (!configured.length) {
            const empty = document.createElement("p");
            empty.textContent = "No channels configured.";
            container.append(empty);
            return;
        }

        configured.forEach(channel => {
            const live = measurements.get(Number(channel.frequency_mhz).toFixed(6)) || {};
            const row = document.createElement("button");
            row.type = "button";
            row.className = "traffic-voice-channel";
            row.disabled = !selected || actionBusy || !payload.ok;
            row.classList.toggle("is-possible-active", selected && Boolean(live.possible_active));
            row.classList.toggle(
                "is-selected",
                selected && settings.tuning_mode === "fixed" && settings.selected_channel_id === channel.id,
            );
            row.title = selected
                ? "Listen on " + channel.label
                : "Select this Voice mode before tuning a channel";
            if (selected) row.addEventListener("click", () => selectFixedChannel(channel.id));

            const copy = document.createElement("div");
            copy.className = "traffic-voice-channel-copy";
            const label = document.createElement("strong");
            label.textContent = channel.label || String(channel.frequency_mhz) + " MHz";
            const frequency = document.createElement("span");
            frequency.textContent = channelFrequencyLabel(channel);
            copy.append(label, frequency);

            const meter = document.createElement("div");
            meter.className = "traffic-voice-channel-meter";
            const fill = document.createElement("i");
            const snr = Number(live.snr_db);
            fill.style.width = selected
                ? (Number.isFinite(snr) ? Math.max(3, Math.min(100, snr * 5)) : 3) + "%"
                : "0%";
            meter.append(fill);

            const value = document.createElement("span");
            value.className = "traffic-voice-channel-value";
            value.textContent = selected
                ? (Number.isFinite(snr) ? snr.toFixed(1) + " dB SNR" : "not measured")
                : "available";
            row.append(copy, meter, value);
            container.append(row);
        });
    }

    function renderActivity(payload, modes) {
        modes.forEach(mode => renderChannelBank(mode, payload));
    }

    function stopAudio() {
        const audio = byId("traffic-voice-audio");
        if (!audio) return;
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        const button = byId("traffic-voice-audio-toggle");
        if (button) button.textContent = "▶ Live audio";
        text("traffic-voice-audio-detail", "Live audio stopped in this browser.");
    }

    async function startAudio() {
        const audio = byId("traffic-voice-audio");
        const streamUrl = audio?.dataset.streamUrl || "";
        if (!audio || !streamUrl) return;
        audio.volume = Number(byId("traffic-voice-volume")?.value || 0.85);
        audio.src = streamUrl + (streamUrl.includes("?") ? "&" : "?") + "live=" + Date.now();
        try {
            await audio.play();
            const button = byId("traffic-voice-audio-toggle");
            if (button) button.textContent = "■ Stop audio";
            text("traffic-voice-audio-detail", "Playing the live stream; no artificial duration is shown.");
        } catch (error) {
            text("traffic-voice-audio-detail", "Browser audio could not start: " + error.message);
        }
    }

    function renderAudio(payload) {
        const audio = byId("traffic-voice-audio");
        const button = byId("traffic-voice-audio-toggle");
        const audioState = payload.audio || {};
        text("traffic-voice-audio-state", audioState.stream_state || "WAITING");
        if (!audio) return;
        audio.dataset.streamUrl = audioState.stream_url || "";
        if (button) button.disabled = actionBusy || !audioState.stream_url;
        if (!audioState.stream_url && audio.getAttribute("src")) stopAudio();
        if (!audioState.stream_url) {
            text("traffic-voice-audio-detail", "Start Voice and wait for the local audio stream.");
        }
    }

    function render(payload) {
        lastPayload = payload;
        const status = byId("traffic-voice-status");
        const serviceBadge = byId("traffic-voice-service-state");
        const assignmentBadge = byId("traffic-voice-assignment-state");
        const message = byId("traffic-voice-contract-message");
        const assignment = payload.assignment || {};
        const modes = Array.isArray(payload.modes) ? payload.modes : [];
        const selected = selectedMode(payload);
        const running = Boolean((payload.service || {}).active);

        if (status) {
            status.textContent = payload.ok
                ? (selected.id === "airband_adsb" ? "AIRBAND READY" : "MARINE READY")
                : "ATTENTION";
            status.classList.toggle("is-foundation", Boolean(payload.ok));
            status.classList.toggle("is-attention", !payload.ok);
        }
        if (serviceBadge) {
            serviceBadge.textContent = running ? "VOICE RUNNING" : "VOICE STOPPED";
            serviceBadge.classList.toggle("is-valid", running);
            serviceBadge.classList.toggle("is-offline", !running);
        }

        modes.forEach(mode => renderMode(mode, running));
        renderSettings(payload, running);
        renderActivity(payload, modes);
        renderAudio(payload);

        text("traffic-voice-selected-mode", selected.label || displayToken(payload.selected_mode));
        text("traffic-voice-voice-receiver", receiverLabel(assignment.voice_receiver));
        text("traffic-voice-context-receiver", receiverLabel(assignment.context_receiver));
        text("traffic-voice-backend", (displayToken((payload.backend || {}).name) + " " + ((payload.backend || {}).version || "")).trim());
        text("traffic-voice-execution", payload.execution_enabled ? "EXECUTION ENABLED" : "EXECUTION DISABLED");

        const strongest = payload.strongest_channel || {};
        text("traffic-voice-active-channel", strongest.label || "-");
        text(
            "traffic-voice-signal",
            Number.isFinite(Number(strongest.signal_dbfs))
                ? Number(strongest.signal_dbfs).toFixed(1) + " dBFS · " + Number(strongest.snr_db).toFixed(1) + " dB"
                : "-",
        );
        text("traffic-voice-possible-speaker", payload.possible_speaker || "NOT INFERRED");

        const assignmentValid = Boolean(assignment.separated && assignment.matches_policy);
        if (assignmentBadge) {
            assignmentBadge.textContent = running
                ? (assignmentValid ? "ASSIGNMENT VALID" : "ASSIGNMENT ATTENTION")
                : "ASSIGNED ON START";
            assignmentBadge.classList.toggle("is-valid", running && assignmentValid);
            assignmentBadge.classList.toggle("is-attention", running && !assignmentValid);
        }
        if (message) {
            const errors = ((payload.validation || {}).errors || []).filter(Boolean);
            const context = String(selected.context_plugin || "traffic context").toUpperCase();
            message.textContent = payload.ok
                ? (selected.label || "Traffic Voice") + " uses the receiver opposite " + context
                    + ". Switching and settings reuse the existing Voice service; mission handover stays with Receiver Manager."
                : errors.join(" · ") || "Traffic Voice validation failed.";
            message.classList.toggle("is-error", !payload.ok);
        }

        const start = byId("traffic-voice-start");
        const startAirband = byId("traffic-voice-start-airband");
        const stop = byId("traffic-voice-stop");
        if (start) {
            start.textContent = running && selected.id === "airband_adsb"
                ? "Switch to Marine + AIS"
                : "Start Marine + AIS";
            start.disabled = actionBusy || !payload.ok || (running && selected.id === "marine_ais");
        }
        if (startAirband) {
            startAirband.textContent = running && selected.id === "marine_ais"
                ? "Switch to Airband + ADS-B"
                : "Start Airband + ADS-B";
            startAirband.disabled = actionBusy || !payload.ok || (running && selected.id === "airband_adsb");
        }
        if (stop) stop.disabled = actionBusy || !running;
    }

    function renderError(error) {
        const status = byId("traffic-voice-status");
        if (status) {
            status.textContent = "UNAVAILABLE";
            status.classList.remove("is-foundation");
            status.classList.add("is-attention");
        }
        text("traffic-voice-contract-message", "Traffic Voice API unavailable: " + error.message);
    }

    async function refresh(force = false) {
        if (!force && document.hidden) return;
        const page = byId("tab-traffic-voice");
        if (!force && (!page || !page.classList.contains("active"))) return;
        try {
            const response = await fetch(endpoint, {cache: "no-store"});
            const payload = await response.json();
            if (!response.ok && !payload.validation) {
                throw new Error(payload.error || "HTTP " + response.status);
            }
            render(payload);
        } catch (error) {
            renderError(error);
        }
    }

    async function runAction(action, extra = {}) {
        if (actionBusy) return false;
        actionBusy = true;
        const pending = {
            start_marine: "Starting Marine + AIS transaction…",
            start_airband: "Starting Airband + ADS-B transaction…",
            stop: "Stopping Voice and restoring the previous topology…",
            apply_settings: "Applying receiver settings…",
        };
        text("traffic-voice-action-message", pending[action] || "Working…");
        document.querySelectorAll(".traffic-voice-button")
            .forEach(button => button.setAttribute("disabled", ""));
        let succeeded = false;
        try {
            const response = await fetch(actionEndpoint, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({action, ...extra}),
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "HTTP " + response.status);
            }
            text("traffic-voice-action-message", payload.message);
            settingsDirty = false;
            succeeded = true;
        } catch (error) {
            text("traffic-voice-action-message", "Action failed: " + error.message);
        } finally {
            actionBusy = false;
            await refresh(true);
        }
        return succeeded;
    }

    function formSettings() {
        return {
            tuning_mode: byId("traffic-voice-tuning-mode")?.value || "scan",
            selected_channel_id: byId("traffic-voice-channel-select")?.value || "",
            gain_db: Number(byId("traffic-voice-gain")?.value || 0),
            squelch_snr_db: Number(byId("traffic-voice-squelch")?.value || 0),
            open_squelch: Boolean((lastPayload?.receiver_settings || {}).open_squelch),
        };
    }

    async function applySettings(overrides = {}) {
        return runAction("apply_settings", {
            settings: {...formSettings(), ...overrides},
        });
    }

    async function selectFixedChannel(channelId) {
        if (actionBusy) return;
        const tuning = byId("traffic-voice-tuning-mode");
        const channel = byId("traffic-voice-channel-select");
        if (tuning) tuning.value = "fixed";
        if (channel) channel.value = channelId;
        settingsDirty = true;
        await applySettings({
            tuning_mode: "fixed",
            selected_channel_id: channelId,
            open_squelch: false,
        });
    }

    function initialize() {
        document.querySelector('.tab-button[data-tab="traffic-voice"]')
            ?.addEventListener("click", () => window.setTimeout(() => refresh(true), 0));
        byId("traffic-voice-start")
            ?.addEventListener("click", () => runAction("start_marine"));
        byId("traffic-voice-start-airband")
            ?.addEventListener("click", () => runAction("start_airband"));
        byId("traffic-voice-stop")
            ?.addEventListener("click", () => runAction("stop"));
        byId("traffic-voice-apply-settings")
            ?.addEventListener("click", () => applySettings());
        byId("traffic-voice-open-squelch")?.addEventListener("click", async () => {
            const open = Boolean((lastPayload?.receiver_settings || {}).open_squelch);
            if (!open) await startAudio();
            await applySettings({open_squelch: !open});
            if (!open) await startAudio();
        });
        byId("traffic-voice-audio-toggle")?.addEventListener("click", () => {
            const audio = byId("traffic-voice-audio");
            if (audio && !audio.paused) stopAudio();
            else startAudio();
        });
        byId("traffic-voice-volume")?.addEventListener("input", event => {
            const audio = byId("traffic-voice-audio");
            if (audio) audio.volume = Number(event.target.value);
        });
        ["traffic-voice-tuning-mode", "traffic-voice-channel-select", "traffic-voice-gain"]
            .forEach(id => byId(id)?.addEventListener("change", () => { settingsDirty = true; }));
        byId("traffic-voice-squelch")?.addEventListener("input", event => {
            settingsDirty = true;
            text("traffic-voice-squelch-value", Number(event.target.value).toFixed(1) + " dB");
        });
        document.addEventListener("visibilitychange", refresh);
        refreshTimer = window.setInterval(refresh, 3000);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
        initialize();
    }

    window.addEventListener("beforeunload", () => {
        if (refreshTimer !== null) window.clearInterval(refreshTimer);
        stopAudio();
    }, {once: true});
})();
