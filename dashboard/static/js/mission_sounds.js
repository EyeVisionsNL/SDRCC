(() => {
    "use strict";

    const STORAGE_ENABLED = "sdrcc.missionSounds.enabled";
    const STORAGE_VOLUME = "sdrcc.missionSounds.volume";
    const BASE_TITLE = document.title;

    const SOUND_URLS = Object.freeze({
        start: "/static/audio/mission-start.wav",
        lock: "/static/audio/mission-lock.wav",
        image: "/static/audio/mission-image.wav",
        success: "/static/audio/mission-success.wav",
        noSync: "/static/audio/mission-no-sync.wav",
        failed: "/static/audio/mission-failed.wav",
        cancelled: "/static/audio/mission-cancelled.wav"
    });

    const audios = Object.fromEntries(
        Object.entries(SOUND_URLS).map(([key, url]) => {
            const audio = new Audio(url);
            audio.preload = "auto";
            return [key, audio];
        })
    );

    let initialized = false;
    let audioUnlocked = false;
    let previousState = "UNKNOWN";
    let previousMissionKey = "";
    let previousFrames = 0;
    let previousImages = 0;
    let previousResultKey = "";
    let titleResetTimer = null;

    function byId(id) {
        return document.getElementById(id);
    }

    function readEnabled() {
        const stored = localStorage.getItem(STORAGE_ENABLED);
        return stored === null ? true : stored === "true";
    }

    function readVolume() {
        const stored = Number(localStorage.getItem(STORAGE_VOLUME));
        if (!Number.isFinite(stored)) return 35;
        return Math.max(0, Math.min(100, Math.round(stored)));
    }

    function setStatus(message, className = "") {
        const element = byId("mission-sounds-status");
        if (!element) return;
        element.textContent = message;
        element.className = `mission-sounds-status ${className}`.trim();
    }

    function applyVolume(value) {
        const normalized = Math.max(0, Math.min(100, Number(value) || 0));
        for (const audio of Object.values(audios)) audio.volume = normalized / 100;
        const valueElement = byId("mission-sounds-volume-value");
        if (valueElement) valueElement.textContent = `${Math.round(normalized)}%`;
    }

    function ensureToastHost() {
        let host = byId("mission-event-center");
        if (host) return host;
        host = document.createElement("div");
        host.id = "mission-event-center";
        host.className = "mission-event-center";
        host.setAttribute("aria-live", "polite");
        host.setAttribute("aria-atomic", "false");
        document.body.appendChild(host);
        return host;
    }

    function showNotification({ icon, title, message = "", tone = "info", duration = 6500 }) {
        const host = ensureToastHost();
        const toast = document.createElement("div");
        toast.className = `mission-event-toast is-${tone}`;

        const iconElement = document.createElement("span");
        iconElement.className = "mission-event-icon";
        iconElement.textContent = icon;

        const copy = document.createElement("div");
        copy.className = "mission-event-copy";

        const strong = document.createElement("strong");
        strong.textContent = title;
        copy.appendChild(strong);

        if (message) {
            const small = document.createElement("small");
            small.textContent = message;
            copy.appendChild(small);
        }

        toast.append(iconElement, copy);
        host.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add("is-visible"));

        window.setTimeout(() => {
            toast.classList.remove("is-visible");
            window.setTimeout(() => toast.remove(), 350);
        }, duration);
    }

    function setLiveTitle(satellite) {
        if (titleResetTimer) {
            window.clearTimeout(titleResetTimer);
            titleResetTimer = null;
        }
        document.title = `🛰 LIVE · ${satellite || "Weather Mission"} | ${BASE_TITLE}`;
    }

    function setResultTitle(icon, result) {
        if (titleResetTimer) window.clearTimeout(titleResetTimer);
        document.title = `${icon} ${result} | ${BASE_TITLE}`;
        titleResetTimer = window.setTimeout(() => {
            document.title = BASE_TITLE;
            titleResetTimer = null;
        }, 15000);
    }

    function restoreTitle() {
        if (titleResetTimer) return;
        document.title = BASE_TITLE;
    }

    async function unlockAudio() {
        if (audioUnlocked) return true;
        const audio = audios.start;
        try {
            const oldVolume = audio.volume;
            audio.volume = 0;
            await audio.play();
            audio.pause();
            audio.currentTime = 0;
            audio.volume = oldVolume;
            audioUnlocked = true;
            setStatus(readEnabled() ? "Mission Event Center ready." : "Mission Sounds are off.", readEnabled() ? "is-ready" : "is-muted");
            return true;
        } catch (error) {
            setStatus("Audio is still blocked; use the test button.", "is-muted");
            return false;
        }
    }

    async function playSound(name, { test = false } = {}) {
        if (!test && !readEnabled()) return;
        const audio = audios[name];
        if (!audio) return;
        if (!audioUnlocked) {
            const unlocked = await unlockAudio();
            if (!unlocked) return;
        }
        try {
            for (const [key, candidate] of Object.entries(audios)) {
                if (key !== name && !candidate.paused) {
                    candidate.pause();
                    candidate.currentTime = 0;
                }
            }
            applyVolume(readVolume());
            audio.pause();
            audio.currentTime = 0;
            await audio.play();
            if (test) setStatus("Playing mission start sound.", "is-ready");
        } catch (error) {
            console.error(`Mission sound '${name}' mislukt:`, error);
            setStatus("Mission sound could not be played.", "is-error");
        }
    }

    function missionData(snapshot) {
        const mission = snapshot?.mission || snapshot || {};
        const rf = snapshot?.live_rf || mission.live_rf || {};
        const activeJob = mission.active_job || {};
        const lastResult = mission.last_result || snapshot?.last_result || {};
        const state = String(mission.state || mission.phase || rf.state || "UNKNOWN").trim().toUpperCase();
        const missionKey = String(activeJob.mission_id || rf.mission_id || "");
        const satellite = activeJob.satellite || rf.satellite || "Weather Mission";
        const receiver = activeJob.receiver || rf.receiver || "-";
        const frequencyHz = Number(activeJob.frequency || activeJob.frequency_hz || rf.frequency_hz || 0);
        const frames = Number(rf.frames ?? activeJob.frames ?? 0) || 0;
        const images = Number(rf.image_count ?? activeJob.image_count ?? 0) || 0;
        return { mission, rf, activeJob, lastResult, state, missionKey, satellite, receiver, frequencyHz, frames, images };
    }

    function formatFrequency(value) {
        const hz = Number(value);
        if (!Number.isFinite(hz) || hz <= 0) return "";
        return `${(hz / 1_000_000).toFixed(3)} MHz`;
    }

    function resultKey(result) {
        if (!result || typeof result !== "object") return "";
        return String(result.mission_id || result.id || result.ended_at || "") + ":" + String(result.result || result.status || "");
    }

    function notifyRecording(data) {
        playSound("start");
        const details = [data.receiver !== "-" ? data.receiver : "", formatFrequency(data.frequencyHz)].filter(Boolean).join(" · ");
        showNotification({ icon: "🛰", title: `Mission Started — ${data.satellite}`, message: details, tone: "live", duration: 7500 });
        setLiveTitle(data.satellite);
    }

    function notifyFirstFrame(data) {
        playSound("lock");
        showNotification({ icon: "📡", title: "Synchronisatie verkregen", message: `Eerste frame ontvangen · ${data.satellite}`, tone: "lock" });
    }

    function notifyFirstImage(data) {
        playSound("image");
        showNotification({ icon: "📷", title: "First Image Received", message: data.satellite, tone: "image" });
    }

    function notifyResult(result) {
        const raw = String(result?.result || result?.status || "").trim().toUpperCase();
        const satellite = result?.satellite || "Weather Mission";
        const images = Number(result?.image_count || 0);
        const peak = Number(result?.peak_snr_db);
        const extras = [];
        if (images > 0) extras.push(`${images} image${images === 1 ? "" : "s"}`);
        if (Number.isFinite(peak)) extras.push(`Peak SNR ${peak.toFixed(2)} dB`);
        const message = [satellite, extras.join(" · ")].filter(Boolean).join(" — ");

        if (raw === "SUCCESS") {
            playSound("success");
            showNotification({ icon: "✅", title: "Mission Completed", message, tone: "success", duration: 8000 });
            setResultTitle("✅", "SUCCESS");
        } else if (raw === "NO SYNC" || raw === "NO_SYNC") {
            playSound("noSync");
            showNotification({ icon: "⚠️", title: "No Sync", message: satellite, tone: "warning", duration: 8000 });
            setResultTitle("⚠️", "NO SYNC");
        } else if (raw === "FAILED" || raw === "NO SIGNAL" || raw === "NO IMAGES") {
            playSound("failed");
            showNotification({ icon: "❌", title: `Mission ${raw.toLowerCase()}`, message: satellite, tone: "error", duration: 8500 });
            setResultTitle("❌", raw);
        } else if (raw === "CANCELLED") {
            playSound("cancelled");
            showNotification({ icon: "⏹️", title: "Mission Cancelled", message: satellite, tone: "cancelled" });
            setResultTitle("⏹️", "CANCELLED");
        }
    }

    function handleMissionState(snapshot) {
        const data = missionData(snapshot);
        const currentResultKey = resultKey(data.lastResult);

        if (!initialized) {
            initialized = true;
            previousState = data.state;
            previousMissionKey = data.missionKey;
            previousFrames = data.frames;
            previousImages = data.images;
            previousResultKey = currentResultKey;
            if (data.state === "RECORDING") setLiveTitle(data.satellite);
            return;
        }

        const missionChanged = Boolean(data.missionKey && data.missionKey !== previousMissionKey);
        if (missionChanged) {
            previousFrames = 0;
            previousImages = 0;
        }

        if (data.state === "RECORDING" && previousState !== "RECORDING") notifyRecording(data);
        if (data.state === "RECORDING") setLiveTitle(data.satellite);

        if (data.frames > 0 && previousFrames <= 0) notifyFirstFrame(data);
        if (data.images > 0 && previousImages <= 0) notifyFirstImage(data);

        if (currentResultKey && currentResultKey !== previousResultKey) notifyResult(data.lastResult);
        else if (["READY", "STANDBY"].includes(data.state) && !titleResetTimer) restoreTitle();

        previousState = data.state;
        previousMissionKey = data.missionKey;
        previousFrames = data.frames;
        previousImages = data.images;
        previousResultKey = currentResultKey;
    }

    function setupControls() {
        const enabled = byId("mission-sounds-enabled");
        const volume = byId("mission-sounds-volume");
        const test = byId("mission-sounds-test");
        const enabledValue = readEnabled();
        const volumeValue = readVolume();

        ensureToastHost();

        if (enabled) {
            enabled.checked = enabledValue;
            enabled.addEventListener("change", () => {
                localStorage.setItem(STORAGE_ENABLED, String(enabled.checked));
                setStatus(enabled.checked ? "Mission Sounds are on." : "Mission Sounds are off.", enabled.checked ? "is-ready" : "is-muted");
            });
        }

        if (volume) {
            volume.value = String(volumeValue);
            applyVolume(volumeValue);
            volume.addEventListener("input", () => {
                const value = Number(volume.value);
                localStorage.setItem(STORAGE_VOLUME, String(value));
                applyVolume(value);
            });
        }

        if (test) {
            test.addEventListener("click", async () => {
                audioUnlocked = true;
                await playSound("start", { test: true });
                showNotification({ icon: "🚀", title: "Mission Event Center", message: "Startgeluid en melding werken.", tone: "live" });
            });
        }

        document.addEventListener("pointerdown", unlockAudio, { once: true, passive: true });
        window.addEventListener("sdrcc:mission-state", event => handleMissionState(event.detail || {}));
        setStatus(enabledValue ? "Click once in the dashboard to enable audio." : "Mission Sounds are off.", enabledValue ? "" : "is-muted");
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setupControls, { once: true });
    else setupControls();
})();
