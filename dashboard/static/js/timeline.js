const EVENT_API_URL = "/api/events";
const EVENT_REFRESH_MS = 1000;
const MAX_EVENTS = 100;
const BOTTOM_TOLERANCE_PX = 36;

let eventTimelineStarted = false;
let eventTimelineTimer = null;
let renderedSignature = "";
let activeFilter = "ALL";
let latestEvents = [];

const CATEGORY_ICONS = {
    SYSTEM: "⚙️",
    SCHEDULER: "⏰",
    PREFLIGHT: "✅",
    MISSION: "🛰️",
    RECEIVER: "🎛️",
    SATDUMP: "📡"
};

const FILTERS = [
    ["ALL", "Alles"],
    ["MISSION", "🛰 Mission"],
    ["SATDUMP", "📡 SatDump"],
    ["RECEIVER", "🎛 Receiver"],
    ["PREFLIGHT", "✅ Preflight"],
    ["SCHEDULER", "⏰ Scheduler"],
    ["SYSTEM", "⚙ System"]
];

export function updateLiveLog(lines) {
    const logElement = document.getElementById("live-log");
    if (!logElement) return;

    if (!lines || lines.length === 0) {
        logElement.textContent = "Geen logregels.";
        return;
    }

    logElement.textContent = lines.join("\n");
    logElement.scrollTop = logElement.scrollHeight;
}

export function updateMissionTimeline() {
    startEventTimeline();
}

export function startEventTimeline() {
    if (eventTimelineStarted) return;

    const timeline = document.getElementById("mission-timeline");
    if (!timeline) return;

    setupFilters();
    eventTimelineStarted = true;
    refreshEventTimeline();
    eventTimelineTimer = window.setInterval(refreshEventTimeline, EVENT_REFRESH_MS);

    window.addEventListener("beforeunload", () => {
        if (eventTimelineTimer !== null) {
            window.clearInterval(eventTimelineTimer);
            eventTimelineTimer = null;
        }
    }, {once: true});
}

function setupFilters() {
    const toolbar = document.getElementById("timeline-filters");
    if (!toolbar || toolbar.dataset.ready === "true") return;

    toolbar.replaceChildren();

    for (const [value, label] of FILTERS) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "timeline-filter";
        button.dataset.filter = value;
        button.textContent = label;
        button.setAttribute("aria-pressed", value === activeFilter ? "true" : "false");
        button.addEventListener("click", () => {
            activeFilter = value;
            renderedSignature = "";
            updateFilterButtons(toolbar);
            renderEvents(document.getElementById("mission-timeline"), latestEvents, true);
        });
        toolbar.appendChild(button);
    }

    toolbar.dataset.ready = "true";
}

function updateFilterButtons(toolbar) {
    for (const button of toolbar.querySelectorAll(".timeline-filter")) {
        button.setAttribute("aria-pressed", button.dataset.filter === activeFilter ? "true" : "false");
    }
}

async function refreshEventTimeline() {
    const timeline = document.getElementById("mission-timeline");
    if (!timeline) return;

    try {
        const response = await fetch(`${EVENT_API_URL}?limit=${MAX_EVENTS}`, {cache: "no-store"});
        if (!response.ok) throw new Error(`Event API gaf HTTP ${response.status}`);

        const payload = await response.json();
        latestEvents = Array.isArray(payload.events) ? payload.events : [];
        renderEvents(timeline, latestEvents);
    } catch (error) {
        console.error("Event Timeline update mislukt:", error);
        showTimelineError(timeline);
    }
}

function renderEvents(timeline, apiEvents, force = false) {
    if (!timeline) return;

    const wasNearBottom = isNearBottom(timeline);
    const events = apiEvents
        .filter(event => event && typeof event === "object")
        .slice(0, MAX_EVENTS)
        .reverse()
        .filter(event => activeFilter === "ALL" || normalizeToken(event.category, "SYSTEM") === activeFilter);

    const signature = `${activeFilter}|${events.map(event => String(event.id || "")).join("|")}`;
    if (!force && renderedSignature === signature) return;
    renderedSignature = signature;

    const expandedIds = new Set(
        Array.from(timeline.querySelectorAll(".timeline-item.is-expanded"))
            .map(item => item.dataset.eventId)
    );

    timeline.replaceChildren();

    if (events.length === 0) {
        timeline.appendChild(createEmptyState(activeFilter === "ALL" ? "Nog geen operator-events." : "Geen events binnen dit filter."));
        return;
    }

    const list = document.createElement("div");
    list.className = "timeline-list";

    let previousMissionId = null;
    for (const event of events) {
        const item = createEventItem(event);
        const missionId = extractMissionId(event);

        if (missionId) {
            item.dataset.missionId = missionId;
            if (missionId === previousMissionId) item.classList.add("mission-continuation");
            previousMissionId = missionId;
        } else {
            previousMissionId = null;
        }

        if (expandedIds.has(String(event.id || ""))) {
            item.classList.add("is-expanded");
            item.querySelector(".timeline-expand")?.setAttribute("aria-expanded", "true");
        }

        list.appendChild(item);
    }

    timeline.appendChild(list);

    if (force || wasNearBottom || events.length === 1) {
        timeline.scrollTop = timeline.scrollHeight;
    }
}

function createEventItem(event) {
    const category = normalizeToken(event.category, "SYSTEM");
    const level = normalizeToken(event.level, "INFO");

    const item = document.createElement("article");
    item.className = `timeline-item category-${category.toLowerCase()} level-${level.toLowerCase()}`;
    item.dataset.eventId = String(event.id || "");

    const marker = document.createElement("div");
    marker.className = "timeline-marker";
    marker.textContent = iconForEvent(category, level);
    marker.setAttribute("aria-hidden", "true");

    const content = document.createElement("div");
    content.className = "timeline-content";

    const header = document.createElement("div");
    header.className = "timeline-header";

    const title = document.createElement("strong");
    title.className = "timeline-title";
    title.textContent = event.title || category;

    const headerRight = document.createElement("div");
    headerRight.className = "timeline-header-right";

    const time = document.createElement("time");
    time.className = "timeline-time";
    time.dateTime = event.time || "";
    time.textContent = formatEventTime(event.time);

    const expand = document.createElement("button");
    expand.type = "button";
    expand.className = "timeline-expand";
    expand.textContent = "⌄";
    expand.title = "Details tonen";
    expand.setAttribute("aria-expanded", "false");
    expand.addEventListener("click", () => {
        const expanded = item.classList.toggle("is-expanded");
        expand.setAttribute("aria-expanded", expanded ? "true" : "false");
        expand.title = expanded ? "Details verbergen" : "Details tonen";
    });

    headerRight.append(time, expand);
    header.append(title, headerRight);
    content.appendChild(header);

    if (event.detail) {
        const detail = document.createElement("div");
        detail.className = "timeline-detail";
        detail.textContent = String(event.detail);
        content.appendChild(detail);
    }

    const meta = createEventMeta(event, category, level);
    if (meta) content.appendChild(meta);

    const details = createEventDetails(event);
    if (details) content.appendChild(details);

    item.append(marker, content);
    return item;
}

function createEventMeta(event, category, level) {
    const data = event.data && typeof event.data === "object" ? event.data : {};
    const parts = [];

    if (data.satellite) parts.push(String(data.satellite));
    if (data.receiver) parts.push(String(data.receiver));
    if (data.frequency_mhz !== undefined && data.frequency_mhz !== null) {
        const frequency = Number(data.frequency_mhz);
        parts.push(Number.isFinite(frequency) ? `${frequency.toFixed(3)} MHz` : `${data.frequency_mhz} MHz`);
    }
    if (data.pipeline) parts.push(String(data.pipeline));
    if (parts.length === 0 && category === "SCHEDULER" && data.mode) parts.push(`Mode ${data.mode}`);
    if (parts.length === 0 && level !== "INFO" && level !== "SYSTEM") parts.push(level);
    if (parts.length === 0) return null;

    const meta = document.createElement("div");
    meta.className = "timeline-meta";
    meta.textContent = parts.join(" · ");
    return meta;
}

function createEventDetails(event) {
    const data = event.data && typeof event.data === "object" ? event.data : {};
    const rows = flattenEventData(data);
    if (rows.length === 0) return null;

    const details = document.createElement("div");
    details.className = "timeline-details";

    for (const [label, value] of rows) {
        const row = document.createElement("div");
        row.className = "timeline-detail-row";

        const key = document.createElement("span");
        key.textContent = label;

        const val = document.createElement("code");
        val.textContent = value;

        row.append(key, val);
        details.appendChild(row);
    }

    return details;
}

function flattenEventData(data) {
    const preferred = [
        ["mission_id", "Mission ID"], ["satellite", "Satelliet"], ["receiver", "Receiver"],
        ["receiver_serial", "Serienummer"], ["frequency_mhz", "Frequentie MHz"], ["mode", "Mode"],
        ["pipeline", "Pipeline"], ["progress", "Voortgang"], ["result", "Resultaat"],
        ["success", "Succes"], ["peak_snr_db", "Piek-SNR dB"], ["frames", "Frames"],
        ["cadu_bytes", "CADU bytes"], ["image_count", "Afbeeldingen"], ["output_path", "Outputpad"]
    ];

    const rows = [];
    const used = new Set();

    for (const [key, label] of preferred) {
        if (data[key] === undefined || data[key] === null || typeof data[key] === "object") continue;
        rows.push([label, formatDetailValue(data[key], key)]);
        used.add(key);
    }

    for (const [key, value] of Object.entries(data)) {
        if (used.has(key) || value === undefined || value === null || typeof value === "object") continue;
        rows.push([humanizeKey(key), formatDetailValue(value, key)]);
        if (rows.length >= 14) break;
    }

    return rows;
}

function formatDetailValue(value, key) {
    if (typeof value === "boolean") return value ? "Ja" : "Nee";
    if (key === "progress" && Number.isFinite(Number(value))) return `${value}%`;
    return String(value);
}

function humanizeKey(key) {
    return String(key).replace(/_/g, " ").replace(/\b\w/g, char => char.toUpperCase());
}

function extractMissionId(event) {
    const data = event.data && typeof event.data === "object" ? event.data : {};
    if (data.mission_id) return String(data.mission_id);
    if (data.cancelled_job && typeof data.cancelled_job === "object" && data.cancelled_job.mission_id) {
        return String(data.cancelled_job.mission_id);
    }
    return null;
}

function iconForEvent(category, level) {
    if (level === "ERROR") return "❌";
    if (level === "WARNING") return "⚠️";
    if (level === "SUCCESS" && category !== "PREFLIGHT") return "🎉";
    return CATEGORY_ICONS[category] || "•";
}

function formatEventTime(value) {
    if (!value) return "--:--:--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        const match = String(value).match(/(\d{2}:\d{2}:\d{2})/);
        return match ? match[1] : String(value);
    }
    return new Intl.DateTimeFormat("nl-NL", {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
    }).format(date);
}

function normalizeToken(value, fallback) {
    const token = String(value || fallback).trim().toUpperCase();
    return token.replace(/[^A-Z0-9_-]/g, "-") || fallback;
}

function isNearBottom(element) {
    return element.scrollHeight - element.scrollTop - element.clientHeight <= BOTTOM_TOLERANCE_PX;
}

function createEmptyState(text) {
    const empty = document.createElement("div");
    empty.className = "timeline-empty";
    empty.textContent = text;
    return empty;
}

function showTimelineError(timeline) {
    if (timeline.querySelector(".timeline-list")) return;
    timeline.replaceChildren(createEmptyState("Event Timeline tijdelijk niet bereikbaar."));
}
