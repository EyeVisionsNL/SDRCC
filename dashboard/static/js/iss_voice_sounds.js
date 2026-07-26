(() => {
    "use strict";
    const AUDIO = {
        start: "/static/audio/mission-start.wav",
        success: "/static/audio/mission-success.wav",
        failed: "/static/audio/mission-failed.wav",
        cancelled: "/static/audio/mission-cancelled.wav",
    };
    const players = Object.fromEntries(Object.entries(AUDIO).map(([key, url]) => [key, new Audio(url)]));
    let previous = null;
    let initialised = false;

    function enabled() {
        try { return localStorage.getItem("sdrcc.missionSounds.enabled") === "true"; }
        catch (_) { return false; }
    }
    function volume() {
        try { return Math.max(0, Math.min(1, Number(localStorage.getItem("sdrcc.missionSounds.volume") || 35) / 100)); }
        catch (_) { return 0.35; }
    }
    async function play(name) {
        if (!enabled() || !players[name]) return;
        try {
            const audio = players[name];
            audio.pause(); audio.currentTime = 0; audio.volume = volume();
            await audio.play();
        } catch (error) { console.debug("ISS Voice mission sound blocked:", error); }
    }
    function toast(title, detail, tone) {
        const host = document.getElementById("mission-notification-stack") || document.body;
        const item = document.createElement("div");
        item.className = `mission-notification tone-${tone || "info"}`;
        item.innerHTML = `<strong>${title}</strong>${detail ? `<span>${detail}</span>` : ""}`;
        host.appendChild(item);
        window.setTimeout(() => item.remove(), 7000);
    }
    function keyOf(state) {
        return `${state.mission_id || "none"}:${String(state.phase || "IDLE").toUpperCase()}:${state.updated_at || ""}`;
    }
    function notify(state) {
        const phase = String(state.phase || "IDLE").toUpperCase();
        const prevPhase = String(previous?.phase || "IDLE").toUpperCase();
        const satellite = state.satellite || "ISS (ZARYA)";
        if (phase === "RECORDING" && prevPhase !== "RECORDING") {
            play("start"); toast(`🛰 ISS Voice gestart — ${satellite}`, `${(Number(state.frequency_hz || 0)/1e6).toFixed(4)} MHz`, "live");
        } else if (phase === "FINISHED" && prevPhase !== "FINISHED" && state.success !== false) {
            play("success"); toast("✅ ISS Voice mission voltooid", state.detail || satellite, "success");
        } else if (phase === "FAILED" && prevPhase !== "FAILED") {
            play("failed"); toast("❌ ISS Voice mission failed", state.error || state.detail || satellite, "error");
        } else if (phase === "CANCELLED" && prevPhase !== "CANCELLED") {
            play("cancelled"); toast("⏹️ ISS Voice mission geannuleerd", state.detail || satellite, "cancelled");
        }
    }
    async function poll() {
        try {
            const response = await fetch("/api/receiver-monitor", {cache: "no-store"});
            const data = await response.json();
            const state = data?.providers?.iss_voice;
            if (!state || !state.ok) return;
            if (!initialised) { previous = state; initialised = true; return; }
            if (keyOf(state) !== keyOf(previous)) notify(state);
            previous = state;
        } catch (_) { /* next poll retries */ }
    }
    document.addEventListener("DOMContentLoaded", () => { poll(); window.setInterval(poll, 1000); });
})();
