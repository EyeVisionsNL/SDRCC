(() => {
    "use strict";

    const setText = (id, value) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    };

    const formatDb = value => {
        const number = Number(value);
        return Number.isFinite(number) ? `${number.toFixed(2)} dB` : "--.-- dB";
    };

    function render(data) {
        const state = String(data.state || "IDLE").toUpperCase();
        const stateElement = document.getElementById("mission-monitor-state");
        if (stateElement) {
            stateElement.textContent = state;
            stateElement.className = `live-rf-state live-rf-state-${state.toLowerCase().replaceAll(" ", "-")}`;
        }

        const hasImage = Boolean(data.image && data.image.url);
        const source = data.active ? "LIVE MISSION" : (hasImage ? "LAST SUCCESS" : "STANDBY");
        setText("mission-monitor-source", source);
        setText("mission-monitor-title", data.title || "No active weather mission");
        setText("mission-monitor-message", data.message || "Waiting for the next mission...");
        setText("mission-monitor-images", Number(data.image_count || 0).toLocaleString("en-US"));
        setText("mission-monitor-frames", Number(data.frames || 0).toLocaleString("en-US"));
        setText("mission-monitor-cadu", Number(data.cadu_bytes || 0).toLocaleString("en-US"));
        setText("mission-monitor-snr", formatDb(data.peak_snr_db));
        setText("mission-monitor-updated", data.updated_at ? `Updated ${data.updated_at}` : "Standby");

        const image = document.getElementById("mission-monitor-image");
        const imageLink = document.getElementById("mission-monitor-image-link");
        const placeholder = document.getElementById("mission-monitor-placeholder");
        if (!image || !imageLink || !placeholder) return;

        if (hasImage) {
            const cacheKey = data.image.modified || Date.now();
            const imageUrl = `${data.image.url}?v=${encodeURIComponent(cacheKey)}`;
            image.src = imageUrl;
            imageLink.href = data.image.url;
            imageLink.hidden = false;
            placeholder.hidden = true;
        } else {
            imageLink.hidden = true;
            imageLink.removeAttribute("href");
            image.removeAttribute("src");
            placeholder.hidden = false;
            setText("mission-monitor-placeholder-title", data.title || "No active weather mission");
            setText("mission-monitor-placeholder-text", data.message || "Waiting for the next mission...");
        }
    }

    async function refresh() {
        try {
            const response = await fetch("/api/mission-monitor", {cache: "no-store"});
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "Mission Monitor API error");
            render(data);
        } catch (error) {
            setText("mission-monitor-updated", "Unavailable");
            setText("mission-monitor-message", error.message);
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        if (!document.getElementById("mission-monitor-title")) return;
        refresh();
        window.setInterval(refresh, 4000);
    });
})();
