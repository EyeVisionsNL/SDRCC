const API_URL = "/api/mission-history?limit=250";
let refreshTimer = null;
let loading = false;

function number(value, digits = 0) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "-";
    return parsed.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
}

function percent(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `${number(parsed, 1)}%` : "-";
}

function db(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `${number(parsed, 2)} dB` : "-";
}

function degrees(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `${number(parsed, 1)}°` : "-";
}

function duration(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) return "-";
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.round(seconds % 60);
    return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

function bytes(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "-";
    if (parsed >= 1024 ** 3) return `${number(parsed / 1024 ** 3, 2)} GB`;
    if (parsed >= 1024 ** 2) return `${number(parsed / 1024 ** 2, 2)} MB`;
    if (parsed >= 1024) return `${number(parsed / 1024, 1)} KB`;
    return `${number(parsed)} B`;
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}


function onOff(value) {
    if (value === true) return "ON";
    if (value === false) return "OFF";
    return "Unknown";
}

function frequency(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `${number(parsed / 1_000_000, 3)} MHz` : "-";
}

function sampleRate(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `${number(parsed / 1_000_000, 3)} MS/s` : "-";
}

function gainLabel(config) {
    const mode = String(config?.gain_mode || "unknown").toLowerCase();
    if (mode === "manual") return `Manual · ${number(config?.manual_gain_db, 1)} dB`;
    if (mode === "auto") return "Auto";
    return "Unknown";
}

function confidenceClass(confidence) {
    const level = String(confidence?.level || "LOW").toLowerCase();
    return ["low", "medium", "high"].includes(level) ? level : "low";
}

function configurationFacts(config) {
    return [
        ["Satellite", config?.satellite || "Unknown"],
        ["Receiver", `${config?.receiver || "Unknown"} · ${config?.receiver_serial || "no serial"}`],
        ["Frequency", frequency(config?.frequency)],
        ["Sample rate", sampleRate(config?.sample_rate)],
        ["Gain", gainLabel(config)],
        ["DC Block", onOff(config?.dc_block)],
        ["IQ Swap", onOff(config?.iq_swap)],
        ["Pipeline", config?.pipeline || "Unknown"],
    ];
}

function renderBestRfConfiguration(intelligence) {
    const container = document.getElementById("analytics-rf-best");
    if (!container) return;
    const best = intelligence?.best_observed_configuration;
    setText("analytics-rf-status", String(intelligence?.status || "LEARNING"));

    const confidenceElement = document.getElementById("analytics-rf-confidence");
    const confidence = best?.confidence || {level: "LOW", label: "Low"};
    if (confidenceElement) {
        confidenceElement.textContent = `${confidence.label || "Low"} confidence`;
        confidenceElement.className = `mission-intelligence-confidence ${confidenceClass(confidence)}`;
    }

    if (!best) {
        container.innerHTML = '<div class="mission-analytics-empty">No complete RF configurations have been stored yet.</div>';
        return;
    }

    container.innerHTML = `
        <div class="mission-intelligence-configuration">
            <div class="mission-intelligence-facts">
                ${configurationFacts(best).map(([label, value]) => `
                    <span><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></span>
                `).join("")}
            </div>
            <div class="mission-intelligence-outcome">
                <span><small>Observed score</small><strong>${number(best.score, 1)}</strong></span>
                <span><small>Missions</small><strong>${number(best.missions)}</strong></span>
                <span><small>Success</small><strong>${percent(best.success_rate)}</strong></span>
                <span><small>Avg. peak SNR</small><strong>${db(best.average_peak_snr_db)}</strong></span>
                <span><small>Avg. images</small><strong>${number(best.average_images, 1)}</strong></span>
                <span><small>Avg. elevation</small><strong>${degrees(best.average_max_elevation)}</strong></span>
            </div>
        </div>`;
}

function renderRfRanking(intelligence) {
    const container = document.getElementById("analytics-rf-configurations");
    if (!container) return;
    const rows = Array.isArray(intelligence?.configurations) ? intelligence.configurations : [];
    if (rows.length === 0) {
        container.innerHTML = '<div class="mission-analytics-empty">No complete RF configuration history available.</div>';
        return;
    }

    container.innerHTML = rows.slice(0, 5).map((config, index) => `
        <article class="mission-rf-rank-card">
            <div class="mission-rf-rank-number">#${index + 1}</div>
            <div class="mission-rf-rank-main">
                <div class="mission-rf-rank-title">
                    <strong>${escapeHtml(config?.satellite || "Unknown satellite")}</strong>
                    <span>${escapeHtml(config?.receiver || "Unknown receiver")} · ${escapeHtml(gainLabel(config))} · DC ${onOff(config?.dc_block)} · IQ ${onOff(config?.iq_swap)}</span>
                </div>
                <div class="mission-rf-rank-meta">
                    <span>${frequency(config?.frequency)}</span>
                    <span>${sampleRate(config?.sample_rate)}</span>
                    <span>${number(config?.missions)} mission${Number(config?.missions) === 1 ? "" : "s"}</span>
                    <span class="mission-rf-confidence-inline ${confidenceClass(config?.confidence)}">${escapeHtml(config?.confidence?.label || "Low")}</span>
                </div>
            </div>
            <div class="mission-rf-rank-metrics">
                <span><small>Score</small><strong>${number(config?.score, 1)}</strong></span>
                <span><small>Success</small><strong>${percent(config?.success_rate)}</strong></span>
                <span><small>Avg. SNR</small><strong>${db(config?.average_peak_snr_db)}</strong></span>
                <span><small>Images</small><strong>${number(config?.average_images, 1)}</strong></span>
            </div>
        </article>
    `).join("");
}

function renderRfIntelligence(intelligence, totalMissions) {
    renderBestRfConfiguration(intelligence || {});
    renderRfRanking(intelligence || {});
    const eligible = Number(intelligence?.eligible_missions || 0);
    const missing = Number(intelligence?.missing_rf_missions || 0);
    setText(
        "analytics-rf-coverage",
        `Based on ${number(eligible)} complete RF mission${eligible === 1 ? "" : "s"} · ${number(missing)} of ${number(totalMissions || 0)} missing complete RF history · learning thresholds: Medium 5, High 20`,
    );
}

function performanceCard(item, kind) {
    const name = item?.name || "Unknown";
    const missions = Number(item?.missions || 0);
    const successRate = Number(item?.success_rate || 0);
    const className = successRate >= 80 ? "good" : successRate >= 50 ? "warn" : "bad";
    const elevation = kind === "satellite"
        ? `<span>Avg. elevation<strong>${degrees(item?.average_max_elevation)}</strong></span>`
        : `<span>Avg. quality<strong>${number(item?.average_quality_score, 1)}</strong></span>`;

    return `
        <article class="mission-analytics-performance">
            <div class="mission-analytics-performance-title">
                <strong>${escapeHtml(name)}</strong>
                <span class="mission-analytics-rate ${className}">${percent(successRate)}</span>
            </div>
            <div class="mission-analytics-performance-grid">
                <span>Missions<strong>${number(missions)}</strong></span>
                <span>Successful<strong>${number(item?.success || 0)}</strong></span>
                <span>Avg. peak SNR<strong>${db(item?.average_peak_snr_db)}</strong></span>
                <span>Best peak SNR<strong>${db(item?.best_peak_snr_db)}</strong></span>
                <span>Total images<strong>${number(item?.total_images || 0)}</strong></span>
                ${elevation}
            </div>
        </article>`;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function renderPerformance(id, rows, kind) {
    const container = document.getElementById(id);
    if (!container) return;
    if (!Array.isArray(rows) || rows.length === 0) {
        container.innerHTML = '<div class="mission-analytics-empty">No statistics available.</div>';
        return;
    }
    container.innerHTML = rows.map(item => performanceCard(item, kind)).join("");
}

function renderBreakdown(id, values, total) {
    const container = document.getElementById(id);
    if (!container) return;
    const entries = Object.entries(values || {}).filter(([, count]) => Number(count) > 0);
    if (entries.length === 0) {
        container.innerHTML = '<div class="mission-analytics-empty">No statistics available.</div>';
        return;
    }
    const denominator = Math.max(Number(total) || 0, 1);
    container.innerHTML = entries
        .sort((a, b) => Number(b[1]) - Number(a[1]))
        .map(([label, count]) => {
            const ratio = Math.max(0, Math.min(100, Number(count) / denominator * 100));
            return `
                <div class="mission-analytics-breakdown-row">
                    <div><strong>${escapeHtml(label)}</strong><span>${number(count)} mission${Number(count) === 1 ? "" : "s"}</span></div>
                    <div class="mission-analytics-bar"><span style="width:${ratio.toFixed(1)}%"></span></div>
                    <b>${percent(ratio)}</b>
                </div>`;
        }).join("");
}


function missionLabel(mission) {
    const timestamp = mission?.started_at || mission?.created_at || "";
    const date = timestamp ? new Date(timestamp.replace(" ", "T")) : null;
    const dateLabel = date && !Number.isNaN(date.getTime())
        ? date.toLocaleDateString(undefined, {month: "short", day: "numeric"})
        : "Unknown date";
    return `${dateLabel} · ${mission?.satellite || "Unknown satellite"}`;
}

function resultClass(result) {
    const normalized = String(result || "OTHER").toUpperCase();
    if (normalized === "SUCCESS") return "good";
    if (["NO SYNC", "NO SIGNAL", "NO IMAGES"].includes(normalized)) return "warn";
    return "bad";
}

function renderMetricTrend(id, missions, field, formatter) {
    const container = document.getElementById(id);
    if (!container) return;
    const rows = (Array.isArray(missions) ? missions : [])
        .map(mission => ({mission, value: Number(mission?.[field])}))
        .filter(row => Number.isFinite(row.value))
        .slice()
        .reverse();

    if (rows.length === 0) {
        container.innerHTML = '<div class="mission-analytics-empty">No trend data available.</div>';
        return;
    }

    const maximum = Math.max(...rows.map(row => row.value), 1);
    container.innerHTML = rows.map(({mission, value}) => {
        const width = Math.max(2, Math.min(100, value / maximum * 100));
        return `
            <div class="mission-analytics-trend-row">
                <div class="mission-analytics-trend-label">
                    <strong>${escapeHtml(missionLabel(mission))}</strong>
                    <span>${escapeHtml(mission?.receiver || "Unknown receiver")}</span>
                </div>
                <div class="mission-analytics-trend-value">${formatter(value)}</div>
                <div class="mission-analytics-trend-bar"><span style="width:${width.toFixed(1)}%"></span></div>
            </div>`;
    }).join("");
}

function renderOutcomeTimeline(id, missions) {
    const container = document.getElementById(id);
    if (!container) return;
    const rows = (Array.isArray(missions) ? missions : []).slice().reverse();
    if (rows.length === 0) {
        container.innerHTML = '<div class="mission-analytics-empty">No mission results available.</div>';
        return;
    }

    container.innerHTML = rows.map(mission => {
        const result = String(mission?.result || mission?.status || "OTHER").toUpperCase();
        return `
            <div class="mission-analytics-timeline-row">
                <span class="mission-analytics-timeline-dot ${resultClass(result)}" aria-hidden="true"></span>
                <div>
                    <strong>${escapeHtml(missionLabel(mission))}</strong>
                    <span>${escapeHtml(mission?.receiver || "Unknown receiver")}</span>
                </div>
                <b class="${resultClass(result)}">${escapeHtml(result)}</b>
            </div>`;
    }).join("");
}

function renderTrends(missions) {
    const rows = Array.isArray(missions) ? missions : [];
    renderMetricTrend("analytics-snr-trend", rows, "peak_snr_db", db);
    renderMetricTrend("analytics-images-trend", rows, "image_count", value => number(value));
    renderOutcomeTimeline("analytics-outcome-timeline", rows);

    const ratedElevation = rows.filter(mission => Number.isFinite(Number(mission?.max_elevation))).length;
    setText(
        "analytics-trend-coverage",
        `Showing ${number(rows.length)} missions · elevation available for ${number(ratedElevation)}`,
    );
}

function render(stats) {
    setText("analytics-total", number(stats.total || 0));
    setText("analytics-completed", `${number(stats.completed || 0)} completed`);
    setText("analytics-success-rate", percent(stats.success_rate));
    setText("analytics-success-count", `${number(stats.success || 0)} successful`);
    setText("analytics-average-snr", db(stats.average_peak_snr_db));
    setText("analytics-best-snr", `Best: ${db(stats.best_peak_snr_db)}`);
    setText("analytics-average-elevation", degrees(stats.average_max_elevation));
    setText("analytics-total-images", number(stats.total_images || 0));
    setText("analytics-average-duration", `Average duration: ${duration(stats.average_duration_seconds)}`);
    setText("analytics-total-frames", number(stats.total_frames || 0));
    setText("analytics-total-cadu", `CADU: ${bytes(stats.total_cadu_bytes || 0)}`);

    renderRfIntelligence(stats.rf_intelligence, stats.total);
    renderPerformance("analytics-receivers", stats.receiver_statistics, "receiver");
    renderPerformance("analytics-satellites", stats.satellite_statistics, "satellite");
    renderBreakdown("analytics-results", stats.result_counts, stats.total);
    renderBreakdown("analytics-quality", stats.quality_grade_counts, stats.total);
}

async function refreshAnalytics() {
    if (loading) return;
    loading = true;
    const button = document.getElementById("mission-analytics-refresh");
    if (button) button.disabled = true;
    setText("mission-analytics-message", "Loading analytics data...");

    try {
        const response = await fetch(API_URL, {cache: "no-store"});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (payload.ok !== true) throw new Error("Mission History API returned ok=false");
        const stats = payload.statistics || {};
        if (stats.schema_version !== 3) throw new Error("Analytics schema 3 is not available");
        render(stats);
        renderTrends(payload.missions || []);
        setText("mission-analytics-updated", `Updated ${new Date().toLocaleTimeString()}`);
        setText("mission-analytics-message", `Analytics based on ${number(stats.total || 0)} stored missions.`);
    } catch (error) {
        console.error("Mission Analytics refresh failed", error);
        setText("mission-analytics-message", `Analytics unavailable: ${error.message}`);
    } finally {
        loading = false;
        if (button) button.disabled = false;
    }
}

export function setupMissionAnalytics() {
    const refreshButton = document.getElementById("mission-analytics-refresh");
    if (!refreshButton) return;
    refreshButton.addEventListener("click", refreshAnalytics);

    const tabButton = document.querySelector('[data-tab="mission-analytics"]');
    if (tabButton) tabButton.addEventListener("click", refreshAnalytics);

    refreshAnalytics();
    refreshTimer = window.setInterval(refreshAnalytics, 30000);
}
