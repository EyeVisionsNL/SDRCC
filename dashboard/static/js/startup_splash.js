(() => {
    "use strict";

    const splash = document.getElementById("sdrcc-startup-splash");
    if (!splash) return;

    const sessionKey = "sdrcc-startup-splash-v0540v";
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
    const minimumVisibleMs = reducedMotion ? 150 : 1350;
    let closing = false;
    let observer = null;

    splash.hidden = false;
    window.requestAnimationFrame(() => splash.classList.add("is-visible"));

    function finish() {
        splash.hidden = true;
        splash.classList.remove("is-visible", "is-leaving");
    }

    function dismiss() {
        if (closing) return;
        closing = true;
        if (observer) observer.disconnect();

        const elapsed = performance.now() - openedAt;
        const remaining = Math.max(0, minimumVisibleMs - elapsed);
        window.setTimeout(() => {
            markShown();
            splash.classList.add("is-leaving");
            window.setTimeout(finish, reducedMotion ? 0 : 400);
        }, remaining);
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
