(() => {
    "use strict";
    const text = (id, value) => { const el=document.getElementById(id); if(el) el.textContent=value ?? "-"; };
    const upper = value => String(value || "IDLE").toUpperCase();
    const activeMissionReceiver = snapshot => {
        const activeJob = snapshot.mission?.active_job;
        if (!activeJob || typeof activeJob !== "object") return "";
        return upper(
            activeJob.receiver
            || activeJob.receiver_name
            || activeJob.device
            || snapshot.receiver_manager?.reservation?.device?.number
            || snapshot.receiver_manager?.reservations?.sdr1?.mission_id === activeJob.mission_id && "SDR1"
            || snapshot.receiver_manager?.reservations?.sdr2?.mission_id === activeJob.mission_id && "SDR2"
            || ""
        );
    };

    function update(snapshot) {
        if (!snapshot || snapshot.loading) return;
        const activeJob = snapshot.mission?.active_job;
        const receiver = activeMissionReceiver(snapshot);
        const missionActive = Boolean(activeJob && typeof activeJob === "object");
        const sdr1Active = missionActive && receiver.includes("SDR1");
        const sdr2Active = missionActive && receiver.includes("SDR2");
        const state = upper(snapshot.state);

        text("mission-sdr1-badge", sdr1Active ? state : "READY");
        text("mission-sdr2-badge", sdr2Active ? state : "IDLE");
        text("mission-sdr2-state", sdr2Active ? state : "IDLE");
        text("mission-sdr2-detail", sdr2Active ? (snapshot.summary?.detail || "Mission active") : "No active mission");

        const rm = snapshot.receiver_manager?.receivers?.sdr2 || {};
        const reservation = rm.reservation || snapshot.receiver_manager?.reservations?.sdr2 || null;
        const device = rm.device || {};
        text("mission-sdr2-title", sdr2Active ? (snapshot.summary?.satellite || "Active mission") : (rm.available === false ? "Unavailable" : "Available"));
        text("mission-sdr2-receiver", device.number || "SDR2");
        text("mission-sdr2-serial", device.serial || "24006572");
        text("mission-sdr2-reservation", reservation ? (reservation.status || "Reserved") : "None");
        text("mission-sdr2-mission", sdr2Active ? (snapshot.summary?.satellite || "-") : "-");
        text("mission-sdr2-frequency", sdr2Active && snapshot.summary?.frequency_mhz ? `${Number(snapshot.summary.frequency_mhz).toFixed(3)} MHz` : "-");
        text("mission-sdr2-mode", sdr2Active ? (snapshot.summary?.mode || "-") : "-");
        text("mission-sdr2-pipeline", sdr2Active ? (snapshot.summary?.pipeline || "-") : "-");
        text("mission-sdr2-result", sdr2Active ? (snapshot.summary?.result || state) : "-");
    }


    if(window.MissionState) window.MissionState.subscribe(update);
    else window.addEventListener("sdrcc:mission-state", event => update(event.detail));
})();
