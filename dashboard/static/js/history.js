let refreshTimer = null;
let searchTimer = null;
let initialised = false;

function byId(id) {
    return document.getElementById(id);
}

function text(value, fallback = "-") {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
}

function number(value, fallback = "-") {
    if (value === null || value === undefined || value === "") return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString("nl-NL") : fallback;
}

function duration(value) {
    if (value === null || value === undefined) return "-";
    const total = Math.max(0, Math.round(Number(value) || 0));
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return minutes > 0 ? `${minutes}m ${String(seconds).padStart(2, "0")}s` : `${seconds}s`;
}

function resultClass(result) {
    return `result-${String(result || "other").toLowerCase().replaceAll(" ", "-")}`;
}

function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = text(value);
}

function detailItem(label, value, wide = false) {
    const item = document.createElement("div");
    item.className = `history-detail-item${wide ? " history-detail-wide" : ""}`;

    const name = document.createElement("span");
    name.textContent = label;
    const content = document.createElement("strong");
    content.textContent = text(value);

    item.append(name, content);
    return item;
}

function metric(label, value, extraClass = "") {
    const item = document.createElement("div");
    item.className = `history-metric ${extraClass}`.trim();
    const strong = document.createElement("strong");
    strong.textContent = text(value);
    const caption = document.createElement("span");
    caption.textContent = label;
    item.append(strong, caption);
    return item;
}

function missionCard(mission) {
    const card = document.createElement("article");
    card.className = `history-mission ${resultClass(mission.result)}`;
    card.dataset.missionId = text(mission.mission_id, "");

    const summary = document.createElement("div");
    summary.className = "history-mission-summary";

    const main = document.createElement("div");
    main.className = "history-main";
    const satellite = document.createElement("strong");
    satellite.textContent = `🛰 ${text(mission.satellite)}`;
    const date = document.createElement("small");
    date.textContent = `${text(mission.ended_at || mission.created_at)} · ${text(mission.mission_id)}`;
    main.append(satellite, date);

    const result = document.createElement("span");
    result.className = "history-result";
    result.textContent = text(mission.result);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "control-button history-details-button";
    button.textContent = "Details";

    summary.append(
        main,
        result,
        metric("Duur", duration(mission.duration_seconds)),
        metric("Piek-SNR", mission.peak_snr_db == null ? "-" : `${mission.peak_snr_db} dB`),
        metric("Frames", number(mission.frames), "history-hide-medium"),
        metric("Beelden", number(mission.image_count), "history-hide-medium"),
        button
    );

    const details = document.createElement("div");
    details.className = "history-mission-details";
    const grid = document.createElement("div");
    grid.className = "history-detail-grid";
    grid.append(
        detailItem("Mission ID", mission.mission_id),
        detailItem("Satelliet", mission.satellite),
        detailItem("Receiver", mission.receiver),
        detailItem("Serienummer", mission.receiver_serial),
        detailItem("Frequentie", mission.frequency_mhz == null ? "-" : `${mission.frequency_mhz} MHz`),
        detailItem("Mode", mission.mode),
        detailItem("Pipeline", mission.pipeline),
        detailItem("Resultaat", mission.result),
        detailItem("Start", mission.started_at || mission.created_at),
        detailItem("Einde", mission.ended_at),
        detailItem("CADU-bytes", number(mission.cadu_bytes)),
        detailItem("Status", mission.status),
        detailItem("Detail", mission.detail, true),
        detailItem("Fout", mission.error, true),
        detailItem("Outputmap", mission.output_path, true)
    );
    details.appendChild(grid);

    button.addEventListener("click", () => {
        card.classList.toggle("open");
        button.textContent = card.classList.contains("open") ? "Sluiten" : "Details";
    });

    card.append(summary, details);
    return card;
}

function renderStatistics(statistics = {}) {
    setText("history-stat-total", number(statistics.total, "0"));
    setText("history-stat-success", `${number(statistics.success_rate, "0")}%`);
    setText("history-stat-images", number(statistics.total_images, "0"));
    setText("history-stat-duration", duration(statistics.average_duration_seconds));
    setText("history-stat-snr", statistics.best_peak_snr_db == null ? "-" : `${statistics.best_peak_snr_db} dB`);
    setText("history-stat-frames", number(statistics.total_frames, "0"));
}

function renderMissions(missions = []) {
    const list = byId("mission-history-list");
    if (!list) return;
    list.innerHTML = "";

    if (!missions.length) {
        const empty = document.createElement("div");
        empty.className = "history-empty";
        empty.textContent = "Geen missies gevonden voor deze selectie.";
        list.appendChild(empty);
        return;
    }

    missions.forEach(mission => list.appendChild(missionCard(mission)));
}

function currentParameters() {
    const params = new URLSearchParams();
    params.set("limit", byId("history-limit")?.value || "100");

    const result = byId("history-result-filter")?.value || "";
    const query = byId("history-search")?.value.trim() || "";
    if (result) params.set("result", result);
    if (query) params.set("q", query);
    return params;
}

export async function refreshMissionHistory() {
    const list = byId("mission-history-list");
    if (!list) return;

    try {
        const response = await fetch(`/api/mission-history?${currentParameters().toString()}`, {
            cache: "no-store"
        });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) {
            throw new Error(payload.error || "Mission History API fout");
        }
        renderStatistics(payload.statistics || {});
        renderMissions(payload.missions || []);
        setText("history-count", `${payload.count || 0} van ${payload.total || 0} missies`);
    } catch (error) {
        list.innerHTML = "";
        const message = document.createElement("div");
        message.className = "history-empty";
        message.textContent = `Mission History kon niet worden geladen: ${error.message}`;
        list.appendChild(message);
    }
}

function historyTabActive() {
    return byId("tab-history")?.classList.contains("active") === true;
}

export function setupMissionHistory() {
    if (initialised || !byId("tab-history")) return;
    initialised = true;

    byId("history-refresh")?.addEventListener("click", refreshMissionHistory);
    byId("history-result-filter")?.addEventListener("change", refreshMissionHistory);
    byId("history-limit")?.addEventListener("change", refreshMissionHistory);
    byId("history-search")?.addEventListener("input", () => {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(refreshMissionHistory, 300);
    });

    document.querySelector('[data-tab="history"]')?.addEventListener("click", refreshMissionHistory);
    refreshMissionHistory();

    refreshTimer = window.setInterval(() => {
        if (historyTabActive()) refreshMissionHistory();
    }, 15000);
}
