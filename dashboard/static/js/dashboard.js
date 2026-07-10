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
import {
    updateScheduler,
    updateSchedulerCountdown,
    updateSchedulerServerOffset
} from "./scheduler.js";

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
        updateRecentCaptures(data.recent_captures);

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
refreshDashboard();

setInterval(refreshDashboard, 5000);
setInterval(updateCountdown, 1000);
setInterval(updateSchedulerCountdown, 1000);
