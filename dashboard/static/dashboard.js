let nextPassEpoch = null;
let serverOffsetSeconds = 0;

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = value ?? "-";
    }
}

function setStatus(id, active) {
    const element = document.getElementById(id);
    if (!element) return;

    if (active) {
        element.textContent = "RUNNING";
        element.className = "ok";
    } else {
        element.textContent = "STOPPED";
        element.className = "bad";
    }
}

function setBar(id, value) {
    const bar = document.getElementById(id);
    if (!bar) return;

    const number = Number(value) || 0;
    bar.style.width = `${number}%`;
    bar.classList.remove("bar-ok", "bar-warn", "bar-bad");

    if (number >= 85) bar.classList.add("bar-bad");
    else if (number >= 65) bar.classList.add("bar-warn");
    else bar.classList.add("bar-ok");
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
    if (seconds <= 0) return "NU / ACTIEF";

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

function updateLiveLog(lines) {
    const logElement = document.getElementById("live-log");
    if (!logElement) return;

    if (!lines || lines.length === 0) {
        logElement.textContent = "Geen logregels.";
        return;
    }

    logElement.textContent = lines.join("\n");
    logElement.scrollTop = logElement.scrollHeight;
}

function lineLevel(line) {
    const upper = line.toUpperCase();

    if (upper.includes("ERROR") || upper.includes("MISLUKT") || upper.includes("FAILED")) return "error";
    if (upper.includes("WARN") || upper.includes("STOPPED") || upper.includes("TIMEOUT")) return "warn";

    return "info";
}

function updateMissionTimeline(lines) {
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

function updateMissionEngine(mission) {
    if (!mission) return;

    setText("mission-phase", mission.phase);
    setText("mission-detail", mission.detail);

    const bar = document.getElementById("mission-progress-bar");
    if (bar) {
        bar.style.width = `${mission.progress || 0}%`;
    }

    const stepsBox = document.getElementById("mission-steps");
    if (!stepsBox) return;

    const steps = mission.steps || [];
    const activeIndex = mission.active_index ?? 0;

    stepsBox.innerHTML = "";

    steps.forEach((step, index) => {
        const div = document.createElement("div");
        div.className = index === activeIndex ? "mission-step active" : "mission-step";
        div.textContent = index === activeIndex ? `➤ ${step}` : `· ${step}`;
        stepsBox.appendChild(div);
    });
}

function updateCaptureBlock(capture, suffix = "") {
    const empty = document.getElementById(`capture-empty${suffix}`);
    const content = document.getElementById(`capture-content${suffix}`);
    const image = document.getElementById(`capture-image${suffix}`);
    const name = document.getElementById(`capture-name${suffix}`);
    const modified = document.getElementById(`capture-modified${suffix}`);
    const size = document.getElementById(`capture-size${suffix}`);

    if (!empty || !content || !image || !name || !modified || !size) return;

    if (!capture) {
        empty.style.display = "block";
        empty.textContent = "Nog geen afbeelding gevonden.";
        content.classList.add("hidden");
        image.removeAttribute("src");
        return;
    }

    empty.style.display = "none";
    content.classList.remove("hidden");

    image.src = capture.url + "?t=" + Date.now();

    if (capture.live) {
        name.textContent = "🔴 LIVE PREVIEW · " + capture.filename;
    } else {
        name.textContent = capture.filename;
    }

    modified.textContent = capture.modified;
    size.textContent = capture.size_kb;
}

function updateLatestCapture(capture) {
    updateCaptureBlock(capture, "");
    updateCaptureBlock(capture, "-images");
}

function updateServiceButtons(data) {
    const aisActive = Boolean(data.ais && data.ais.active);
    const adsbActive = Boolean(data.adsb && data.adsb.active);

    document.querySelectorAll(".control-button").forEach(button => {
        button.disabled = false;
        button.classList.remove("disabled", "running");
    });

    const startAis = document.querySelector('[data-action="start_ais"]');
    const stopAis = document.querySelector('[data-action="stop_ais"]');
    const startAdsb = document.querySelector('[data-action="start_adsb"]');
    const stopAdsb = document.querySelector('[data-action="stop_adsb"]');

    if (startAis && stopAis) {
        if (aisActive) {
            startAis.disabled = true;
            startAis.classList.add("disabled");
            stopAis.classList.add("running");
        } else {
            stopAis.disabled = true;
            stopAis.classList.add("disabled");
            startAis.classList.add("running");
        }
    }

    if (startAdsb && stopAdsb) {
        if (adsbActive) {
            startAdsb.disabled = true;
            startAdsb.classList.add("disabled");
            stopAdsb.classList.add("running");
        } else {
            stopAdsb.disabled = true;
            stopAdsb.classList.add("disabled");
            startAdsb.classList.add("running");
        }
    }
}

function updateStatusbar(data) {
    const left = document.getElementById("statusbar-left");
    const right = document.getElementById("statusbar-right");

    const ais = data.ais && data.ais.active ? "AIS OK" : "AIS OFF";
    const adsb = data.adsb && data.adsb.active ? "ADS-B OK" : "ADS-B OFF";
    const tle = data.tle_present ? "TLE OK" : "TLE MISSING";
    const cpu = data.system ? `CPU ${data.system.cpu_percent}%` : "CPU -";
    const phase = data.mission ? data.mission.phase : "MISSION -";

    if (left) {
        left.textContent = `READY | ${phase} | ${ais} | ${adsb} | ${tle} | ${cpu}`;
    }

    if (right) {
        const now = new Date();
        right.textContent = now.toLocaleTimeString("nl-NL");
    }
}

async function runAction(actionId) {
    const resultBox = document.getElementById("control-result");

    if (resultBox) {
        resultBox.textContent = "Actie wordt uitgevoerd...";
        resultBox.className = "control-result warn";
    }

    try {
        const response = await fetch("/api/action", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({action: actionId})
        });

        const data = await response.json();

        if (resultBox) {
            resultBox.textContent = data.message || "Actie uitgevoerd.";
            resultBox.className = data.ok ? "control-result ok" : "control-result bad";
        }

        await refreshDashboard();

    } catch (err) {
        console.error(err);

        if (resultBox) {
            resultBox.textContent = "Actie mislukt: " + String(err);
            resultBox.className = "control-result bad";
        }
    }
}

function setupControls() {
    const buttons = document.querySelectorAll(".control-button");

    buttons.forEach(button => {
        button.addEventListener("click", () => {
            if (button.disabled) return;

            const actionId = button.dataset.action;
            if (!actionId) return;

            if (button.classList.contains("danger") && actionId === "record") {
                const confirmed = confirm("Weet je zeker dat je Record NOW wilt starten?");
                if (!confirmed) return;
            }

            runAction(actionId);
        });
    });
}

function setupTabs() {
    const buttons = document.querySelectorAll(".tab-button");
    const pages = document.querySelectorAll(".tab-page");

    buttons.forEach(button => {
        button.addEventListener("click", () => {
            const tab = button.dataset.tab;

            buttons.forEach(item => item.classList.remove("active"));
            pages.forEach(page => page.classList.remove("active"));

            button.classList.add("active");

            const page = document.getElementById(`tab-${tab}`);
            if (page) {
                page.classList.add("active");
            }
        });
    });
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

        setBar("system-cpu-bar", data.system.cpu_percent);
        setBar("system-ram-bar", data.system.ram_percent);
        setBar("system-disk-bar", data.system.disk_percent);

        setText("sdr2-status", data.sdr2.status);
        setText("sdr2-profile", data.sdr2.profile);
        setText("sdr2-locked", data.sdr2.locked ? "YES" : "NO");
        setText("sdr2-process", data.sdr2.process ?? "-");
        setText("sdr2-updated", data.sdr2.updated);

        setStatus("ais-status", data.ais && data.ais.active);
        setStatus("ais-status-radio", data.ais && data.ais.active);

        setStatus("adsb-status", data.adsb && data.adsb.active);
        setStatus("adsb-status-radio", data.adsb && data.adsb.active);

        updateServiceButtons(data);
        updateStatusbar(data);
        updateMissionEngine(data.mission);

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

        if (container) {
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
                container.innerHTML = "Geen SDR devices gevonden.";
            }
        }

        const tleStatus = document.getElementById("tle-status");

        if (tleStatus) {
            if (data.tle_present) {
                tleStatus.innerText = "aanwezig";
                tleStatus.className = "ok";
            } else {
                tleStatus.innerText = "ontbreekt";
                tleStatus.className = "bad";
            }
        }

        updateLiveLog(data.logs);
        updateMissionTimeline(data.logs);
        updateLatestCapture(data.latest_capture);

    } catch (err) {
        console.error(err);
        updateLiveLog(["Dashboard update mislukt:", String(err)]);
    }
}

setupTabs();
setupControls();
refreshDashboard();

setInterval(refreshDashboard, 5000);
setInterval(updateCountdown, 1000);
