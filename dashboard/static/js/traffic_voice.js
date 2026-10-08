(() => {
    "use strict";

    const endpoint = "/api/traffic-voice";
    const actionEndpoint = "/api/traffic-voice/action";
    const channelListExportEndpoint = "/api/traffic-voice/channel-list.xlsx";
    const channelListImportEndpoint = "/api/traffic-voice/channel-list/import";
    let refreshTimer = null;
    let actionBusy = false;
    let settingsDirty = false;
    let lastPayload = null;
    let channelSignature = "";
    let gainSignature = "";
    let audioOperation = 0;
    let replayResumeLive = false;
    let playingRecordingId = "";
    const speechFilterStorageKey = "sdrcc.trafficVoice.speechFilter";
    const speechFilterOptions = ["off", "light", "normal", "strong"];
    let speechFilter = "normal";
    let denoise = "off";
    let audioMode = "marine_ais";
    const audioPreferences = {
        marine_ais: {filter: "normal", denoise: "off"},
        airband_adsb: {filter: "off", denoise: "off"}
    };

    function loadAudioPreferences() {
        for (const mode of Object.keys(audioPreferences)) {
            try {
                const saved = JSON.parse(localStorage.getItem("sdrcc.trafficVoice.audio." + mode) || "null");
                const legacy = mode === "marine_ais" ? localStorage.getItem(speechFilterStorageKey) : null;
                const filter = saved?.filter || legacy;
                if (speechFilterOptions.includes(filter)) audioPreferences[mode].filter = filter;
                if (["off", "speex", "rnnoise"].includes(saved?.denoise)) audioPreferences[mode].denoise = saved.denoise;
            } catch (_) { /* Defaults work without storage. */ }
        }
        selectAudioMode(audioMode);
    }

    function selectAudioMode(mode) {
        if (!audioPreferences[mode]) return;
        audioMode = mode;
        speechFilter = audioPreferences[mode].filter;
        denoise = audioPreferences[mode].denoise;
        const filter = byId("traffic-voice-speech-filter");
        const engine = byId("traffic-voice-denoise");
        if (filter) filter.value = speechFilter;
        if (engine) engine.value = denoise;
    }

    function saveAudioPreferences() {
        audioPreferences[audioMode] = {filter: speechFilter, denoise};
        try { localStorage.setItem("sdrcc.trafficVoice.audio." + audioMode, JSON.stringify(audioPreferences[audioMode])); } catch (_) {}
        if (byId("traffic-voice-audio")?.getAttribute("src")) startAudio();
    }
    let aisAutoEnabled = false;
    let lastAutoAisMmsi = "";
    let aisZoom = 14;
    const aisZoomStorageKey = "sdrcc.trafficVoice.aisZoom";
    const vesselPhotoStorageKey = "sdrcc.trafficVoice.vesselPhotos";
    let vesselPhotosEnabled = false;
    let vesselPhotoMmsi = "";
    let vesselPhotoRequest = 0;

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

    function receiverSoftwareLabel(backend) {
        const name = String(backend?.name || "").trim();
        const version = String(backend?.version || "").trim();
        const product = name.toLowerCase() === "rtlsdr_airband"
            ? "RTLSDR-Airband"
            : displayToken(name);
        const capability = name.toLowerCase() === "rtlsdr_airband" ? " · AM/NFM" : "";
        return (product + (version ? " " + version : "") + capability).trim();
    }

    function renderAisMatch(payload) {
        const match = payload.ais_match || {};
        const detail = byId("traffic-voice-ais-match-detail");
        const button = byId("traffic-voice-show-ais-vessel");
        const statusMessages = {
            not_applicable: "AIS correlation is available in Marine Voice + AIS.",
            no_validated_atis: "Waiting for validated Marine ATIS.",
            invalid_atis: "The decoded ATIS identity is not a valid ten-digit ATIS code.",
            no_callsign: "Validated ATIS has no AIS callsign projection.",
            source_unavailable: "AIS-Catcher ships.json is currently unavailable.",
            not_found: "No exact live AIS vessel match for this ATIS.",
            ambiguous: "Multiple exact ATIS/AIS matches; no vessel selected.",
            not_validated: "Matching AIS vessel found, but AIS-Catcher has not validated it.",
            stale: "Matching AIS vessel found, but its position is stale.",
            invalid_position: "Matching AIS vessel found without a usable live position.",
        };
        if (button) {
            button.hidden = !match.matched;
            button.dataset.mmsi = match.matched ? String(match.mmsi || "") : "";
        }
        if (!detail) return;
        if (!match.matched) {
            detail.textContent = statusMessages[match.status] || "No verified AIS vessel match.";
            return;
        }

        const values = ["AIS MATCHED", "MMSI " + match.mmsi];
        const matchMethods = {
            callsign_standard: "ATIS→CALLSIGN",
            mmsi_direct: "ATIS→MMSI",
        };
        if (matchMethods[match.match_method]) {
            values.push(matchMethods[match.match_method]);
        }
        if (Number.isFinite(Number(match.distance_nm))) {
            values.push(Number(match.distance_nm).toFixed(1) + " NM");
        }
        if (Number.isFinite(Number(match.last_signal_seconds))) {
            values.push(Number(match.last_signal_seconds).toFixed(0) + " s old");
        }
        detail.textContent = values.join(" · ");
        maybeAutoFollowAis(match);
        updateGoogleImagesLink(match);
        maybeLoadVesselPhoto(match);
    }

    function initializeAisZoom() {
        const input = byId("traffic-voice-ais-zoom");
        if (!input) return;
        try {
            const saved = Number(window.localStorage.getItem(aisZoomStorageKey));
            if (Number.isInteger(saved) && saved >= 3 && saved <= 18) aisZoom = saved;
        } catch (_) { /* Zoom remains usable when browser storage is disabled. */ }
        input.value = String(aisZoom);
        input.addEventListener("change", () => {
            const value = Number(input.value);
            if (!Number.isInteger(value) || value < 3 || value > 18) {
                input.value = String(aisZoom);
                text("traffic-voice-action-message", "Enter a zoom level from 3 to 18.");
                return;
            }
            aisZoom = value;
            try { window.localStorage.setItem(aisZoomStorageKey, String(aisZoom)); } catch (_) {}
            if (aisAutoEnabled && lastAutoAisMmsi) {
                if (!window.sdrccRadioView?.updateAisAutoWindow(lastAutoAisMmsi, aisZoom)) {
                    disableAisAuto("AIS Auto stopped because its map window was closed.");
                }
            }
        });
    }

    function renderAisAutoButton() {
        const button = byId("traffic-voice-auto-ais-vessel");
        if (!button) return;
        button.textContent = aisAutoEnabled ? "Auto: on" : "Auto: off";
        button.setAttribute("aria-pressed", String(aisAutoEnabled));
        button.classList.toggle("is-active", aisAutoEnabled);
    }

    function disableAisAuto(message = "") {
        aisAutoEnabled = false;
        lastAutoAisMmsi = "";
        renderAisAutoButton();
        if (message) text("traffic-voice-action-message", message);
    }

    function toggleAisAuto() {
        if (aisAutoEnabled) {
            disableAisAuto("Automatic AIS vessel following stopped.");
            return;
        }
        const mmsi = String(byId("traffic-voice-show-ais-vessel")?.dataset.mmsi || "");
        const opened = window.sdrccRadioView?.openAisAutoWindow(mmsi, aisZoom);
        if (!opened) {
            disableAisAuto("AIS Auto needs permission to open the map window.");
            return;
        }
        aisAutoEnabled = true;
        lastAutoAisMmsi = /^\d{9}$/.test(mmsi) ? mmsi : "";
        renderAisAutoButton();
        text(
            "traffic-voice-action-message",
            lastAutoAisMmsi
                ? "AIS Auto is following the current matched vessel."
                : "AIS Auto is waiting for the next validated ATIS/AIS match.",
        );
    }

    function maybeAutoFollowAis(match) {
        if (!aisAutoEnabled) return;
        const mmsi = String(match?.mmsi || "");
        if (!/^\d{9}$/.test(mmsi) || mmsi === lastAutoAisMmsi) return;
        if (!window.sdrccRadioView?.updateAisAutoWindow(mmsi, aisZoom)) {
            disableAisAuto("AIS Auto stopped because its map window was closed.");
            return;
        }
        lastAutoAisMmsi = mmsi;
        text("traffic-voice-action-message", "AIS Auto selected MMSI " + mmsi + ".");
    }

    function renderVesselPhotoToggle() {
        const button = byId("traffic-voice-vessel-photos-toggle");
        if (!button) return;
        button.textContent = vesselPhotosEnabled ? "Ship photos: on" : "Ship photos: off";
        button.setAttribute("aria-pressed", String(vesselPhotosEnabled));
        button.classList.toggle("is-active", vesselPhotosEnabled);
    }

    function clearVesselPhoto() {
        vesselPhotoRequest += 1;
        vesselPhotoMmsi = "";
        const card = byId("traffic-voice-vessel-photo-card");
        const image = byId("traffic-voice-vessel-photo");
        if (card) card.hidden = true;
        if (image) image.removeAttribute("src");
        byId("traffic-voice-vessel-photo-link")?.removeAttribute("href");
    }

    function toggleVesselPhotos() {
        vesselPhotosEnabled = !vesselPhotosEnabled;
        try { localStorage.setItem(vesselPhotoStorageKey, vesselPhotosEnabled ? "1" : "0"); } catch (_) {}
        renderVesselPhotoToggle();
        if (!vesselPhotosEnabled) {
            clearVesselPhoto();
            text("traffic-voice-action-message", "Ship photos off; no photo lookups run.");
            return;
        }
        text("traffic-voice-action-message", "Ship photos on; lookup runs only for a validated live ATIS/AIS match.");
        maybeLoadVesselPhoto(lastPayload?.ais_match || {});
    }

    function updateGoogleImagesLink(match) {
        const link = byId("traffic-voice-google-images");
        if (!link) return;
        const mmsi = String(match?.mmsi || "");
        if (!match?.matched || !/^\d{9}$/.test(mmsi)) {
            link.hidden = true;
            link.removeAttribute("href");
            return;
        }
        const parts = [match.shipname, match.imo ? ("IMO " + match.imo) : "", "MMSI " + mmsi, "ship"].filter(Boolean);
        link.href = "https://www.google.com/search?tbm=isch&q=" + encodeURIComponent(parts.join(" "));
        link.hidden = false;
    }

    async function maybeLoadVesselPhoto(match) {
        if (!vesselPhotosEnabled) return;
        const mmsi = String(match?.mmsi || "");
        if (!match?.matched || !/^\d{9}$/.test(mmsi)) {
            clearVesselPhoto();
            return;
        }
        if (mmsi === vesselPhotoMmsi) return;
        vesselPhotoMmsi = mmsi;
        const requestId = ++vesselPhotoRequest;
        const shipname = String(match.shipname || match.callsign || "");
        const imo = String(match.imo || "");
        const card = byId("traffic-voice-vessel-photo-card");
        const image = byId("traffic-voice-vessel-photo");
        if (card) card.hidden = false;
        if (image) image.removeAttribute("src");
        byId("traffic-voice-vessel-photo-link")?.removeAttribute("href");
        text("traffic-voice-vessel-photo-name", shipname || ("MMSI " + mmsi));
        text("traffic-voice-vessel-photo-credit", "Searching vessel photo…");
        try {
            const response = await fetch(
                "/api/traffic-voice/vessel-photo?mmsi=" + encodeURIComponent(mmsi)
                + "&shipname=" + encodeURIComponent(shipname)
                + "&imo=" + encodeURIComponent(imo)
                + "&eni=" + encodeURIComponent(match.eni || ""),
                {cache: "no-store"},
            );
            const result = await response.json();
            if (requestId !== vesselPhotoRequest || !vesselPhotosEnabled) return;
            if (!card || !image) return;
            if (!response.ok || !result.ok || !result.image_url) {
                image.removeAttribute("src");
                byId("traffic-voice-vessel-photo-link")?.removeAttribute("href");
                text("traffic-voice-vessel-photo-credit",
                    result.status === "unavailable"
                        ? "Photo source temporarily unavailable."
                        : "No vessel photo found.");
                return;
            }
            image.src = result.image_url;
            image.style.objectFit = result.source === "De Binnenvaart" ? "contain" : "";
            if (result.page_url && /^(?:https:\/\/(?:(?:www\.)?binnenvaartspotter|(?:www\.)?debinnenvaart)\.nl\/|https:\/\/(?:markprummel\.nl|commons\.wikimedia\.org)\/)/.test(result.page_url)) {
                byId("traffic-voice-vessel-photo-link")?.setAttribute("href", result.page_url);
            }
            image.alt = shipname ? "Photo of " + shipname : "Photo of matched vessel";
            text("traffic-voice-vessel-photo-name", shipname || ("MMSI " + mmsi));
            const credit = byId("traffic-voice-vessel-photo-credit");
            if (credit) {
                credit.textContent = [result.source, result.artist, result.license].filter(Boolean).join(" · ") || "Wikimedia Commons";
                if (result.page_url && /^(?:https:\/\/(?:(?:www\.)?binnenvaartspotter|(?:www\.)?debinnenvaart)\.nl\/|https:\/\/(?:markprummel\.nl|commons\.wikimedia\.org)\/)/.test(result.page_url)) {
                    const original = document.createElement("a");
                    original.href = result.page_url;
                    original.target = "_blank"; original.rel = "noopener noreferrer";
                    original.textContent = "View original ↗";
                    credit.append(" · ", original);
                }
            }
        } catch (_) {
            if (requestId === vesselPhotoRequest) {
                if (card) card.hidden = false;
                if (image) image.removeAttribute("src");
                byId("traffic-voice-vessel-photo-link")?.removeAttribute("href");
                text("traffic-voice-vessel-photo-credit", "Photo lookup failed.");
            }
        }
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

    function renderMode(mode, running, focusedModeId) {
        const card = document.querySelector('[data-traffic-mode="' + mode.id + '"]');
        if (!card) return;
        card.hidden = Boolean(focusedModeId && mode.id !== focusedModeId);
        card.classList.toggle("is-selected", Boolean(mode.selected));
        card.classList.toggle("is-planned", !mode.execution_enabled);
        const state = card.querySelector("[data-traffic-mode-state]");
        if (state) {
            state.textContent = mode.execution_enabled
                ? (mode.selected ? (running ? "ACTIVE MODE" : "SELECTED · STOPPED") : "AVAILABLE")
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
        const autoGain = byId("traffic-voice-auto-gain");
        const tuningMode = byId("traffic-voice-tuning-mode");
        const squelch = byId("traffic-voice-squelch");
        const scanInterval = byId("traffic-voice-scan-interval");
        const channelFilterButton = byId("traffic-voice-channel-filter");

        if (channelFilterButton) {
            const marine = settings.mode_id === "marine_ais";
            const enabled = settings.channel_filter_enabled !== false;
            channelFilterButton.hidden = !marine;
            channelFilterButton.disabled = actionBusy || !running || !marine;
            channelFilterButton.textContent = enabled
                ? "Channel filter: ON · 15 kHz"
                : "Channel filter: OFF";
            channelFilterButton.setAttribute("aria-pressed", String(enabled));
            channelFilterButton.classList.toggle("is-open", enabled);
            channelFilterButton.title = enabled
                ? "15 kHz RF channel filter is active before NFM demodulation. Click to compare without it."
                : "RF channel filter is bypassed. Click to enable the 15 kHz pre-demod filter.";
        }

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
            if (autoGain) autoGain.checked = settings.gain_mode !== "manual";
            if (gainSelect) gainSelect.value = String(settings.gain_db ?? "28");
            if (squelch) squelch.value = String(settings.squelch_snr_db ?? "6");
            if (scanInterval) scanInterval.value = String(settings.scan_interval_ms ?? "200");
        }
        if (gainSelect) gainSelect.disabled = Boolean(autoGain?.checked);
        text(
            "traffic-voice-squelch-value",
            Number(squelch?.value || settings.squelch_snr_db || 0).toFixed(1) + " dB",
        );
        text(
            "traffic-voice-scan-interval-value",
            Math.round(Number(scanInterval?.value || settings.scan_interval_ms || 200)) + " ms/ch",
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
                : "SCAN · " + (Array.isArray(settings.scan_channel_ids) ? settings.scan_channel_ids.length : channels.length)
                    + "/" + channels.length;
        text("traffic-voice-tuning-state", tuningLabel);
        text(
            "traffic-voice-rf-settings",
            (settings.gain_mode === "manual"
                ? Number(settings.gain_db || 0).toFixed(1) + " dB"
                : Number.isFinite(Number(settings.runtime_gain_db))
                    ? "SMART " + Number(settings.runtime_gain_db).toFixed(1) + " dB fixed"
                    : "SMART GAIN")
                + " · " + Number(settings.squelch_snr_db || 0).toFixed(1) + " dB",
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
            const wrapper = document.createElement("div");
            wrapper.className = "traffic-voice-channel-wrap";

            const scanToggle = document.createElement("label");
            scanToggle.className = "traffic-voice-scan-toggle";
            scanToggle.title = selected
                ? "Include this channel in Scan all channels"
                : "Select this Voice mode before changing its scan list";
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.checked = channel.scan_enabled !== false;
            checkbox.disabled = !selected || actionBusy || !payload.ok;
            checkbox.dataset.scanChannelId = String(channel.id);
            const toggleText = document.createElement("span");
            toggleText.textContent = "Scan";
            scanToggle.append(checkbox, toggleText);
            if (selected) {
                checkbox.addEventListener("change", async event => {
                    const current = Array.isArray((lastPayload?.receiver_settings || {}).scan_channel_ids)
                        ? [...lastPayload.receiver_settings.scan_channel_ids]
                        : configured.filter(item => item.scan_enabled !== false).map(item => item.id);
                    const wanted = new Set(current.map(String));
                    if (event.target.checked) wanted.add(String(channel.id));
                    else wanted.delete(String(channel.id));
                    if (!wanted.size) {
                        event.target.checked = true;
                        text("traffic-voice-action-message", "At least one channel must remain enabled for scanning.");
                        return;
                    }
                    await applySettings({scan_channel_ids: [...wanted]});
                });
            }

            const row = document.createElement("button");
            row.type = "button";
            row.className = "traffic-voice-channel";
            row.disabled = !selected || actionBusy || !payload.ok;
            row.classList.toggle("is-scan-excluded", channel.scan_enabled === false);
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
            wrapper.append(scanToggle, row);
            container.append(wrapper);
        });
    }

    function renderActivity(payload, modes) {
        modes.forEach(mode => renderChannelBank(mode, payload));
    }

    function stopAudio() {
        const audio = byId("traffic-voice-audio");
        if (!audio) return;
        audioOperation += 1;
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        const button = byId("traffic-voice-audio-toggle");
        if (button) {
            button.textContent = "▶ Live audio";
            button.disabled = actionBusy || !audio.dataset.streamUrl;
        }
        text("traffic-voice-audio-detail", "Live audio stopped in this browser.");
    }

    async function startAudio() {
        const audio = byId("traffic-voice-audio");
        const streamUrl = audio?.dataset.streamUrl || "";
        if (!audio || !streamUrl) return;

        const operation = ++audioOperation;
        audio.volume = Number(byId("traffic-voice-volume")?.value || 0.85);
        audio.src = streamUrl + (streamUrl.includes("?") ? "&" : "?") + "live=" + Date.now()
            + "&speech_filter=" + encodeURIComponent(speechFilter)
            + "&denoise=" + encodeURIComponent(denoise) + "&mode=" + encodeURIComponent(audioMode);

        try {
            await audio.play();
            if (operation !== audioOperation) return;
            const button = byId("traffic-voice-audio-toggle");
            if (button) button.textContent = "■ Stop audio";
            text("traffic-voice-audio-detail", "Playing the live stream; no artificial duration is shown.");
        } catch (error) {
            if (operation !== audioOperation || error?.name === "AbortError") return;
            audio.removeAttribute("src");
            audio.load();
            const button = byId("traffic-voice-audio-toggle");
            if (button) {
                button.textContent = "▶ Live audio";
                button.disabled = actionBusy || !audio.dataset.streamUrl;
            }
            text("traffic-voice-audio-detail", "Browser audio could not start: " + error.message);
        }
    }

    function renderMarineRecordings(payload) {
        const section = byId("traffic-voice-recordings");
        const list = byId("traffic-voice-recordings-list");
        const status = byId("traffic-voice-recordings-status");
        if (!section || !list) return;
        const marineSelected = payload.selected_mode === "marine_ais";
        section.hidden = !marineSelected;
        if (!marineSelected) return;

        const audioState = payload.audio || {};
        const recordings = Array.isArray(audioState.marine_recordings)
            ? audioState.marine_recordings
            : [];
        const active = recordings.some(recording => !recording.complete);
        if (status) {
            status.textContent = audioState.recording_listener_error
                ? "Marine replay capture unavailable: " + audioState.recording_listener_error
                : active
                    ? "Recording the current transmission; replay is ready when it ends."
                    : recordings.length
                        ? recordings.length + " recent Marine transmission" + (recordings.length === 1 ? "" : "s") + " ready to replay."
                        : "Waiting for the next Marine transmission.";
        }

        list.replaceChildren();
        recordings.forEach(recording => {
            if (!recording || typeof recording.id !== "string") return;
            const row = document.createElement("div");
            row.className = "traffic-voice-recording";
            row.setAttribute("role", "listitem");

            const copy = document.createElement("div");
            copy.className = "traffic-voice-recording-copy";
            const channel = document.createElement("strong");
            const frequency = Number(recording.frequency_mhz);
            const frequencyLabel = Number.isFinite(frequency) ? " · " + frequency.toFixed(3) + " MHz" : "";
            channel.textContent = (recording.channel || "Marine transmission") + frequencyLabel;
            const details = document.createElement("small");
            const received = new Date(recording.received_at);
            const timeLabel = Number.isFinite(received.getTime())
                ? received.toLocaleTimeString(undefined, {hour: "2-digit", minute: "2-digit", second: "2-digit"})
                : "Time unavailable";
            const duration = Number.isFinite(Number(recording.duration_seconds))
                ? Number(recording.duration_seconds).toFixed(1) + " s"
                : "-";
            details.textContent = timeLabel + " · " + duration;
            copy.append(channel, details);

            const actions = document.createElement("div");
            actions.className = "traffic-voice-recording-actions";
            const saveButton = document.createElement("button");
            saveButton.type = "button";
            saveButton.className = "traffic-voice-button traffic-voice-recording-save";
            saveButton.textContent = "💾 Save";
            saveButton.disabled = !recording.complete;
            saveButton.addEventListener("click", async event => {
                event.stopPropagation();
                saveButton.disabled = true;
                try {
                    const response = await fetch("/api/traffic-voice/recordings/" + encodeURIComponent(recording.id) + "/save", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({
                            channel: recording.channel,
                            frequency_mhz: recording.frequency_mhz,
                            atis: lastPayload?.atis || {},
                            ais_match: lastPayload?.ais_match || {},
                        }),
                    });
                    const result = await response.json();
                    if (!response.ok || !result.ok) throw new Error(result.message || "Save failed");
                    saveButton.textContent = "✓ Saved";
                    text("traffic-voice-action-message", "Marine recording saved as " + result.filename + ".");
                } catch (error) {
                    saveButton.disabled = false;
                    text("traffic-voice-action-message", "Could not save Marine recording: " + error.message);
                }
            });

            const button = document.createElement("button");
            button.type = "button";
            button.className = "traffic-voice-button traffic-voice-recording-play";
            button.dataset.recordingId = recording.id;
            const isPlaying = playingRecordingId === recording.id;
            button.textContent = !recording.complete
                ? "Recording…"
                : (isPlaying ? "■ Stop replay" : "▶ Replay");
            button.disabled = !recording.complete || !recording.play_url;
            button.setAttribute("aria-label", (isPlaying ? "Stop replay of " : "Replay ") + channel.textContent);
            actions.append(button, saveButton);
            row.append(copy, actions);
            list.append(row);
        });
    }

    function stopRecordingReplay(resumeLive = true) {
        const replay = byId("traffic-voice-replay-audio");
        const shouldResumeLive = replayResumeLive && resumeLive;
        replayResumeLive = false;
        playingRecordingId = "";
        if (replay) {
            replay.pause();
            replay.removeAttribute("src");
            replay.load();
        }
        if (shouldResumeLive) {
            startAudio();
        } else {
            text("traffic-voice-audio-detail", "Saved Marine replay stopped.");
        }
        if (lastPayload) renderMarineRecordings(lastPayload);
    }

    async function playMarineRecording(recording) {
        const replay = byId("traffic-voice-replay-audio");
        const live = byId("traffic-voice-audio");
        if (!replay || !recording?.play_url || !recording.complete) return;
        if (playingRecordingId === recording.id) {
            stopRecordingReplay(true);
            return;
        }
        const switchingReplay = Boolean(playingRecordingId);
        const resumeLiveAfterReplay = switchingReplay
            ? replayResumeLive
            : Boolean(live?.getAttribute("src"));
        if (switchingReplay) stopRecordingReplay(false);
        replayResumeLive = resumeLiveAfterReplay;
        if (replayResumeLive) stopAudio();
        playingRecordingId = recording.id;
        replay.volume = Number(byId("traffic-voice-volume")?.value || 0.85);
        replay.src = recording.play_url + "?replay=" + Date.now();
        text("traffic-voice-audio-detail", "Replaying a saved Marine transmission.");
        if (lastPayload) renderMarineRecordings(lastPayload);
        try {
            await replay.play();
        } catch (error) {
            if (error?.name === "AbortError") return;
            text("traffic-voice-audio-detail", "Replay could not start: " + error.message);
            stopRecordingReplay(true);
        }
    }

    function renderAudio(payload) {
        const audio = byId("traffic-voice-audio");
        const button = byId("traffic-voice-audio-toggle");
        const audioState = payload.audio || {};
        const modeChanged = payload.selected_mode !== audioMode && Boolean(audioPreferences[payload.selected_mode]);
        if (modeChanged && playingRecordingId) stopRecordingReplay(false);
        const wasListening = Boolean(audio?.getAttribute("src"));
        if (modeChanged) selectAudioMode(payload.selected_mode);
        const engineSelect = byId("traffic-voice-denoise");
        if (engineSelect) {
            for (const option of engineSelect.options) {
                const available = option.value === "off" || audioState.denoisers?.[option.value]?.available;
                option.disabled = !available;
            }
        }
        const capability = audioState.denoisers?.[denoise];
        const warning = denoise !== "off" && (!capability?.available || capability?.last_error);
        text("traffic-voice-processing-detail", warning
            ? "Noise reduction unavailable or failed; speech filter remains active. Check audio dependencies."
            : (audioMode === "marine_ais" ? "Marine" : "Airband") + " preferences · ATIS input unchanged");
        text("traffic-voice-audio-state", audioState.stream_state || "WAITING");
        if (!audio) return;
        audio.dataset.streamUrl = audioState.stream_url || "";
        if (modeChanged && wasListening && audioState.stream_url) startAudio();

        const browserListening = Boolean(audio.getAttribute("src"));
        const voiceRunning = Boolean((payload.service || {}).active);
        if (button) {
            button.textContent = browserListening ? "■ Stop audio" : "▶ Live audio";
            // A running browser stream must always remain stoppable, even when
            // the backend temporarily reports no fresh packet during silence.
            button.disabled = actionBusy || (!browserListening && !audioState.stream_url);
        }
        if (!voiceRunning && browserListening) stopAudio();
        if (!audioState.stream_url && !browserListening) {
            text("traffic-voice-audio-detail", "Start Voice and wait for the local audio stream.");
        } else if (!audioState.stream_url && browserListening) {
            text("traffic-voice-audio-detail", "Live audio is waiting for the next receiver packet.");
        }
    }

    function renderChannelListControls() {
        // Channel lists are configuration and do not require a running receiver.
        ["traffic-voice-channel-list-load", "traffic-voice-channel-list-export"]
            .forEach(id => {
                const button = byId(id);
                if (button) button.disabled = actionBusy;
            });
    }

    function render(payload) {
        renderChannelListControls();
        lastPayload = payload;
        const status = byId("traffic-voice-status");
        const serviceBadge = byId("traffic-voice-service-state");
        const assignmentBadge = byId("traffic-voice-assignment-state");
        const message = byId("traffic-voice-contract-message");
        const assignment = payload.assignment || {};
        const modes = Array.isArray(payload.modes) ? payload.modes : [];
        const selected = selectedMode(payload);
        const running = Boolean((payload.service || {}).active);
        const focusedModeId = running && ["marine_ais", "airband_adsb"].includes(selected.id)
            ? selected.id
            : "";
        const modeGrid = document.querySelector(".traffic-voice-mode-grid");
        if (modeGrid) modeGrid.classList.toggle("is-mode-focused", Boolean(focusedModeId));

        if (status) {
            status.textContent = payload.ok
                ? "MARINE + AIRBAND READY"
                : "ATTENTION";
            status.classList.toggle("is-foundation", Boolean(payload.ok));
            status.classList.toggle("is-attention", !payload.ok);
        }
        if (serviceBadge) {
            serviceBadge.textContent = running
                ? (selected.id === "airband_adsb" ? "AIRBAND RUNNING" : "MARINE RUNNING")
                : "VOICE STOPPED";
            serviceBadge.classList.toggle("is-valid", running);
            serviceBadge.classList.toggle("is-offline", !running);
        }

        modes.forEach(mode => renderMode(mode, running, focusedModeId));
        renderSettings(payload, running);
        renderActivity(payload, modes);
        renderAudio(payload);
        renderMarineRecordings(payload);

        text("traffic-voice-selected-mode", selected.label || displayToken(payload.selected_mode));
        text("traffic-voice-voice-receiver", receiverLabel(assignment.voice_receiver));
        text("traffic-voice-context-receiver", receiverLabel(assignment.context_receiver));
        text("traffic-voice-backend", receiverSoftwareLabel(payload.backend || {}));
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
        renderAisMatch(payload);

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
            const switchingToAirband = running && selected.id === "marine_ais";
            start.textContent = switchingToAirband
                ? "Switch to Airband + ADS-B"
                : "Start Marine + AIS";
            start.classList.toggle("is-start", !switchingToAirband);
            start.classList.toggle("is-airband", switchingToAirband);
            start.disabled = actionBusy || !payload.ok || (running && selected.id !== "marine_ais");
        }
        if (startAirband) {
            const switchingToMarine = running && selected.id === "airband_adsb";
            startAirband.textContent = switchingToMarine
                ? "Switch to Marine + AIS"
                : "Start Airband + ADS-B";
            startAirband.classList.toggle("is-start", switchingToMarine);
            startAirband.classList.toggle("is-airband", !switchingToMarine);
            startAirband.disabled = actionBusy || !payload.ok || (running && selected.id !== "airband_adsb");
        }
        if (stop) stop.disabled = actionBusy || !running;
    }

    function renderError(error) {
        const status = byId("traffic-voice-status");
        const mapButton = byId("traffic-voice-show-ais-vessel");
        if (status) {
            status.textContent = "UNAVAILABLE";
            status.classList.remove("is-foundation");
            status.classList.add("is-attention");
        }
        if (mapButton) mapButton.hidden = true;
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
            renderChannelListControls();
            await refresh(true);
        }
        return succeeded;
    }

    function formSettings() {
        return {
            tuning_mode: byId("traffic-voice-tuning-mode")?.value || "scan",
            selected_channel_id: byId("traffic-voice-channel-select")?.value || "",
            gain_mode: byId("traffic-voice-auto-gain")?.checked ? "smart" : "manual",
            auto_gain: Boolean(byId("traffic-voice-auto-gain")?.checked),
            gain_db: Number(byId("traffic-voice-gain")?.value || 0),
            squelch_snr_db: Number(byId("traffic-voice-squelch")?.value || 0),
            scan_interval_ms: Number(byId("traffic-voice-scan-interval")?.value || 200),
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

    function showAisVessel() {
        const button = byId("traffic-voice-show-ais-vessel");
        const mmsi = String(button?.dataset.mmsi || "");
        const opened = window.sdrccRadioView?.openAisVessel(mmsi, aisZoom);
        if (!opened) {
            text("traffic-voice-action-message", "AIS map could not open this vessel.");
        }
    }

    function exportChannelList() { window.location.href = channelListExportEndpoint; }

    async function importChannelList(file) {
        if (!file) return;
        const form = new FormData(); form.append("file", file, file.name);
        text("traffic-voice-action-message", "Validating Excel channel list…");
        try {
            const response = await fetch(channelListImportEndpoint, {method: "POST", body: form, cache: "no-store"});
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload.ok === false) throw new Error(payload.message || `HTTP ${response.status}`);
            settingsDirty = false; channelSignature = ""; lastPayload = payload.snapshot || lastPayload;
            text("traffic-voice-action-message", `Loaded ${payload.marine_channels} Marine and ${payload.aviation_channels} Aviation channels.`);
            await refresh(true);
        } catch (error) {
            text("traffic-voice-action-message", "Excel import rejected: " + error.message);
        } finally {
            const input = byId("traffic-voice-channel-list-file"); if (input) input.value = "";
        }
    }

    function initialize() {
        loadAudioPreferences();
        byId("traffic-voice-speech-filter")?.addEventListener("change", event => {
            if (!speechFilterOptions.includes(event.target.value)) return;
            speechFilter = event.target.value;
            saveAudioPreferences();
        });
        byId("traffic-voice-denoise")?.addEventListener("change", event => {
            if (!["off", "speex", "rnnoise"].includes(event.target.value)) return;
            denoise = event.target.value;
            saveAudioPreferences();
        });
        initializeAisZoom();
        document.querySelector('.tab-button[data-tab="traffic-voice"]')
            ?.addEventListener("click", () => window.setTimeout(() => refresh(true), 0));
        byId("traffic-voice-start")?.addEventListener("click", () => {
            const activeMode = selectedMode(lastPayload || {}).id;
            const switching = Boolean(lastPayload?.service?.active) && activeMode === "marine_ais";
            runAction(switching ? "start_airband" : "start_marine");
        });
        byId("traffic-voice-start-airband")?.addEventListener("click", () => {
            const activeMode = selectedMode(lastPayload || {}).id;
            const switching = Boolean(lastPayload?.service?.active) && activeMode === "airband_adsb";
            runAction(switching ? "start_marine" : "start_airband");
        });
        byId("traffic-voice-stop")
            ?.addEventListener("click", () => runAction("stop"));
        byId("traffic-voice-show-ais-vessel")
            ?.addEventListener("click", showAisVessel);
        byId("traffic-voice-auto-ais-vessel")
            ?.addEventListener("click", toggleAisAuto);
        try { vesselPhotosEnabled = localStorage.getItem(vesselPhotoStorageKey) === "1"; } catch (_) {}
        renderVesselPhotoToggle();
        byId("traffic-voice-vessel-photos-toggle")
            ?.addEventListener("click", toggleVesselPhotos);
        byId("traffic-voice-apply-settings")
            ?.addEventListener("click", () => applySettings());
        byId("traffic-voice-channel-list-export")?.addEventListener("click", exportChannelList);
        byId("traffic-voice-channel-list-load")?.addEventListener("click", () => byId("traffic-voice-channel-list-file")?.click());
        byId("traffic-voice-channel-list-file")?.addEventListener("change", event => importChannelList(event.target.files?.[0]));
        byId("traffic-voice-open-squelch")?.addEventListener("click", async () => {
            const open = Boolean((lastPayload?.receiver_settings || {}).open_squelch);
            await applySettings({open_squelch: !open});
            if (!open) await startAudio();
        });
        byId("traffic-voice-audio-toggle")?.addEventListener("click", () => {
            const audio = byId("traffic-voice-audio");
            if (audio?.getAttribute("src")) stopAudio();
            else {
                if (playingRecordingId) stopRecordingReplay(false);
                startAudio();
            }
        });
        byId("traffic-voice-recordings-list")?.addEventListener("click", event => {
            const button = event.target.closest("button[data-recording-id]");
            if (!button || button.disabled) return;
            const recording = (lastPayload?.audio?.marine_recordings || [])
                .find(item => item.id === button.dataset.recordingId);
            if (recording) playMarineRecording(recording);
        });
        byId("traffic-voice-channel-filter")?.addEventListener("click", async () => {
            const settings = lastPayload?.receiver_settings || {};
            if (settings.mode_id !== "marine_ais") return;
            await applySettings({
                channel_filter_enabled: settings.channel_filter_enabled === false,
            });
        });
        byId("traffic-voice-volume")?.addEventListener("input", event => {
            const audio = byId("traffic-voice-audio");
            if (audio) audio.volume = Number(event.target.value);
            const replay = byId("traffic-voice-replay-audio");
            if (replay) replay.volume = Number(event.target.value);
        });
        const replayAudio = byId("traffic-voice-replay-audio");
        ["ended", "error"].forEach(eventName => replayAudio?.addEventListener(eventName, () => {
            if (!playingRecordingId) return;
            stopRecordingReplay(true);
        }));
        const liveAudio = byId("traffic-voice-audio");
        ["ended", "error"].forEach(eventName => liveAudio?.addEventListener(eventName, () => {
            if (!liveAudio.getAttribute("src")) return;
            audioOperation += 1;
            liveAudio.removeAttribute("src");
            liveAudio.load();
            const button = byId("traffic-voice-audio-toggle");
            if (button) {
                button.textContent = "▶ Live audio";
                button.disabled = actionBusy || !liveAudio.dataset.streamUrl;
            }
            text(
                "traffic-voice-audio-detail",
                "Live audio stream ended; click Live audio to reconnect.",
            );
        }));
        ["traffic-voice-tuning-mode", "traffic-voice-channel-select", "traffic-voice-gain"]
            .forEach(id => byId(id)?.addEventListener("change", () => { settingsDirty = true; }));
        byId("traffic-voice-auto-gain")?.addEventListener("change", event => {
            settingsDirty = true;
            const gain = byId("traffic-voice-gain");
            if (gain) gain.disabled = Boolean(event.target.checked);
        });
        byId("traffic-voice-squelch")?.addEventListener("input", event => {
            settingsDirty = true;
            text("traffic-voice-squelch-value", Number(event.target.value).toFixed(1) + " dB");
        });
        byId("traffic-voice-scan-interval")?.addEventListener("input", event => {
            settingsDirty = true;
            text("traffic-voice-scan-interval-value", Math.round(Number(event.target.value)) + " ms/ch");
        });
        document.addEventListener("visibilitychange", refresh);
        refreshTimer = window.setInterval(refresh, 3000);
        renderAisAutoButton();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
        initialize();
    }

    window.addEventListener("beforeunload", () => {
        if (refreshTimer !== null) window.clearInterval(refreshTimer);
        stopRecordingReplay(false);
        stopAudio();
    }, {once: true});
})();
