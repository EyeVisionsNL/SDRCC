import {setStatus} from "./utils.js";

export function updateServices(data) {
    setStatus("ais-status", data.ais && data.ais.active);
    setStatus("ais-status-radio", data.ais && data.ais.active);

    setStatus("adsb-status", data.adsb && data.adsb.active);
    setStatus("adsb-status-radio", data.adsb && data.adsb.active);
}

export function updateServiceButtons(data) {
    const aisActive = Boolean(data.ais && data.ais.active);
    const adsbActive = Boolean(data.adsb && data.adsb.active);

    document.querySelectorAll(".control-button").forEach(button => {
        button.disabled = false;
        button.classList.remove("disabled", "running");
    });

    setPair("start_ais", "stop_ais", aisActive);
    setPair("start_adsb", "stop_adsb", adsbActive);
}

function setPair(startAction, stopAction, active) {
    const startButton = document.querySelector(`[data-action="${startAction}"]`);
    const stopButton = document.querySelector(`[data-action="${stopAction}"]`);

    if (!startButton || !stopButton) return;

    if (active) {
        startButton.disabled = true;
        startButton.classList.add("disabled");
        stopButton.classList.add("running");
    } else {
        stopButton.disabled = true;
        stopButton.classList.add("disabled");
        startButton.classList.add("running");
    }
}
