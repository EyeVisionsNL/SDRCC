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

export function updateMissionTimeline(lines) {
    const box = document.getElementById("mission-timeline");
    if (!box) return;

    if (!lines || lines.length === 0) {
        box.innerHTML = '<div class="timeline-empty">Geen timeline-data.</div>';
        return;
    }

    const interesting = lines
        .filter(line => {
            const lower = line.toLowerCase();
            return (
                lower.includes("dashboard actie") ||
                lower.includes("service") ||
                lower.includes("record") ||
                lower.includes("satdump") ||
                lower.includes("pass") ||
                lower.includes("ais") ||
                lower.includes("ads-b") ||
                lower.includes("tle")
            );
        })
        .slice(-12);

    if (interesting.length === 0) {
        box.innerHTML = '<div class="timeline-empty">Nog geen missie-events.</div>';
        return;
    }

    box.innerHTML = '<div class="timeline-list">' + interesting.map(line => {
        const level = lineLevel(line);
        return `<div class="timeline-item ${level}">${line}</div>`;
    }).join("") + '</div>';
}

function lineLevel(line) {
    const upper = line.toUpperCase();

    if (upper.includes("ERROR") || upper.includes("MISLUKT") || upper.includes("FAILED")) return "error";
    if (upper.includes("WARN") || upper.includes("STOPPED") || upper.includes("TIMEOUT")) return "warn";

    return "info";
}
