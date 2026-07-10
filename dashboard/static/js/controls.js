import {runActionApi} from "./api.js";

export function setupControls(refreshCallback) {
    const buttons = document.querySelectorAll(".control-button");

    buttons.forEach(button => {
        button.addEventListener("click", async () => {
            if (button.disabled) return;

            const actionId = button.dataset.action;
            if (!actionId) return;

            if (button.classList.contains("danger") && actionId === "record") {
                const confirmed = confirm("Weet je zeker dat je Record NOW wilt starten?");
                if (!confirmed) return;
            }

            await runAction(actionId, refreshCallback);
        });
    });
}

async function runAction(actionId, refreshCallback) {
    const resultBox = document.getElementById("control-result");

    if (resultBox) {
        resultBox.textContent = "Actie wordt uitgevoerd...";
        resultBox.className = "control-result warn";
    }

    try {
        const data = await runActionApi(actionId);

        if (resultBox) {
            resultBox.textContent = data.message || "Actie uitgevoerd.";
            resultBox.className = data.ok ? "control-result ok" : "control-result bad";
        }

        await refreshCallback();

    } catch (error) {
        console.error(error);

        if (resultBox) {
            resultBox.textContent = "Actie mislukt: " + String(error);
            resultBox.className = "control-result bad";
        }
    }
}
