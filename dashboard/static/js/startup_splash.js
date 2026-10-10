(() => {
    "use strict";

    const splash = document.getElementById("sdrcc-startup-splash");
    if (!splash) return;

    const sessionKey = "sdrcc-startup-splash-v06524";
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const startupAudio = new Audio("/static/audio/startup-space-v3.mp3");
    startupAudio.preload = "none";
    const retryButton = document.getElementById("sdrcc-startup-sound-retry");
    const startupToggle = document.getElementById("mission-startup-sound-enabled");
    const startupTest = document.getElementById("mission-startup-sound-test");
    const soundKey = "sdrcc.missionSounds.startupEnabled";

    function storedValue(key) {
        try { return localStorage.getItem(key); } catch (_) { return null; }
    }
    function startupEnabled() { return storedValue(soundKey) !== "false"; }
    function masterEnabled() { return storedValue("sdrcc.missionSounds.enabled") !== "false"; }
    function volumePercent() {
        const stored = Number(storedValue("sdrcc.missionSounds.volume") ?? 35);
        return Number.isFinite(stored) ? Math.max(0, Math.min(100, stored)) : 35;
    }
    function playStartupSound(test = false) {
        if (!test && (!startupEnabled() || !masterEnabled() || reducedMotion)) {
            return Promise.resolve(false);
        }
        const volume = Math.min(1, volumePercent() / 100 * 0.85);
        if (volume <= 0) return Promise.resolve(false);
        try {
            startupAudio.pause();
            startupAudio.currentTime = 0;
            startupAudio.volume = volume;
            return Promise.resolve(startupAudio.play()).then(
                () => true,
                error => {
                    // Browsers can require a click before they allow sound.
                    if (!test && error?.name === "NotAllowedError" && retryButton
                        && !splash.hidden && !splash.classList.contains("is-leaving")) {
                        retryButton.hidden = false;
                    }
                    console.debug("Startup audio unavailable:", error);
                    return false;
                }
            );
        } catch (error) {
            console.debug("Startup audio unavailable:", error);
            return Promise.resolve(false);
        }
    }

    if (startupToggle) {
        startupToggle.checked = startupEnabled();
        startupToggle.addEventListener("change", () => {
            try { localStorage.setItem(soundKey, String(startupToggle.checked)); } catch (_) {}
        });
    }
    startupTest?.addEventListener("click", () => { void playStartupSound(true); });

    function wasShown() {
        try {
            return window.sessionStorage.getItem(sessionKey) === "shown";
        } catch (_error) {
            return false;
        }
    }

    function markShown() {
        try {
            window.sessionStorage.setItem(sessionKey, "shown");
        } catch (_error) {
            // The splash still works when browser storage is unavailable.
        }
    }

    if (wasShown()) return;

    const openedAt = performance.now();
    const minimumVisibleMs = reducedMotion ? 150 : 2750;
    let closing = false;
    let observer = null;
    let leaveTimer = null;
    let soundEndAt = 0;

    splash.hidden = false;
    window.requestAnimationFrame(() => splash.classList.add("is-visible"));

    function playWhileSplash(clicked = false) {
        if (clicked) {
            soundEndAt = Math.max(soundEndAt, performance.now() + 2300);
            scheduleExit();
        }
        void playStartupSound().then(played => {
            if (!played) return;
            soundEndAt = Math.max(soundEndAt, performance.now() + 2250);
            scheduleExit();
        });
    }
    retryButton?.addEventListener("click", () => {
        retryButton.hidden = true;
        playWhileSplash(true);
    });
    if (startupEnabled() && masterEnabled() && volumePercent() > 0 && !reducedMotion) {
        playWhileSplash();
    }

    function finish() {
        splash.hidden = true;
        splash.classList.remove("is-visible", "is-leaving");
    }

    function scheduleExit() {
        if (!closing) return;
        if (leaveTimer !== null) window.clearTimeout(leaveTimer);
        const deadline = Math.max(openedAt + minimumVisibleMs, soundEndAt);
        leaveTimer = window.setTimeout(() => {
            markShown();
            if (retryButton) retryButton.hidden = true;
            splash.classList.add("is-leaving");
            window.setTimeout(finish, reducedMotion ? 0 : 400);
        }, Math.max(0, deadline - performance.now()));
    }

    function dismiss() {
        if (closing) return;
        closing = true;
        if (observer) observer.disconnect();
        scheduleExit();
    }

    function dashboardIsReady() {
        const cpu = document.getElementById("system-cpu");
        return Boolean(cpu && cpu.textContent.trim() && cpu.textContent.trim() !== "-");
    }

    if (dashboardIsReady()) {
        dismiss();
    } else {
        const cpu = document.getElementById("system-cpu");
        if (cpu) {
            observer = new MutationObserver(() => {
                if (dashboardIsReady()) dismiss();
            });
            observer.observe(cpu, {childList: true, characterData: true, subtree: true});
        }
    }

    window.setTimeout(dismiss, 4500);
})();
