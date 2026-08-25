(() => {
    "use strict";

    const byId = (id) => document.getElementById(id);
    const state = {busy: false};

    function setMessage(message, kind = "") {
        const target = byId("home-position-result");
        if (!target) return;
        target.textContent = message;
        target.classList.remove("is-ok", "is-error", "is-busy");
        if (kind) target.classList.add(`is-${kind}`);
    }

    function renderPosition(position) {
        if (!position) return;
        byId("home-position-location").value = position.location || "Home";
        byId("home-position-latitude").value = Number(position.latitude).toFixed(6);
        byId("home-position-longitude").value = Number(position.longitude).toFixed(6);
        byId("home-position-altitude").value = Number(position.altitude_m || 0).toFixed(1);
        setMessage(
            `Configured: ${position.location || "Home"} · ` +
            `${Number(position.latitude).toFixed(6)}, ${Number(position.longitude).toFixed(6)} · ` +
            `${Number(position.altitude_m || 0).toFixed(1)} m ASL`,
            "ok"
        );
    }

    async function loadPosition() {
        try {
            const response = await fetch("/api/home-position", {cache: "no-store"});
            const payload = await response.json();
            if (!response.ok || payload.ok === false) {
                throw new Error(payload.message || "Home Position could not be loaded.");
            }
            renderPosition(payload.position);
        } catch (error) {
            setMessage(`Load failed: ${error.message}`, "error");
        }
    }

    function readForm() {
        return {
            location: byId("home-position-location").value.trim() || "Home",
            latitude: Number(byId("home-position-latitude").value),
            longitude: Number(byId("home-position-longitude").value),
            altitude_m: Number(byId("home-position-altitude").value),
        };
    }

    function setBusy(busy) {
        state.busy = busy;
        byId("home-position-save").disabled = busy;
        byId("home-position-browser").disabled = busy;
    }

    async function savePosition(event) {
        event.preventDefault();
        if (state.busy) return;
        setBusy(true);
        setMessage("Saving Home Position...", "busy");
        try {
            const response = await fetch("/api/home-position", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(readForm()),
            });
            const payload = await response.json();
            if (!response.ok || payload.ok === false) {
                throw new Error(payload.message || "Home Position could not be saved.");
            }
            renderPosition(payload.position);
            setMessage(payload.message || "Home Position saved.", "ok");

            // Existing consumers already read station.yaml; these events only refresh presentation.
            window.dispatchEvent(new CustomEvent("sdrcc:home-position-changed", {
                detail: payload.position,
            }));
            window.dispatchEvent(new CustomEvent("sdrcc:weather-planning-changed"));
        } catch (error) {
            setMessage(`Save failed: ${error.message}`, "error");
        } finally {
            setBusy(false);
        }
    }

    function useBrowserLocation() {
        if (state.busy) return;
        if (!navigator.geolocation) {
            setMessage("Browser geolocation is not available. Enter latitude and longitude manually.", "error");
            return;
        }
        setMessage("Requesting browser location...", "busy");
        navigator.geolocation.getCurrentPosition(
            (position) => {
                byId("home-position-latitude").value = Number(position.coords.latitude).toFixed(6);
                byId("home-position-longitude").value = Number(position.coords.longitude).toFixed(6);
                if (Number.isFinite(position.coords.altitude)) {
                    byId("home-position-altitude").value = Number(position.coords.altitude).toFixed(1);
                }
                setMessage("Browser position loaded into the form. Press Save Home Position to apply it.", "ok");
            },
            (error) => {
                setMessage(`Browser location failed: ${error.message}`, "error");
            },
            {enableHighAccuracy: true, timeout: 10000, maximumAge: 60000}
        );
    }

    function initialize() {
        const form = byId("home-position-form");
        if (!form) return;
        form.addEventListener("submit", savePosition);
        byId("home-position-browser")?.addEventListener("click", useBrowserLocation);
        document.querySelector('.tab-button[data-tab="system"]')?.addEventListener("click", () => {
            window.setTimeout(loadPosition, 0);
        });
        loadPosition();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
        initialize();
    }
})();
