let nextPassEpoch = null;
let serverOffsetSeconds = 0;

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = value ?? "-";
    }
}

function formatUptime(seconds) {
    if (seconds == null) return "-";

    const days = Math.floor(seconds / 86400);
    seconds %= 86400;

    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;

    const minutes = Math.floor(seconds / 60);

    let text = "";

    if (days > 0) text += days + "d ";
    if (hours > 0 || days > 0) text += hours + "h ";

    text += minutes + "m";
    return text;
}

function formatCountdown(seconds) {
    if (seconds == null) return "-";

    if (seconds <= 0) {
        return "NU / ACTIEF";
    }

    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;

    const minutes = Math.floor(seconds / 60);
    const sec = seconds % 60;

    return (
        String(hours).padStart(2, "0") + ":" +
        String(minutes).padStart(2, "0") + ":" +
        String(sec).padStart(2, "0")
    );
}

function updateCountdown() {
    if (!nextPassEpoch) {
        setText("next-countdown", "-");
        return;
    }

    const browserNow = Math.floor(Date.now() / 1000);
    const estimatedServerNow = browserNow + serverOffsetSeconds;
    const remaining = nextPassEpoch - estimatedServerNow;

    setText("next-countdown", formatCountdown(remaining));
}

async function refreshDashboard() {
    try {
        const response = await fetch("/api/status");
        const data = await response.json();

        const browserNow = Math.floor(Date.now() / 1000);
        serverOffsetSeconds = data.server_time_epoch - browserNow;

        setText("system-cpu", data.system.cpu_percent + " %");
        setText("system-ram", data.system.ram_percent + " %");
        setText("system-disk", data.system.disk_percent + " %");
        setText("system-uptime", formatUptime(data.system.uptime_seconds));

        setText("sdr2-status", data.sdr2.status);
        setText("sdr2-profile", data.sdr2.profile);
        setText("sdr2-locked", data.sdr2.locked ? "YES" : "NO");
        setText("sdr2-process", data.sdr2.process ?? "-");
        setText("sdr2-updated", data.sdr2.updated);

        const adsb = document.getElementById("adsb-status");

        if (data.adsb && data.adsb.active) {
            adsb.innerText = "RUNNING";
            adsb.className = "ok";
        } else {
            adsb.innerText = "STOPPED";
            adsb.className = "bad";
        }

        if (data.next_pass) {
            nextPassEpoch = data.next_pass.start_epoch;

            setText("next-name", data.next_pass.name);
            setText("next-start", data.next_pass.start);
            setText("next-maximum", data.next_pass.maximum);
            setText("next-end", data.next_pass.end);
            setText("next-elevation", data.next_pass.max_elevation + "°");
            setText("next-azimuth", data.next_pass.azimuth + "°");
            setText("next-frequency", data.next_pass.frequency_mhz + " MHz");
            setText("next-mode", data.next_pass.mode);
            setText("next-pipeline", data.next_pass.pipeline);
        } else {
            nextPassEpoch = null;

            setText("next-name", "Geen passage");
            setText("next-start", "-");
            setText("next-maximum", "-");
            setText("next-end", "-");
            setText("next-elevation", "-");
            setText("next-azimuth", "-");
            setText("next-frequency", "-");
            setText("next-mode", "-");
            setText("next-pipeline", "-");
        }

        updateCountdown();

        const container = document.getElementById("devices");
        container.innerHTML = "";

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

        const tle = document.getElementById("tle-status");

        if (data.tle_present) {
            tle.innerText = "aanwezig";
            tle.className = "ok";
        } else {
            tle.innerText = "ontbreekt";
            tle.className = "bad";
        }

    } catch (err) {
        console.error(err);
    }
}

refreshDashboard();
setInterval(refreshDashboard, 5000);
setInterval(updateCountdown, 1000);
