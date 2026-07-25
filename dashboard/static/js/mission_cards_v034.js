(() => {
    "use strict";

    const normalizeReceiver = (...values) => {
        for (const value of values) {
            const normalized = String(value || "").trim().toUpperCase().replaceAll("_", "");
            if (normalized.includes("SDR1") || normalized === "1") return "SDR1";
            if (normalized.includes("SDR2") || normalized === "2") return "SDR2";
        }
        return "";
    };

    function update(snapshot) {
        if (!snapshot || snapshot.loading) return;
        const activeJob = snapshot.mission?.active_job;
        if (!activeJob || typeof activeJob !== "object") return;

        const receiver = normalizeReceiver(
            activeJob.receiver_id,
            activeJob.receiver,
            activeJob.receiver_name,
            activeJob.device,
            snapshot.receiver_manager?.reservation?.device?.number
        );
        if (!receiver) return;

        const badge = document.getElementById(`mission-${receiver.toLowerCase()}-badge`);
        if (badge) badge.textContent = String(snapshot.state || "ACTIVE").toUpperCase();
    }

    if (window.MissionState) window.MissionState.subscribe(update);
    else window.addEventListener("sdrcc:mission-state", event => update(event.detail));
})();
