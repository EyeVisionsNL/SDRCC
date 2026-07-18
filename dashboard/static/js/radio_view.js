(() => {
    "use strict";

    const ACTIVE_PHASES = new Set([
        "LOCK RECEIVER",
        "RECORDING",
        "DECODING",
        "PROCESSING",
        "ARCHIVING",
    ]);

    const byId = (id) => document.getElementById(id);

    function buildViewerUrls() {
        const hostname = window.location.hostname;
        const protocol = window.location.protocol === "https:" ? "https:" : "http:";
        return {
            adsb: `${protocol}//${hostname}/tar1090/`,
            ais: `${protocol}//${hostname}:8100/`,
        };
    }

    function configureViewer(name, url) {
        const frame = byId(`radio-view-${name}-frame`);
        const button = byId(`radio-view-${name}-open`);
        const badge = byId(`radio-view-${name}-state`);
        const error = byId(`radio-view-${name}-error`);

        if (!frame || !button || !badge || !error) return;

        button.href = url;
        frame.src = url;

        let settled = false;
        const timeout = window.setTimeout(() => {
            if (settled) return;
            badge.textContent = "No Response";
            badge.classList.add("is-offline");
        }, 10000);

        frame.addEventListener("load", () => {
            settled = true;
            window.clearTimeout(timeout);
            error.classList.add("hidden");
            badge.textContent = "Online";
            badge.classList.remove("is-offline");
            badge.classList.add("is-online");
        });

        frame.addEventListener("error", () => {
            settled = true;
            window.clearTimeout(timeout);
            error.classList.remove("hidden");
            badge.textContent = "Offline";
            badge.classList.remove("is-online");
            badge.classList.add("is-offline");
        });
    }

    function formatPass(passData) {
        if (!passData || typeof passData !== "object") {
            return ["No next pass available", "Ground track integration is ready."];
        }

        const name = passData.name || passData.satellite || "Next Satellite";
        const detail = [];
        if (passData.start_time) detail.push(passData.start_time);
        if (passData.max_elevation != null) detail.push(`max. ${passData.max_elevation}°`);
        if (passData.azimuth != null) detail.push(`azimut ${passData.azimuth}°`);

        return [name, detail.join(" · ") || "Ground track integration is ready."];
    }

    async function fetchJson(url) {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
        return response.json();
    }

    async function updateSatelliteView() {
        const badge = byId("radio-view-satellite-state");
        const overallStatus = byId("radio-view-status");
        const subtitle = byId("radio-view-satellite-subtitle");
        const groundTrack = byId("radio-view-ground-track");
        const liveWrap = byId("radio-view-live-image-wrap");
        const image = byId("radio-view-live-image");
        const imageWait = byId("radio-view-live-image-wait");
        const nextName = byId("radio-view-next-satellite");
        const nextDetail = byId("radio-view-next-pass-detail");

        if (!badge || !groundTrack || !liveWrap) return;

        try {
            const [mission, capture, status, planning] = await Promise.all([
                fetchJson("/api/mission-engine"),
                fetchJson("/api/capture-status"),
                fetchJson("/api/status"),
                fetchJson("/api/mission-queue?limit=20&hours=48"),
            ]);

            const phase = String(mission.state || mission.phase || "").toUpperCase();
            const active = ACTIVE_PHASES.has(phase) && mission.active_job;

            if (active) {
                groundTrack.classList.add("hidden");
                liveWrap.classList.remove("hidden");
                badge.textContent = phase;
                badge.classList.add("is-online");
                subtitle.textContent = "Live image from the active mission";
                overallStatus.textContent = `Live Mission · ${phase}`;
                overallStatus.classList.add("is-live");

                const latest = capture.available ? capture.latest_capture : null;
                const activeMissionId = mission.active_job && mission.active_job.mission_id;
                const belongsToActiveMission = latest && activeMissionId && latest.mission_id === activeMissionId;

                if (belongsToActiveMission && latest.url) {
                    image.src = `${latest.url}?t=${Date.now()}`;
                    image.classList.remove("hidden");
                    imageWait.classList.add("hidden");
                } else {
                    image.removeAttribute("src");
                    image.classList.add("hidden");
                    imageWait.classList.remove("hidden");
                }
                return;
            }

            liveWrap.classList.add("hidden");
            groundTrack.classList.remove("hidden");
            badge.textContent = "Ground Track";
            badge.classList.remove("is-online");
            subtitle.textContent = "Next pass and future ground track";
            overallStatus.textContent = "Stand-by";
            overallStatus.classList.remove("is-live");

            const plannedPass = Array.isArray(planning.queue) && planning.queue.length
                ? planning.queue[0]
                : status.next_pass;
            const [name, detail] = formatPass(plannedPass);
            const missionType = String(plannedPass?.mission_type || "WEATHER").toUpperCase();
            nextName.textContent = `${missionType === "VOICE" ? "🎙 " : ""}${name}`;
            nextDetail.textContent = `${missionType} · ${detail}`;
        } catch (error) {
            console.warn("Radio View update mislukt:", error);
            badge.textContent = "No Data";
            badge.classList.add("is-offline");
            overallStatus.textContent = "Check Connection";
        }
    }

    function openInternalTab(event) {
        const link = event.target.closest("[data-open-tab]");
        if (!link) return;
        event.preventDefault();
        const tabName = link.dataset.openTab;
        const button = document.querySelector(`.tab-button[data-tab="${tabName}"]`);
        if (button) button.click();
    }

    function initialize() {
        const urls = buildViewerUrls();
        configureViewer("adsb", urls.adsb);
        configureViewer("ais", urls.ais);
        document.addEventListener("click", openInternalTab);
        updateSatelliteView();
        window.setInterval(updateSatelliteView, 5000);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
