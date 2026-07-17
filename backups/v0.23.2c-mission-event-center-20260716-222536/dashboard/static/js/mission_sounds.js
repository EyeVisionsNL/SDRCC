(() => {
    "use strict";

    const STORAGE_ENABLED = "sdrcc.missionSounds.enabled";
    const STORAGE_VOLUME = "sdrcc.missionSounds.volume";
    const START_SOUND_URL = "/static/audio/mission-start.wav";

    let initialized = false;
    let previousState = null;
    let audioUnlocked = false;
    let playInProgress = false;

    const audio = new Audio(START_SOUND_URL);
    audio.preload = "auto";

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
        audio.volume = normalized / 100;
        const valueElement = byId("mission-sounds-volume-value");
        if (valueElement) valueElement.textContent = `${Math.round(normalized)}%`;
    }

    async function unlockAudio() {
        if (audioUnlocked) return true;
        try {
            const oldVolume = audio.volume;
            audio.volume = 0;
            await audio.play();
            audio.pause();
            audio.currentTime = 0;
            audio.volume = oldVolume;
            audioUnlocked = true;
            setStatus(readEnabled() ? "Mission Sounds gereed." : "Mission Sounds staan uit.", readEnabled() ? "is-ready" : "is-muted");
            return true;
        } catch (error) {
            setStatus("Audio is nog geblokkeerd; gebruik de testknop.", "is-muted");
            return false;
        }
    }

    async function playMissionStart({ test = false } = {}) {
        if (playInProgress) return;
        if (!test && !readEnabled()) return;
        if (!audioUnlocked) {
            const unlocked = await unlockAudio();
            if (!unlocked) return;
        }

        playInProgress = true;
        try {
            audio.pause();
            audio.currentTime = 0;
            applyVolume(readVolume());
            await audio.play();
            setStatus(test ? "Startgeluid wordt afgespeeld." : "Mission start — audio afgespeeld.", "is-ready");
        } catch (error) {
            console.error("Mission start sound mislukt:", error);
            setStatus("Startgeluid kon niet worden afgespeeld.", "is-error");
        } finally {
            playInProgress = false;
        }
    }

    function normalizeState(snapshot) {
        return String(snapshot?.state || snapshot?.live_rf?.state || "UNKNOWN").trim().toUpperCase();
    }

    function handleMissionState(snapshot) {
        const state = normalizeState(snapshot);

        if (!initialized) {
            initialized = true;
            previousState = state;
            return;
        }

        if (state === "RECORDING" && previousState !== "RECORDING") {
            playMissionStart();
        }

        previousState = state;
    }

    function setupControls() {
        const enabled = byId("mission-sounds-enabled");
        const volume = byId("mission-sounds-volume");
        const test = byId("mission-sounds-test");

        const enabledValue = readEnabled();
        const volumeValue = readVolume();

        if (enabled) {
            enabled.checked = enabledValue;
            enabled.addEventListener("change", () => {
                localStorage.setItem(STORAGE_ENABLED, String(enabled.checked));
                setStatus(enabled.checked ? "Mission Sounds staan aan." : "Mission Sounds staan uit.", enabled.checked ? "is-ready" : "is-muted");
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
                await playMissionStart({ test: true });
            });
        }

        document.addEventListener("pointerdown", unlockAudio, { once: true, passive: true });
        window.addEventListener("sdrcc:mission-state", event => handleMissionState(event.detail || {}));

        setStatus(enabledValue ? "Klik eenmaal in het dashboard om audio te activeren." : "Mission Sounds staan uit.", enabledValue ? "" : "is-muted");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setupControls, { once: true });
    } else {
        setupControls();
    }
})();
