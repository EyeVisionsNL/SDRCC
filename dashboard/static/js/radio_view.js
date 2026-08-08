(() => {
    "use strict";

    const SVG_NS = "http://www.w3.org/2000/svg";
    const ACTIVE_PHASES = new Set([
        "LOCK RECEIVER",
        "RECORDING",
        "DECODING",
        "PROCESSING",
        "ARCHIVING",
    ]);
    const SATELLITE_STYLE = {
        iss: { label: "ISS", color: "#facc15", labelOffset: [-42, -14] },
        meteor_m2_3: { label: "M2-3", color: "#38d9ff", labelOffset: [12, -14] },
        meteor_m2_4: { label: "M2-4", color: "#b99cff", labelOffset: [12, 23] },
    };

    const byId = (id) => document.getElementById(id);
    let latestTracking = null;
    let latestMission = null;
    let latestQueue = null;
    let selectedSatelliteKey = null;
    let lastQueueFetchMs = 0;

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
            badge.textContent = "No response";
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

    async function fetchJson(url) {
        const response = await fetch(url, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) {
            throw new Error(payload.error || payload.message || `${url}: HTTP ${response.status}`);
        }
        return payload;
    }

    async function fetchMissionQueue() {
        const now = Date.now();
        if (latestQueue && now - lastQueueFetchMs < 30000) return latestQueue;
        const queue = await fetchJson("/api/mission-queue?limit=10&hours=48");
        lastQueueFetchMs = now;
        latestQueue = queue;
        return queue;
    }

    function svgElement(name, attributes = {}) {
        const element = document.createElementNS(SVG_NS, name);
        Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
        return element;
    }

    function project(longitude, latitude) {
        const normalizedLongitude = ((Number(longitude) + 180) % 360 + 360) % 360 - 180;
        const safeLatitude = Math.max(-90, Math.min(90, Number(latitude)));
        return [
            (normalizedLongitude + 180) * (1000 / 360),
            (90 - safeLatitude) * (500 / 180),
        ];
    }

    function pathData(points) {
        return (points || []).map((point, index) => {
            const [x, y] = project(point[0], point[1]);
            return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
        }).join(" ");
    }

    function clearGroup(id) {
        const group = byId(id);
        if (group) group.replaceChildren();
        return group;
    }

    function satelliteKeyForName(name) {
        const value = String(name || "").toUpperCase();
        if (value.includes("ISS")) return "iss";
        if (value.includes("M2 3") || value.includes("M2-3")) return "meteor_m2_3";
        if (value.includes("M2 4") || value.includes("M2-4")) return "meteor_m2_4";
        return null;
    }

    function styleFor(key) {
        return SATELLITE_STYLE[key] || { label: key, color: "#7dd3fc", labelOffset: [12, -14] };
    }

    function appendPaths(group, segments, className, satellite) {
        if (!group) return;
        const style = styleFor(satellite.key);
        (segments || []).forEach((segment) => {
            if (!Array.isArray(segment) || segment.length < 2) return;
            const path = svgElement("path", {
                d: pathData(segment),
                class: `${className}${satellite.key === selectedSatelliteKey ? " is-selected" : ""}`,
                "data-satellite-key": satellite.key,
            });
            path.style.setProperty("--satellite-color", style.color);
            group.append(path);
        });
    }

    function selectSatellite(key) {
        const available = (latestTracking?.satellites || []).some((satellite) => satellite.key === key);
        if (!available) return;
        selectedSatelliteKey = key;
        renderSatelliteMap(latestTracking, latestMission, latestQueue);
    }

    function appendSatelliteMarker(group, satellite, activeKey) {
        if (!group) return;
        const style = styleFor(satellite.key);
        const [x, y] = project(satellite.position.longitude, satellite.position.latitude);
        const classes = ["radio-view-map-marker"];
        if (satellite.key === selectedSatelliteKey) classes.push("is-selected");
        if (satellite.observer.above_horizon) classes.push("is-visible");
        if (satellite.key === activeKey) classes.push("is-mission-active");
        const marker = svgElement("g", {
            class: classes.join(" "),
            transform: `translate(${x.toFixed(2)} ${y.toFixed(2)})`,
            tabindex: "0",
            role: "button",
            "aria-label": `Select ${satellite.name}`,
        });
        marker.style.setProperty("--satellite-color", style.color);
        marker.append(svgElement("circle", { cx: 0, cy: 0, r: satellite.key === activeKey ? 10 : 8 }));
        const label = svgElement("text", {
            x: style.labelOffset[0],
            y: style.labelOffset[1],
        });
        label.textContent = style.label;
        marker.append(label);
        const title = svgElement("title");
        title.textContent = `${satellite.name} · ${satellite.position.latitude.toFixed(2)}°, ${satellite.position.longitude.toFixed(2)}° · elevation ${satellite.observer.elevation_deg.toFixed(1)}°`;
        marker.append(title);
        marker.addEventListener("click", () => selectSatellite(satellite.key));
        marker.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                selectSatellite(satellite.key);
            }
        });
        group.append(marker);
    }

    function appendStationMarker(group, station) {
        if (!group || !station) return;
        const [x, y] = project(station.longitude, station.latitude);
        const marker = svgElement("g", {
            class: "radio-view-home-marker",
            transform: `translate(${x.toFixed(2)} ${y.toFixed(2)})`,
        });
        marker.append(svgElement("circle", { cx: 0, cy: 0, r: 7 }));
        const label = svgElement("text", { x: 11, y: -10 });
        label.textContent = "HOME";
        marker.append(label);
        const title = svgElement("title");
        title.textContent = `${station.location} · ${Number(station.latitude).toFixed(4)}°, ${Number(station.longitude).toFixed(4)}°`;
        marker.append(title);
        group.append(marker);
    }

    function usableQueueItems(queue) {
        const nowEpoch = Date.now() / 1000;
        return (queue?.queue || [])
            .filter((item) => !item.skipped && String(item.status || "").toUpperCase() !== "SKIPPED")
            .filter((item) => Number(item.end_epoch || item.start_epoch || 0) >= nowEpoch)
            .sort((first, second) => Number(first.start_epoch || 0) - Number(second.start_epoch || 0));
    }

    function nextPlannedMission(queue) {
        const items = usableQueueItems(queue);
        return items.find((item) => ["IN PROGRESS", "TARGET", "NEXT"].includes(String(item.status || "").toUpperCase())) || items[0] || null;
    }

    function formatMissionTime(epoch) {
        if (!Number.isFinite(Number(epoch))) return "-";
        const date = new Date(Number(epoch) * 1000);
        const day = date
            .toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" })
            .replace(",", "");
        const time = date.toLocaleTimeString("en-GB", {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
        });
        return `${day} ${time}`;
    }

    function updateNextMission(queue) {
        const name = byId("radio-view-next-satellite");
        const detail = byId("radio-view-next-pass-detail");
        if (!name || !detail) return;
        const next = nextPlannedMission(queue);
        if (!next) {
            name.textContent = "No planned mission";
            detail.textContent = "Mission Queue has no active entry.";
            return;
        }
        name.textContent = next.name || next.satellite || "Satellite mission";
        const values = [formatMissionTime(next.start_epoch)];
        if (next.max_elevation != null) values.push(`max ${Number(next.max_elevation).toFixed(1)}°`);
        if (next.frequency_mhz != null) values.push(`${Number(next.frequency_mhz).toFixed(3)} MHz`);
        detail.textContent = values.join(" · ");
    }

    function updateSelectedDetail(snapshot) {
        const state = byId("radio-view-selected-state");
        const name = byId("radio-view-selected-name");
        const detail = byId("radio-view-selected-detail");
        const selected = (snapshot.satellites || []).find((satellite) => satellite.key === selectedSatelliteKey);
        if (!state || !name || !detail || !selected) return;
        const visible = Boolean(selected.observer.above_horizon);
        state.textContent = visible ? "ABOVE HORIZON" : "BELOW HORIZON";
        state.classList.toggle("is-visible", visible);
        name.textContent = selected.name;
        detail.textContent = [
            `elev. ${Number(selected.observer.elevation_deg).toFixed(1)}°`,
            `az. ${Number(selected.observer.azimuth_deg).toFixed(1)}°`,
            `${Math.round(Number(selected.observer.range_km))} km range`,
            `${Math.round(Number(selected.position.altitude_km))} km altitude`,
        ].join(" · ");
    }

    function updateSelector(snapshot) {
        const available = new Set((snapshot.satellites || []).map((satellite) => satellite.key));
        document.querySelectorAll(".radio-view-satellite-selector [data-satellite-key]").forEach((button) => {
            const key = button.dataset.satelliteKey;
            const style = styleFor(key);
            button.style.setProperty("--satellite-color", style.color);
            button.classList.toggle("is-active", key === selectedSatelliteKey);
            button.classList.toggle("is-unavailable", !available.has(key));
            button.disabled = !available.has(key);
        });
    }

    function renderSatelliteMap(snapshot, mission, queue) {
        const footprints = clearGroup("radio-view-satellite-footprints");
        const tracks = clearGroup("radio-view-satellite-tracks");
        const markers = clearGroup("radio-view-satellite-markers");
        const stationMarker = clearGroup("radio-view-station-marker");
        const satellites = snapshot?.satellites || [];
        const activeName = mission?.active_job?.satellite || mission?.active_job?.name;
        const phase = String(mission?.state || mission?.phase || "").toUpperCase();
        const activeKey = ACTIVE_PHASES.has(phase) ? satelliteKeyForName(activeName) : null;
        const nextKey = satelliteKeyForName(nextPlannedMission(queue)?.name);

        if (!satellites.some((satellite) => satellite.key === selectedSatelliteKey)) {
            selectedSatelliteKey = activeKey || nextKey || satellites[0]?.key || null;
        }

        const drawOrder = [...satellites].sort((first, second) => {
            return Number(first.key === selectedSatelliteKey) - Number(second.key === selectedSatelliteKey);
        });
        drawOrder.forEach((satellite) => {
            appendPaths(footprints, satellite.footprint?.segments, "radio-view-footprint", satellite);
            appendPaths(tracks, satellite.ground_track?.past, "radio-view-orbit-track is-past", satellite);
            appendPaths(tracks, satellite.ground_track?.future, "radio-view-orbit-track is-future", satellite);
        });
        drawOrder.forEach((satellite) => appendSatelliteMarker(markers, satellite, activeKey));
        appendStationMarker(stationMarker, snapshot.station);

        const stationName = byId("radio-view-station-name");
        const mapAge = byId("radio-view-map-age");
        if (stationName) stationName.textContent = `HOME · ${snapshot.station?.location || "Station"}`;
        if (mapAge) {
            const generated = new Date(Number(snapshot.generated_epoch) * 1000);
            const time = generated.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            mapAge.textContent = `Updated ${time} · TLE ${String(snapshot.tle?.state || "unknown").toUpperCase()}`;
        }
        updateSelector(snapshot);
        updateSelectedDetail(snapshot);
        updateNextMission(queue);
    }

    async function updateSatelliteView() {
        const badge = byId("radio-view-satellite-state");
        const overallStatus = byId("radio-view-status");
        const errorPanel = byId("radio-view-satellite-error");
        try {
            const [tracking, mission, queue] = await Promise.all([
                fetchJson("/api/satellite-view"),
                fetchJson("/api/mission-engine").catch(() => ({})),
                fetchMissionQueue().catch(() => latestQueue || { queue: [] }),
            ]);
            latestTracking = tracking;
            latestMission = mission;
            latestQueue = queue;
            renderSatelliteMap(tracking, mission, queue);
            errorPanel?.classList.add("hidden");

            const phase = String(mission.state || mission.phase || "").toUpperCase();
            const active = ACTIVE_PHASES.has(phase) && mission.active_job;
            if (active) {
                badge.textContent = phase;
                overallStatus.textContent = `Live mission · ${phase}`;
                overallStatus.classList.add("is-live");
            } else {
                badge.textContent = tracking.tle?.stale
                    ? "TLE STALE"
                    : `${tracking.satellites.length} TRACKED`;
                overallStatus.textContent = "Live overview";
                overallStatus.classList.remove("is-live");
            }
            badge.classList.toggle("is-online", !tracking.tle?.stale);
            badge.classList.toggle("is-offline", Boolean(tracking.tle?.stale));
        } catch (error) {
            console.warn("Radio View satellite update failed:", error);
            badge.textContent = "No orbital data";
            badge.classList.remove("is-online");
            badge.classList.add("is-offline");
            errorPanel?.classList.remove("hidden");
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
        document.querySelectorAll(".radio-view-satellite-selector [data-satellite-key]").forEach((button) => {
            button.addEventListener("click", () => selectSatellite(button.dataset.satelliteKey));
        });
        document.querySelector('.tab-button[data-tab="radio-view"]')?.addEventListener("click", () => {
            window.setTimeout(updateSatelliteView, 0);
        });
        updateSatelliteView();
        window.setInterval(() => {
            if (byId("tab-radio-view")?.classList.contains("active")) updateSatelliteView();
        }, 10000);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
