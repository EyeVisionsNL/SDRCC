async function fetchMissionEngine() {
    const response = await fetch("/api/mission-engine", {
        cache: "no-store",
    });

    if (!response.ok) {
        throw new Error("Mission Engine API fout");
    }

    return await response.json();
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = value;
    }
}

function updateMissionSteps(steps) {
    const container = document.getElementById("mission-steps");
    if (!container) {
        return;
    }

    container.innerHTML = "";

    for (const step of steps || []) {
        const item = document.createElement("div");
        item.className = `mission-step ${step.status || "pending"}`;
        item.textContent = step.name;
        container.appendChild(item);
    }
}

function updateMissionProgress(progress) {
    const bar = document.getElementById("mission-progress-bar");
    if (!bar) {
        return;
    }

    bar.style.width = `${progress || 0}%`;
}

async function updateMissionEngine() {
    try {
        const data = await fetchMissionEngine();

        setText("mission-phase", data.phase || "-");
        setText("mission-detail", data.detail || "-");
        updateMissionProgress(data.progress || 0);
        updateMissionSteps(data.steps || []);
    } catch (error) {
        setText("mission-phase", "IDLE");
        setText("mission-detail", `Mission Engine niet bereikbaar: ${error.message}`);
        updateMissionProgress(0);
        updateMissionSteps([]);
    }
}

updateMissionEngine();
setInterval(updateMissionEngine, 2500);
