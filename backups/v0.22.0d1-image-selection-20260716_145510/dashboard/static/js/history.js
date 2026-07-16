let refreshTimer = null;
let searchTimer = null;
let initialised = false;
let selectedMissionId = null;
let currentMissions = [];

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
    if (value === null || value === undefined || value === "") return "-";
    const total = Math.max(0, Math.round(Number(value) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;

    if (hours > 0) return `${hours}u ${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
    if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
    return `${seconds}s`;
}

function resultClass(result) {
    return `result-${String(result || "other").toLowerCase().replaceAll(" ", "-")}`;
}

function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = text(value);
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

function detailItem(label, value, options = {}) {
    const item = document.createElement("div");
    item.className = `history-detail-item${options.wide ? " history-detail-wide" : ""}`;

    const name = document.createElement("span");
    name.textContent = label;

    const content = document.createElement(options.code ? "code" : "strong");
    content.textContent = text(value);

    item.append(name, content);
    return item;
}

function missionCard(mission) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `history-mission ${resultClass(mission.result)}`;
    card.dataset.missionId = text(mission.mission_id, "");
    card.setAttribute("aria-pressed", mission.mission_id === selectedMissionId ? "true" : "false");

    if (mission.mission_id === selectedMissionId) {
        card.classList.add("selected");
    }

    const top = document.createElement("div");
    top.className = "history-mission-top";

    const main = document.createElement("div");
    main.className = "history-main";

    const satellite = document.createElement("strong");
    satellite.textContent = `🛰 ${text(mission.satellite)}`;

    const date = document.createElement("small");
    date.textContent = text(mission.ended_at || mission.created_at);

    main.append(satellite, date);

    const result = document.createElement("span");
    result.className = "history-result";
    result.textContent = text(mission.result);

    top.append(main, result);

    const metrics = document.createElement("div");
    metrics.className = "history-mission-metrics";
    metrics.append(
        metric("Duur", duration(mission.duration_seconds)),
        metric("Piek-SNR", mission.peak_snr_db == null ? "-" : `${mission.peak_snr_db} dB`),
        metric("Beelden", number(mission.image_count)),
        metric("Max elev.", mission.max_elevation == null ? "-" : `${mission.max_elevation}°`)
    );

    const id = document.createElement("small");
    id.className = "history-mission-id";
    id.textContent = text(mission.mission_id);

    card.append(top, metrics, id);
    card.addEventListener("click", () => selectMission(mission.mission_id));
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
    currentMissions = missions;
    const list = byId("mission-history-list");
    if (!list) return;
    list.innerHTML = "";

    if (!missions.length) {
        selectedMissionId = null;
        const empty = document.createElement("div");
        empty.className = "history-empty";
        empty.textContent = "Geen missies gevonden voor deze selectie.";
        list.appendChild(empty);
        renderEmptyDetail("Selecteer een missie om de details te bekijken.");
        return;
    }

    if (!missions.some(mission => mission.mission_id === selectedMissionId)) {
        selectedMissionId = missions[0].mission_id;
    }

    missions.forEach(mission => list.appendChild(missionCard(mission)));

    if (selectedMissionId) {
        loadMissionDetail(selectedMissionId);
    }
}

function renderEmptyDetail(message = "Selecteer een missie om de details te bekijken.") {
    const panel = byId("mission-history-detail");
    if (!panel) return;
    panel.innerHTML = "";

    const empty = document.createElement("div");
    empty.className = "history-detail-empty";
    empty.textContent = message;
    panel.appendChild(empty);
}

function sectionTitle(title) {
    const heading = document.createElement("h3");
    heading.className = "history-detail-section-title";
    heading.textContent = title;
    return heading;
}

function statusMark(value) {
    const mark = document.createElement("span");
    mark.className = `history-quality-mark ${value ? "ok" : "missing"}`;
    mark.textContent = value ? "✓" : "–";
    return mark;
}

function qualityItem(label, value, displayValue = null) {
    const item = document.createElement("div");
    item.className = "history-quality-item";
    item.append(statusMark(Boolean(value)));

    const body = document.createElement("div");
    const name = document.createElement("span");
    name.textContent = label;
    const content = document.createElement("strong");
    content.textContent = displayValue === null ? (value ? "OK" : "Niet bevestigd") : text(displayValue);
    body.append(name, content);
    item.appendChild(body);
    return item;
}

function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
    if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
    if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
}

function fileItem(icon, label, info = {}) {
    const item = document.createElement("div");
    item.className = `history-file-item${info.available ? " available" : " unavailable"}`;

    const symbol = document.createElement("span");
    symbol.className = "history-file-icon";
    symbol.textContent = icon;

    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = label;
    const meta = document.createElement("small");
    meta.textContent = info.available
        ? `${number(info.count, "0")} bestand(en) · ${formatBytes(info.bytes)}`
        : "Niet beschikbaar";
    body.append(title, meta);
    item.append(symbol, body);
    return item;
}

function eventIcon(category) {
    const icons = {
        MISSION: "🛰",
        RECEIVER: "🎛",
        SATDUMP: "📡",
        PREFLIGHT: "✅",
        SCHEDULER: "⏰",
        SYSTEM: "⚙"
    };
    return icons[String(category || "").toUpperCase()] || "•";
}

function eventTime(value) {
    if (!value) return "-";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return text(value);
    return parsed.toLocaleTimeString("nl-NL", {hour: "2-digit", minute: "2-digit", second: "2-digit"});
}

function missionEventItem(event) {
    const item = document.createElement("div");
    item.className = `history-event history-event-${String(event.level || "info").toLowerCase()}`;

    const icon = document.createElement("span");
    icon.className = "history-event-icon";
    icon.textContent = eventIcon(event.category);

    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = text(event.title);
    const detail = document.createElement("small");
    detail.textContent = text(event.detail, "");
    body.append(title);
    if (detail.textContent) body.appendChild(detail);

    const time = document.createElement("time");
    time.textContent = eventTime(event.time);
    item.append(icon, body, time);
    return item;
}

function renderMissionDetail(payload) {
    const mission = payload.mission || {};
    const quality = payload.quality || {};
    const diagnostics = payload.diagnostics || {};
    const files = payload.files || {};
    const events = Array.isArray(payload.events) ? payload.events : [];
    const panel = byId("mission-history-detail");
    if (!panel) return;
    panel.innerHTML = "";

    const header = document.createElement("div");
    header.className = "history-detail-header";

    const identity = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = `🛰 ${text(mission.satellite)}`;
    const missionId = document.createElement("code");
    missionId.textContent = text(mission.mission_id);
    identity.append(title, missionId);

    const actions = document.createElement("div");
    actions.className = "history-detail-actions";

    const result = document.createElement("span");
    result.className = `history-result ${resultClass(mission.result)}`;
    result.textContent = text(mission.result);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "history-delete-button";
    deleteButton.title = "Complete missie verwijderen";
    deleteButton.setAttribute("aria-label", `Missie ${text(mission.mission_id)} verwijderen`);
    deleteButton.textContent = "🗑 Verwijderen";
    deleteButton.addEventListener("click", () => deleteMission(mission, deleteButton));

    actions.append(result, deleteButton);
    header.append(identity, actions);

    const qualityBlock = document.createElement("section");
    qualityBlock.className = `history-quality ${resultClass(quality.result || mission.result)}`;
    const qualityHeading = document.createElement("div");
    qualityHeading.className = "history-quality-heading";
    const qualityTitle = document.createElement("h3");
    qualityTitle.textContent = "Mission Quality";
    const qualityResult = document.createElement("strong");
    qualityResult.textContent = text(quality.result || mission.result);
    qualityHeading.append(qualityTitle, qualityResult);

    const qualityGrid = document.createElement("div");
    qualityGrid.className = "history-quality-grid";
    qualityGrid.append(
        qualityItem("Receiver lock", quality.receiver_lock),
        qualityItem("Recording", quality.recording),
        qualityItem("Decoder", quality.decoder),
        qualityItem("Beelden", Number(quality.images || 0) > 0, number(quality.images, "0")),
        qualityItem("Piek-SNR", quality.peak_snr_db != null, quality.peak_snr_db == null ? "-" : `${quality.peak_snr_db} dB`)
    );
    qualityBlock.append(qualityHeading, qualityGrid);

    const overview = document.createElement("div");
    overview.className = "history-detail-overview";
    overview.append(
        metric("Duur", duration(mission.duration_seconds)),
        metric("Piek-SNR", mission.peak_snr_db == null ? "-" : `${mission.peak_snr_db} dB`),
        metric("Frames", number(mission.frames)),
        metric("CADU-bytes", number(mission.cadu_bytes)),
        metric("Beelden", number(mission.image_count))
    );

    const summary = document.createElement("div");
    summary.className = "history-detail-grid";
    summary.append(
        detailItem("Receiver", mission.receiver),
        detailItem("Frequentie", mission.frequency_mhz == null ? "-" : `${mission.frequency_mhz} MHz`),
        detailItem("Mode", mission.mode),
        detailItem("Pipeline", mission.pipeline, {code: true}),
        detailItem("Gestart", mission.started_at),
        detailItem("Beëindigd", mission.ended_at),
        detailItem("Status", mission.status),
        detailItem("Progress", mission.progress == null ? "-" : `${mission.progress}%`),
        detailItem("Min. elevatie", mission.min_elevation == null ? "-" : `${mission.min_elevation}°`),
        detailItem("Max. elevatie", mission.max_elevation == null ? "-" : `${mission.max_elevation}°`),
        detailItem("Kwaliteit", quality.score == null ? "-" : `${quality.score}% · ${text(quality.grade)}`)
    );

    const filesGrid = document.createElement("div");
    filesGrid.className = "history-files-grid";
    filesGrid.append(
        fileItem("🎙", "Recording", files.recording),
        fileItem("🖼", "Images", files.images),
        fileItem("📄", "Log", files.logs),
        fileItem("📊", "Telemetry", files.telemetry)
    );

    const imageFiles = Array.isArray(files.image_files) ? files.image_files : [];
    const gallery = document.createElement("div");
    gallery.className = "history-gallery";

    const preview = document.createElement("div");
    preview.className = "history-preview";

    const galleryViewer = document.createElement("img");
    galleryViewer.loading = "lazy";
    galleryViewer.alt = "Mission image";

    const galleryCaption = document.createElement("small");
    const thumbnails = document.createElement("div");
    thumbnails.className = "history-gallery-thumbnails";

    function selectGalleryImage(item, button = null) {
        if (!item?.url) return;
        galleryViewer.src = `${item.url}?t=${Date.now()}`;
        galleryViewer.alt = `Mission image ${text(item.filename)}`;
        galleryCaption.textContent = text(item.relative_path || item.filename);
        thumbnails.querySelectorAll(".history-gallery-thumb").forEach(candidate => {
            candidate.classList.toggle("selected", candidate === button);
        });
    }

    if (imageFiles.length) {
        preview.append(galleryViewer, galleryCaption);
        imageFiles.forEach((item, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "history-gallery-thumb";
            button.title = text(item.relative_path || item.filename);

            const thumb = document.createElement("img");
            thumb.src = `${item.url}?t=${Date.now()}`;
            thumb.alt = text(item.filename);
            thumb.loading = "lazy";

            const label = document.createElement("span");
            label.textContent = text(item.filename);
            button.append(thumb, label);
            button.addEventListener("click", () => selectGalleryImage(item, button));
            thumbnails.appendChild(button);

            if (index === 0) selectGalleryImage(item, button);
        });
        gallery.append(preview, thumbnails);
    } else if (files.preview?.url) {
        const fallback = {
            url: files.preview.url,
            filename: files.preview.filename,
            relative_path: files.preview.relative_path,
        };
        preview.append(galleryViewer, galleryCaption);
        selectGalleryImage(fallback);
        gallery.appendChild(preview);
    } else {
        const empty = document.createElement("div");
        empty.className = "history-preview-empty";
        empty.textContent = "Geen afbeelding beschikbaar voor deze missie.";
        preview.appendChild(empty);
        gallery.appendChild(preview);
    }

    const eventList = document.createElement("div");
    eventList.className = "history-event-list";
    if (events.length) {
        events.forEach(event => eventList.appendChild(missionEventItem(event)));
    } else {
        const empty = document.createElement("div");
        empty.className = "history-event-empty";
        empty.textContent = "Geen bewaarde Event Bus-events voor deze missie.";
        eventList.appendChild(empty);
    }

    const technical = document.createElement("div");
    technical.className = "history-detail-grid";
    technical.append(
        detailItem("Receiver-ID", mission.receiver_id),
        detailItem("Serienummer", mission.receiver_serial),
        detailItem("Aangemaakt", mission.created_at),
        detailItem("Diagnostiek", diagnostics.available ? diagnostics.directory : "Niet beschikbaar", {wide: true, code: true}),
        detailItem("Outputmap", mission.output_path, {wide: true, code: true}),
        detailItem("Detail", mission.detail, {wide: true}),
        detailItem("Fout", mission.error, {wide: true})
    );

    panel.append(
        header,
        qualityBlock,
        sectionTitle("Mission Summary"),
        overview,
        summary,
        sectionTitle("Bestanden"),
        filesGrid,
        sectionTitle(`Mission Images (${imageFiles.length || files.images?.count || 0})`),
        gallery,
        sectionTitle("Mission Events"),
        eventList,
        sectionTitle("Technische details"),
        technical
    );
}


async function deleteMission(mission, button) {
    const missionId = text(mission?.mission_id, "");
    if (!missionId) return;

    const satellite = text(mission?.satellite, "Onbekende satelliet");
    const confirmed = window.confirm(
        `Complete missie verwijderen?\n\n${satellite}\n${missionId}\n\n` +
        "Alle opnames, beelden, telemetrie en historiegegevens van deze missie worden definitief verwijderd."
    );
    if (!confirmed) return;

    const originalLabel = button?.textContent || "🗑 Verwijderen";
    if (button) {
        button.disabled = true;
        button.textContent = "Verwijderen…";
    }

    try {
        const response = await fetch(`/api/mission-history/${encodeURIComponent(missionId)}`, {
            method: "DELETE",
            headers: {"Accept": "application/json"},
            cache: "no-store"
        });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) {
            throw new Error(payload.error || "Missie verwijderen is mislukt");
        }

        selectedMissionId = null;
        renderEmptyDetail("Missie verwijderd. Geschiedenis wordt bijgewerkt…");
        await refreshMissionHistory();
    } catch (error) {
        window.alert(`Missie kon niet worden verwijderd: ${error.message}`);
        if (button) {
            button.disabled = false;
            button.textContent = originalLabel;
        }
    }
}

async function loadMissionDetail(missionId) {
    const panel = byId("mission-history-detail");
    if (!panel || !missionId) return;

    panel.setAttribute("aria-busy", "true");
    try {
        const response = await fetch(`/api/mission-history/${encodeURIComponent(missionId)}`, {
            cache: "no-store"
        });
        const payload = await response.json();
        if (!response.ok || payload.ok === false || !payload.mission) {
            throw new Error(payload.error || "Mission Detail API fout");
        }
        renderMissionDetail(payload);
    } catch (error) {
        renderEmptyDetail(`Mission Detail kon niet worden geladen: ${error.message}`);
    } finally {
        panel.removeAttribute("aria-busy");
    }
}

function selectMission(missionId) {
    if (!missionId) return;
    selectedMissionId = missionId;

    document.querySelectorAll(".history-mission").forEach(card => {
        const selected = card.dataset.missionId === missionId;
        card.classList.toggle("selected", selected);
        card.setAttribute("aria-pressed", selected ? "true" : "false");
    });

    loadMissionDetail(missionId);
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
        renderEmptyDetail("Mission Detail is niet beschikbaar.");
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
    renderEmptyDetail();
    refreshMissionHistory();

    refreshTimer = window.setInterval(() => {
        if (historyTabActive()) refreshMissionHistory();
    }, 15000);
}
