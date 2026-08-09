const LOG_API_URL = "/api/logs";
const LOG_REFRESH_MS = 5000;
const LOG_LIMIT = 240;
const BOTTOM_TOLERANCE_PX = 48;

let activeSource = "sdrcc";
let latestLines = [];
let refreshTimer = null;
let refreshSequence = 0;

function element(id) {
    return document.getElementById(id);
}

function logsTabIsActive() {
    return element("tab-logs")?.classList.contains("active") === true;
}

function nearBottom(output) {
    return output.scrollHeight - output.scrollTop - output.clientHeight <= BOTTOM_TOLERANCE_PX;
}

function updateSourceButtons() {
    document.querySelectorAll("[data-log-source]").forEach(button => {
        const selected = button.dataset.logSource === activeSource;
        button.classList.toggle("active", selected);
        button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
}

function renderLines({forceBottom = false} = {}) {
    const output = element("live-log");
    const search = element("log-search");
    const count = element("log-count");
    if (!output || !search || !count) return;

    const keepBottom = forceBottom || nearBottom(output);
    const query = search.value.trim().toLocaleLowerCase();
    const filtered = query
        ? latestLines.filter(line => String(line).toLocaleLowerCase().includes(query))
        : latestLines;

    output.textContent = filtered.length > 0
        ? filtered.join("\n")
        : (query ? "No matching log lines." : "No log lines available.");
    count.textContent = query
        ? `${filtered.length} of ${latestLines.length} lines`
        : `${latestLines.length} lines`;

    if (keepBottom) output.scrollTop = output.scrollHeight;
}

function setLoading(isLoading) {
    const refreshButton = element("log-refresh");
    const state = element("log-live-state");
    if (refreshButton) refreshButton.disabled = isLoading;
    if (state) {
        state.textContent = isLoading ? "UPDATING" : "LIVE";
        state.classList.toggle("updating", isLoading);
    }
}

function setMeta(text, isError = false) {
    const meta = element("log-updated");
    if (!meta) return;
    meta.textContent = text;
    meta.classList.toggle("error", isError);
}

async function refreshLogs({forceBottom = false} = {}) {
    if (!logsTabIsActive() || document.hidden) return;

    const sequence = ++refreshSequence;
    setLoading(true);

    try {
        const query = new URLSearchParams({source: activeSource, limit: String(LOG_LIMIT)});
        const response = await fetch(`${LOG_API_URL}?${query}`, {cache: "no-store"});
        const payload = await response.json();
        if (sequence !== refreshSequence) return;
        if (!response.ok || !payload.ok) {
            throw new Error(payload.error || `Log API returned HTTP ${response.status}`);
        }

        latestLines = Array.isArray(payload.lines) ? payload.lines.map(String) : [];
        renderLines({forceBottom});
        setMeta(`Updated ${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"})}`);
    } catch (error) {
        if (sequence !== refreshSequence) return;
        latestLines = [];
        renderLines();
        setMeta(error instanceof Error ? error.message : "Unable to load logs.", true);
    } finally {
        if (sequence === refreshSequence) setLoading(false);
    }
}

function startRefresh() {
    if (!logsTabIsActive() || document.hidden) return;
    refreshLogs({forceBottom: latestLines.length === 0});
    if (refreshTimer === null) {
        refreshTimer = window.setInterval(refreshLogs, LOG_REFRESH_MS);
    }
}

function stopRefresh() {
    if (refreshTimer !== null) {
        window.clearInterval(refreshTimer);
        refreshTimer = null;
    }
    refreshSequence += 1;
    setLoading(false);
}

function selectSource(source) {
    if (!source || source === activeSource) return;
    activeSource = source;
    latestLines = [];
    updateSourceButtons();
    renderLines();
    setMeta("Loading source...");
    refreshLogs({forceBottom: true});
}

export function setupLogs() {
    const page = element("tab-logs");
    if (!page || page.dataset.ready === "true") return;

    document.querySelectorAll("[data-log-source]").forEach(button => {
        button.addEventListener("click", () => selectSource(button.dataset.logSource));
    });
    element("log-search")?.addEventListener("input", () => renderLines());
    element("log-refresh")?.addEventListener("click", () => refreshLogs({forceBottom: true}));

    document.querySelectorAll(".tab-button").forEach(button => {
        button.addEventListener("click", () => {
            if (button.dataset.tab === "logs") startRefresh();
            else stopRefresh();
        });
    });

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) stopRefresh();
        else startRefresh();
    });
    window.addEventListener("beforeunload", stopRefresh, {once: true});

    page.dataset.ready = "true";
    updateSourceButtons();
    renderLines();
    startRefresh();
}
