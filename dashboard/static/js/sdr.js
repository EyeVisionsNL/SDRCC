import {setText} from "./utils.js";

export function updateSdr(data) {
    setText("sdr2-status", data.sdr2.status);
    setText("sdr2-profile", data.sdr2.profile);
    setText("sdr2-locked", data.sdr2.locked ? "YES" : "NO");
    setText("sdr2-process", data.sdr2.process ?? "-");
    setText("sdr2-updated", data.sdr2.updated);

    const container = document.getElementById("devices");
    if (!container) return;

    container.innerHTML = "";

    if (data.devices && data.devices.length > 0) {
        data.devices.forEach(device => {
            container.innerHTML += `
                <div class="device">
                    <strong>${device.name}</strong><br>
                    Serial: ${device.serial}<br>
                    Role: ${device.role}<br>
                    Locked: ${device.locked ? "YES" : "NO"}
                </div>
            `;
        });
    } else {
        container.innerHTML = "No SDR devices found.";
    }
}
