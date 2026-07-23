function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatTime(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
    });
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value ?? 0);
}

function renderEntry(entry) {
    const status = String(entry.status || "UNKNOWN").toUpperCase();
    const plugin = entry.plugin_id || "unknown";
    const executionId = entry.execution_id || "-";
    const timestamp = entry.updated_at || entry.created_at;
    return `
        <article class="execution-journal-entry-v043">
            <time datetime="${escapeHtml(timestamp || "")}">${escapeHtml(formatTime(timestamp))}</time>
            <strong>${escapeHtml(plugin)}</strong>
            <span class="execution-journal-status-v043 status-${escapeHtml(status.toLowerCase())}">${escapeHtml(status)}</span>
            <code title="${escapeHtml(executionId)}">${escapeHtml(executionId.slice(0, 8))}</code>
        </article>`;
}

export async function updateExecutionJournal() {
    const list = document.getElementById("execution-journal-list");
    if (!list) return;

    try {
        const response = await fetch("/api/execution-journal?limit=12&offset=0", {
            cache: "no-store"
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const payload = await response.json();
        if (!payload.ok || payload.read_only !== true) {
            throw new Error("invalid observer response");
        }

        const summary = payload.summary || {};
        setText("execution-journal-total", summary.total);
        setText("execution-journal-active", summary.active);
        setText("execution-journal-finished", summary.finished);
        setText("execution-journal-failed", summary.failed);
        setText("execution-journal-cancelled", summary.cancelled);

        const entries = Array.isArray(payload.entries) ? payload.entries : [];
        list.innerHTML = entries.length
            ? entries.map(renderEntry).join("")
            : '<div class="execution-journal-empty-v043">No journal entries in memory.</div>';
    } catch (error) {
        console.error("Execution Journal update failed", error);
        list.innerHTML = '<div class="execution-journal-empty-v043 error">Execution Journal temporarily unavailable.</div>';
    }
}
