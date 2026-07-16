import {getStatus} from "./api.js";
import {setupTabs} from "./tabs.js";
import {setupControls} from "./controls.js";
import {updateSystem} from "./system.js";
import {updateServices, updateServiceButtons} from "./services.js";
import {updateMissionEngine, updateNextPass, updateCountdown, updateServerOffset} from "./mission.js";
import {updateLatestCapture, updateRecentCaptures} from "./capture.js";
import {updateLiveLog, updateMissionTimeline} from "./timeline.js";
import {updateSdr} from "./sdr.js";
import {updateStatusbar} from "./statusbar.js";
import {setupMissionHistory} from "./history.js";
import {
    updateScheduler,
    updateSchedulerCountdown,
    updateSchedulerServerOffset
} from "./scheduler.js";

let recentCaptureSignature = "";
let selectedImageKey = "";
let latestRecentCaptures = [];

function captureKey(capture) {
    return String(capture?.relative_path || capture?.url || capture?.filename || "");
}

function capturesSignature(captures) {
    return (Array.isArray(captures) ? captures : [])
        .map(item => `${captureKey(item)}:${item.modified || ""}:${item.size_kb || ""}`)
        .join("|");
}

function applyImagesTabSelection(capture) {
    if (!capture) return;
    const image = document.getElementById("capture-image-images");
    if (image) image.src = `${capture.url}?selected=${Date.now()}`;

    const fields = {
        "capture-name-images": capture.filename,
        "capture-satellite-images": capture.satellite,
        "capture-pipeline-images": capture.pipeline,
        "capture-product-images": capture.product,
        "capture-resolution-images": capture.resolution,
        "capture-modified-images": capture.modified,
        "capture-size-images": capture.size_kb,
    };
    Object.entries(fields).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value ?? "-";
    });
}

function refreshRecentCaptures(captures) {
    latestRecentCaptures = Array.isArray(captures) ? captures : [];
    const signature = capturesSignature(latestRecentCaptures);
    if (signature === recentCaptureSignature) return;

    const wanted = selectedImageKey;
    recentCaptureSignature = signature;
    updateRecentCaptures(latestRecentCaptures);

    const selected = latestRecentCaptures.find(item => captureKey(item) === wanted);
    if (selected) {
        window.setTimeout(() => applyImagesTabSelection(selected), 0);
    } else if (latestRecentCaptures.length) {
        selectedImageKey = captureKey(latestRecentCaptures[0]);
    }
}

function setupImageSelectionMemory() {
    const gallery = document.getElementById("recent-captures");
    if (!gallery || gallery.dataset.selectionMemory === "1") return;
    gallery.dataset.selectionMemory = "1";
    gallery.addEventListener("click", event => {
        const image = event.target.closest("img");
        if (!image) return;
        const src = image.getAttribute("src") || "";
        const selected = latestRecentCaptures.find(item => src.includes(item.url));
        if (!selected) return;
        selectedImageKey = captureKey(selected);
        window.setTimeout(() => applyImagesTabSelection(selected), 0);
    });
}

async function refreshDashboard() {
    try {
        const data = await getStatus();

        updateServerOffset(data.server_time_epoch);
        updateSchedulerServerOffset(data.server_time_epoch);
        updateSystem(data);
        updateServices(data);
        updateServiceButtons(data);
        updateMissionEngine(data.mission);
        updateNextPass(data);
        updateSdr(data);
        updateStatusbar(data);
        updateScheduler(data);

        updateLiveLog(data.logs);
        updateMissionTimeline(data.logs);

        updateLatestCapture(data.latest_capture);
        refreshRecentCaptures(data.recent_captures);
        setupImageSelectionMemory();

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

    } catch (error) {
        console.error(error);
        updateLiveLog(["Dashboard update mislukt:", String(error)]);
    }
}

setupTabs();
setupControls(refreshDashboard);
setupMissionHistory();
refreshDashboard();

setInterval(refreshDashboard, 5000);
setInterval(updateCountdown, 1000);
setInterval(updateSchedulerCountdown, 1000);
