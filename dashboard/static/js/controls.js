import {runActionApi} from "./api.js";

export function setupControls(refreshCallback) {
    const buttons = document.querySelectorAll(".control-button");

    buttons.forEach(button => {
        button.addEventListener("click", async () => {
            if (button.disabled) return;

            const missionAction = button.dataset.missionAction;
            if (missionAction) {
                await runMissionAction(missionAction, refreshCallback);
                return;
            }

            const actionId = button.dataset.action;
            if (!actionId) return;

            if (button.classList.contains("danger") && actionId === "record") {
                const confirmed = confirm("Are you sure you want to start Record Now?");
                if (!confirmed) return;
            }

            await runAction(actionId, refreshCallback);
        });
    });
}

async function runMissionAction(missionAction, refreshCallback) {
    const resultBox = document.getElementById("control-result");

    if (missionAction === "reset") {
        const confirmed = confirm("Reset Mission Engine to READY?");
        if (!confirmed) return;
    }

    if (resultBox) {
        resultBox.textContent = "Running Mission Engine action...";
        resultBox.className = "control-result warn";
    }

    try {
        const response = await fetch(`/api/mission-engine/${missionAction}`, {
            method: "POST",
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Mission Engine action failed");
        }

        if (resultBox) {
            resultBox.textContent = `Mission Engine: ${data.phase}`;
            resultBox.className = "control-result ok";
        }

        await refreshCallback();

    } catch (error) {
        console.error(error);

        if (resultBox) {
            resultBox.textContent = "Mission Engine error: " + String(error);
            resultBox.className = "control-result bad";
        }
    }
}

async function runAction(actionId, refreshCallback) {
    const resultBox = document.getElementById("control-result");

    if (resultBox) {
        resultBox.textContent = "Running action...";
        resultBox.className = "control-result warn";
    }

    try {
        const data = await runActionApi(actionId);

        if (resultBox) {
            resultBox.textContent = data.message || "Action completed.";
            resultBox.className = data.ok ? "control-result ok" : "control-result bad";
        }

        await refreshCallback();

    } catch (error) {
        console.error(error);

        if (resultBox) {
            resultBox.textContent = "Action failed: " + String(error);
            resultBox.className = "control-result bad";
        }
    }
}
