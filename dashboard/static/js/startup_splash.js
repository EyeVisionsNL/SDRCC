(() => {
    "use strict";

    const splash = document.getElementById("sdrcc-startup-splash");
    if (!splash) return;

    const sessionKey = "sdrcc-startup-splash-v06526";
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const startupAudio = new Audio("/static/audio/startup-space-v3.mp3");
    // Warm the short soundtrack early; the logo itself never needs a Play button.
    startupAudio.preload = "auto";
    const startupToggle = document.getElementById("mission-startup-sound-enabled");
    const startupTest = document.getElementById("mission-startup-sound-test");
    const startupStatus = document.getElementById("mission-startup-sound-status");
    let gestureRetryArmed = false;
    let splashFinished = false;
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
    function showBlockedStatus() {
        if (!startupStatus) return;
        startupStatus.hidden = false;
        startupStatus.textContent = "De browser blokkeert automatisch geluid. Sta autoplay met geluid toe voor deze SDRCC-website in je browserinstellingen.";
    }
    function clearBlockedStatus() {
        if (startupStatus) startupStatus.hidden = true;
    }
    function disarmGestureRetry() {
        if (!gestureRetryArmed) return;
        gestureRetryArmed = false;
        document.removeEventListener("pointerdown", retryOnGesture, true);
        document.removeEventListener("keydown", retryOnGesture, true);
    }
    function retryOnGesture(event) {
        if (event.type === "keydown" && !["Enter", " ", "Spacebar"].includes(event.key)) return;
        disarmGestureRetry();
        if (splashFinished || splash.hidden || splash.classList.contains("is-leaving")
            || !startupEnabled() || !masterEnabled() || volumePercent() <= 0) return;
        // play() is called inside the trusted user gesture, not later in a timer.
        // The logo remains visible until the short sound has completed.
        playWhileSplash();
    }
    function armGestureRetry() {
        if (gestureRetryArmed || splashFinished || splash.hidden
            || splash.classList.contains("is-leaving")) return;
        gestureRetryArmed = true;
        document.addEventListener("pointerdown", retryOnGesture, true);
        document.addEventListener("keydown", retryOnGesture, true);
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
                () => {
                    if (!test) {
                        disarmGestureRetry();
                        clearBlockedStatus();
                    }
                    return true;
                },
                error => {
                    if (!test && error?.name === "NotAllowedError") {
                        showBlockedStatus();
                        // A natural interaction with the visible logo can unlock
                        // autoplay; no extra button or post-splash replay.
                        armGestureRetry();
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
            clearBlockedStatus();
            if (!startupToggle.checked) disarmGestureRetry();
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

    function playWhileSplash() {
        void playStartupSound().then(played => {
            if (!played) return;
            soundEndAt = Math.max(soundEndAt, performance.now() + 2250);
            scheduleExit();
        });
    }
    if (startupEnabled() && masterEnabled() && volumePercent() > 0 && !reducedMotion) {
        playWhileSplash();
    }

    function finish() {
        splashFinished = true;
        disarmGestureRetry();
        splash.hidden = true;
        splash.classList.remove("is-visible", "is-leaving");
    }

    function scheduleExit() {
        if (!closing) return;
        if (leaveTimer !== null) window.clearTimeout(leaveTimer);
        const deadline = Math.max(openedAt + minimumVisibleMs, soundEndAt);
        leaveTimer = window.setTimeout(() => {
            markShown();
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
