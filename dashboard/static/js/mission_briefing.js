(() => {
    async function getStatus() {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) throw new Error("status api fout");
        return await response.json();
    }

    function setText(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    }

    function onlyTime(value) {
        if (!value || value === "-") return "-";
        const parts = value.split(" ");
        return parts.length > 1 ? parts[1] : value;
    }

    async function updateBriefing() {
        try {
            const data = await getStatus();
            const pass = (data.mission && data.mission.next_pass) || data.next_pass || null;

            if (!pass) {
                setText("briefing-name", "-");
                setText("briefing-mode", "-");
                setText("briefing-start", "-");
                setText("briefing-maximum", "-");
                setText("briefing-end", "-");
                setText("briefing-elevation", "-");
                setText("briefing-azimuth", "-");
                setText("briefing-frequency", "-");
                setText("briefing-pipeline", "-");
                return;
            }

            setText("briefing-name", pass.name || "-");
            setText("briefing-mode", pass.mode || "-");
            setText("briefing-start", onlyTime(pass.start));
            setText("briefing-maximum", onlyTime(pass.maximum));
            setText("briefing-end", onlyTime(pass.end));
            setText("briefing-elevation", pass.max_elevation !== undefined ? `${pass.max_elevation}°` : "-");
            setText("briefing-azimuth", pass.azimuth !== undefined ? `${pass.azimuth}°` : "-");
            setText("briefing-frequency", pass.frequency_mhz !== undefined ? `${pass.frequency_mhz} MHz` : "-");
            setText("briefing-pipeline", pass.pipeline || "-");
        } catch (error) {
            console.log("Mission briefing update mislukt:", error.message);
        }
    }

    updateBriefing();
    setInterval(updateBriefing, 3000);
})();
