import {getStatus} from "./api.js";
import {setupTabs} from "./tabs.js";
import {setupControls} from "./controls.js";
import {updateSystem} from "./system.js?v=0.54.0f";
import {updateServices, updateServiceButtons} from "./services.js?v=0.54.0f";
import {updateMissionEngine, updateNextPass, updateCountdown, updateServerOffset} from "./mission.js?v=0.54.0e";
import {updateLatestCapture, updateRecentCaptures} from "./capture.js";
import {updateLiveLog, updateMissionTimeline} from "./timeline.js";
import {updateExecutionJournal} from "./execution_journal.js";
import {updateSdr} from "./sdr.js";
import {updateStatusbar} from "./statusbar.js";
import {setupMissionHistory} from "./history.js";
import {setupMissionAnalytics} from "./mission_analytics.js?v=0.54.0k-r1";
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
        updateMissionEngine(data);
        updateNextPass(data);
        updateSdr(data);
        updateStatusbar(data);
        updateScheduler(data);

        updateLiveLog(data.logs);
        updateMissionTimeline(data.logs);
        await updateExecutionJournal();

        updateLatestCapture(data.latest_capture);
        updateRecentCaptures(data.recent_captures);

        const tleStatus = document.getElementById("tle-status");
        if (tleStatus) {
            if (data.tle_present) {
                tleStatus.innerText = "present";
                tleStatus.className = "ok";
            } else {
                tleStatus.innerText = "missing";
                tleStatus.className = "bad";
            }
        }

    } catch (error) {
        console.error(error);
        updateLiveLog(["Dashboard update failed:", String(error)]);
    }
}

setupTabs();
setupControls(refreshDashboard);
setupMissionHistory();
setupMissionAnalytics();
refreshDashboard();

setInterval(refreshDashboard, 5000);
setInterval(updateCountdown, 1000);
setInterval(updateSchedulerCountdown, 1000);
